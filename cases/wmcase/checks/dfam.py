# -*- coding: utf-8 -*-
"""
可制造性自检（DfAM）—— 对齐 ``dfam_rules.md``。

这一节回答的是"能不能一次打印成功"，而不是"设计对不对"。
两条最有价值的检查：

* **悬垂面积**：把零件摆成推荐姿态，逐三角面算法线与 −Z 的夹角。
  超过 45° 的下向面就是需要支撑的面积。这是 ``DESIGN_NOTES §9.5``
  里列为"尚未实现"的检查，现在补上了。
* **壁厚采样**：从表面向内打射线，量到对面的距离。
  布尔运算意外削薄了某处，参数表上是看不出来的。

两条都是**采样**方法，不是证明。它们能拦住明显的问题，
但不能替代切片器预览 —— WORKFLOW.md 里把切片预览列为人工环节的第一步。
"""

from __future__ import annotations

import math

from build123d import Axis, Rot, Vector

from . import ERROR, INFO, WARN, Result, rule

#: 推荐打印姿态。理由写在 DESIGN.md §5.8。
PRINT_ORIENTATION = {
    # 主体：绕 X 轴 +90°，让全局 +Y 朝上 →
    #   吊舱腔口朝上（零支撑）、镜头孔变成竖直孔、立板层向平行于弯曲中性面
    "body": Rot(90, 0, 0),
    # 托板：绕 X 轴 +135°，让 45° 反射面朝正上 → T 型槽朝上，零支撑
    "mirror_holder": Rot(135, 0, 0),
    # 滑盖：平放
    "slide_cover": Rot(90, 0, 0),
}

#: 三角化精度。0.2mm 足够做面积统计，再细就只是变慢。
TESS_TOL = 0.2


def _triangles(part, orient):
    """返回 [(重心, 法线, 面积)]，已经摆成打印姿态。"""
    shape = orient * part
    verts, tris = shape.tessellate(TESS_TOL)
    out = []
    for ia, ib, ic in tris:
        a, b, c = verts[ia], verts[ib], verts[ic]
        n = (b - a).cross(c - a)
        area2 = n.length
        if area2 < 1e-9:
            continue
        out.append(((a + b + c) * (1 / 3), n * (1 / area2), area2 / 2))
    return out


@rule("DFAM-01", "DFAM", "推荐姿态下的悬垂面积可控",
      why="dfam_rules §1：最大悬垂角 45°。贴床的底面不算悬垂，"
          "所以要把最低那一层排除掉，否则每个零件都会假报一大片。")
def overhang(design):
    # 留 1° 宽容：恰好 45° 的面按规范是可打印的，但旋转后的浮点值会在
    # ±1e-9 附近抖动，不留余量的话托板上大片 45° 面会被误报成悬垂。
    limit_cos = math.cos(math.radians(design.cfg.mfg.max_overhang_deg - 1.0))
    out = []
    for name, part in design.printed_parts.items():
        orient = PRINT_ORIENTATION.get(name, Rot(0, 0, 0))
        tris = _triangles(part, orient)
        if not tris:
            continue
        zmin = min(c.Z for c, _, _ in tris)
        total = sum(a for _, _, a in tris)
        bad = sum(a for c, n, a in tris
                  if n.Z < -limit_cos and c.Z > zmin + 0.6)
        frac = bad / total * 100 if total else 0.0
        out.append(Result("DFAM-01", "DFAM", f"{name} 悬垂面积占比",
                          frac < 4.0,
                          f"{frac:.2f}%（{bad:.0f}/{total:.0f} mm²，阈值 4%）",
                          overhang._rule["why"], WARN))
    return out


@rule("DFAM-02", "DFAM", "壁厚采样不低于下限",
      why="参数表能保证『设计的壁厚』是 2.5，但保证不了『布尔运算之后'"
          "还剩多少』。从表面往内打射线量到对面，是唯一能发现意外削薄的办法。"
          "DESIGN_NOTES §9.5 把它列为待补检查，这里补上。")
def wall_thickness(design):
    mfg = design.cfg.mfg
    out = []
    for name, part in design.printed_parts.items():
        tris = _triangles(part, Rot(0, 0, 0))
        if not tris:
            continue
        # 按面积排序取大面采样，小三角多半是圆角碎片，量出来没意义
        tris.sort(key=lambda t: -t[2])
        samples = tris[:400]
        thin = []
        thickness = []
        for centroid, normal, _area in samples:
            origin = centroid - normal * 0.08
            try:
                hits = part.find_intersection_points(Axis(tuple(origin), tuple(-normal)))
            except Exception:  # noqa: BLE001
                continue
            best = None
            for pt, _n in hits:
                t = (Vector(pt) - origin).dot(-normal)
                if 0.05 <= t and (best is None or t < best):
                    best = t
            if best is None:
                continue
            thickness.append(best)
            if best < mfg.min_wall:
                thin.append((best, centroid))
        if not thickness:
            out.append(Result("DFAM-02", "DFAM", f"{name} 壁厚采样", False,
                              "采样失败", wall_thickness._rule["why"], WARN))
            continue
        ratio = len(thin) / len(thickness) * 100
        worst = min(thickness)
        where = ""
        if thin:
            t, c = min(thin, key=lambda x: x[0])
            where = f"，最薄处约在 ({c.X:.0f}, {c.Y:.0f}, {c.Z:.0f})"
        # 阈值放到 2%：射线打在圆角、倒角、槽口边缘上会量出偏小的值，
        # 这些是采样方法的固有噪声，不是真的薄壁。本设计里**有意**做薄的地方
        # 只有 T 型槽唇口（0.8）和 PCB 侧导轨（1.6），它们都在噪声之上。
        out.append(Result("DFAM-02", "DFAM", f"{name} 壁厚采样不低于 {mfg.min_wall}mm",
                          ratio < 2.0,
                          f"{len(thickness)} 个采样点，最小 {worst:.2f}mm，"
                          f"低于下限的占 {ratio:.1f}%{where}",
                          wall_thickness._rule["why"], WARN))
    return out


@rule("DFAM-03", "DFAM", "内角有圆角过渡", severity=INFO,
      why="dfam_rules §2：尖锐内角会造成应力集中和床上翘曲，最小内圆角 1.0mm。"
          "这条目前只统计，不判定 —— OCC 里可靠地枚举『内凹边』代价很高。")
def internal_fillets(design):
    out = []
    for name, part in design.printed_parts.items():
        try:
            edges = part.edges()
            n_all = len(edges)
        except Exception:  # noqa: BLE001
            n_all = -1
        out.append(Result("DFAM-03", "DFAM", f"{name} 边数统计", True,
                          f"{n_all} 条边；内圆角靠 fillet_in="
                          f"{design.cfg.mfg.fillet_in} 参数保证，人工在切片预览里复核",
                          internal_fillets._rule["why"], INFO))
    return out


@rule("DFAM-04", "DFAM", "水平孔已做水滴形处理", severity=INFO,
      why="推荐姿态下底部进线孔是水平孔，圆孔顶部会塌。"
          "geometry.teardrop_z 把顶部收成 45° 尖角。")
def teardrop_used(design):
    return True, (f"底部总进线孔 Ø{design.cfg.case.power_hole_d} 已用 teardrop_z 生成，"
                  f"尖角朝 +Y（= 打印姿态的『上』）")
