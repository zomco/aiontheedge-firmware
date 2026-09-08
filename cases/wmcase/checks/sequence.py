# -*- coding: utf-8 -*-
"""
装配 / 拆卸顺序自检 —— "按这个顺序真的装得起来吗"。

沿 :mod:`wmcase.assembly` 定义的路径逐点做布尔：任何一步撞上，
报告会指出是第几步、路径上的哪一点、撞到了谁。

顺便验证两件静态检查看不出来的事：

* **净空**：运动过程中零件的最高点不能超过天花板（Z=77）；
* **顺序依赖**：每一步只和"这一步之前已经在现场的零件"比，
  所以"先装滑盖再装板卡"这种错误顺序会被真实地拦下来。
"""

from __future__ import annotations

from build123d import Part, Pos

from ..assembly import Step, install_sequence, service_sequence, teardown_sequence
from . import ERROR, WARN, Result, fmt, inter_vol, rule

#: Design 上可用作"现场已有零件"的属性名
_SCENE = {
    "meter": lambda d: d.meter,
    "body": lambda d: d.body,
    "board": lambda d: d.board,
    "slide_cover": lambda d: d.slide_cover,
    "mirror_holder": lambda d: d.mirror_holder,
    "mirror_glass": lambda d: d.mirror_glass,
    "leds": lambda d: d.leds,
    "foam": lambda d: d.foam,
}


def _moving(design, name: str) -> Part | None:
    fn = _SCENE.get(name)
    return fn(design) if fn else None


def _scene_parts(design, names) -> list[tuple[str, Part]]:
    """
    "现场已有的零件"列表 —— **刻意不把它们 union 成一个实体**。

    第一版是先 ``body + board + cover + meter`` 合成一个场景再做布尔，
    结果单次自检跑了 20 分钟还没完、内存吃到 3GB：那几个 union 本身
    就是最贵的布尔运算，而且每一步都要重算一遍。

    逐个求交、把体积加起来，结果完全一样（干涉体互不重叠），
    但快了两个数量级。**布尔运算的代价和形体复杂度是超线性的，
    能不合并就不要合并。**
    """
    out = []
    for n in names:
        p = _moving(design, n)
        if p is not None:
            out.append((n, p))
    return out


#: "天花板管辖区"：只有表盘正上方这一块受 70mm 净空约束。
#: 吊舱在 +Y 一米净空区，抬多高都没关系，不能一起算进去
#: （否则每一步都会假报"撞天花板"）。
CEILING_REGION_X = 70.0
CEILING_REGION_Y = 60.0


def _ceiling_probe(part):
    """
    把零件三角化成点云，供逐点核算净空用。

    为什么不用 ``(moved & region).bounding_box()``：那要为路径上每个点做一次
    布尔，一条路径就是好几秒。点云只需算一次，之后每个偏移量只是加减法。
    三角化的顶点足以包住实体的极值，对"最高点"这种判据是够用的。
    """
    verts, _tris = part.tessellate(1.0)
    return [(v.X, v.Y, v.Z) for v in verts]


def _max_z_in_region(cloud, dx, dy, dz) -> float:
    best = -1e9
    for x, y, z in cloud:
        if abs(x + dx) <= CEILING_REGION_X and abs(y + dy) <= CEILING_REGION_Y:
            best = max(best, z + dz)
    return best


def _walk(design, steps: list[Step], phase: str, rid: str):
    """沿路径仿真一组步骤，产出 Result。"""
    tol = design.cfg.mfg.vol_tol
    ceiling = design.cfg.meter.ceiling_z
    for st in steps:
        if not st.check_path or st.part == "-":
            continue
        mover = _moving(design, st.part)
        if mover is None:
            continue
        scene_names = tuple(n for n in st.present
                            if n != st.part and n not in st.ignore)
        scene = _scene_parts(design, scene_names)
        cloud = _ceiling_probe(mover)
        worst = 0.0
        worst_at = None
        worst_who = ""
        zmax = -1e9
        for dx, dy, dz in st.path:
            zmax = max(zmax, _max_z_in_region(cloud, dx, dy, dz))
            if not scene:
                continue
            moved = Pos(dx, dy, dz) * mover
            for name, other in scene:
                v = inter_vol(other, moved)
                if v > worst:
                    worst, worst_at, worst_who = v, (dx, dy, dz), name
        ignored = f"（忽略 {'/'.join(st.ignore)}）" if st.ignore else ""
        yield Result(rid, "SEQ", f"[{phase}{st.index}] {st.name}",
                     worst < tol,
                     f"路径最大干涉 {fmt(worst)}{ignored}"
                     + (f" @ 偏移 {worst_at} 撞到 {worst_who}" if worst_at else ""),
                     "静态干涉检查看不出顺序问题：板卡装得进、滑盖也装得上，"
                     "但先装滑盖就再也装不进板卡了。", ERROR)
        yield Result(rid + "-CLR", "SEQ", f"[{phase}{st.index}] 运动过程不撞天花板",
                     zmax < ceiling,
                     f"表盘正上方区域内的路径最高点 z={zmax:.1f} < 天花板 {ceiling:.1f}",
                     "上方净空 70mm 是全项目最紧的约束，"
                     "而且它是 40 台里的**最小**值。", ERROR)


@rule("SEQ-01", "SEQ", "整机装配顺序可行")
def install(design):
    return _walk(design, install_sequence(design.cfg), "装配", "SEQ-01")


@rule("SEQ-02", "SEQ", "每月抄表流程可行",
      why="这是唯一的日常操作：没有工具、光线不好、人站在楼梯上。"
          "它必须比装配流程更宽容。")
def service(design):
    return _walk(design, service_sequence(design.cfg), "抄表", "SEQ-02")


@rule("SEQ-03", "SEQ", "整机拆卸流程可行")
def teardown(design):
    return _walk(design, teardown_sequence(design.cfg), "拆卸", "SEQ-03")


@rule("SEQ-04", "SEQ", "取下托板后整机能抬到脱离银圈而不撞天花板",
      why="抱箍夹持带 16.5mm 高，整机必须垂直抬升这么多才能脱开银圈。"
          "上方只有 70mm，这条尺寸链必须算，不能试。")
def teardown_headroom(design):
    c, m = design.cfg.case, design.cfg.meter
    lift = c.collar_z1 - c.collar_z0 + 2.0
    over = design.body & Pos(0, 0, 0) * _dial_region(design)
    zmax = over.bounding_box().max.Z if over.volume > 1 else c.pod_z1
    return zmax + lift < m.ceiling_z, (
        f"表盘上方最高点 {zmax:.1f} + 抬升 {lift:.1f} = {zmax + lift:.1f} "
        f"< 天花板 {m.ceiling_z:.1f}")


def _dial_region(design):
    """表盘正上方的"天花板管辖区"。吊舱在 +Y 远处，不受这条约束。"""
    from ..geometry import bx
    return bx(-70, 70, -60, 60, -30, 200)


@rule("SEQ-06", "SEQ", "爆炸图里各零件互不重叠",
      why="爆炸图是给**人**看的，它唯一的作用就是让人一眼看出"
          "谁装在谁上面、按什么顺序、从哪个方向装进去。"
          "只要有两个件还叠在一起，这个作用就没了 —— 而分离距离是手填的常数，"
          "改了任何一个零件的尺寸都可能让它重新叠上。所以要有一条检查盯着。")
def exploded_separated(design):
    parts = [(ch.label, ch) for ch in design.exploded().children
             if not ch.label.startswith("99_")]     # 引导杆本来就穿过零件，跳过
    worst, pair = 0.0, ""
    for i in range(len(parts)):
        for j in range(i + 1, len(parts)):
            v = inter_vol(parts[i][1], parts[j][1])
            if v > worst:
                worst, pair = v, f"{parts[i][0]} ∩ {parts[j][0]}"
    return worst < 1.0, (f"{len(parts)} 个件两两求交，最大重叠 {fmt(worst)}"
                         + (f"（{pair}）" if pair else ""))


@rule("SEQ-05", "SEQ", "夹紧螺栓有徒手操作空间",
      why="蝶形螺丝要用手指拧。螺栓头周围如果被自家结构包住，"
          "现场只能拆掉别的件才能拧——这种事装配说明书里写不出来。")
def bolt_access(design):
    from ..geometry import cyl_x

    c = design.cfg.case
    tol = design.cfg.mfg.vol_tol
    out = []
    for bz in c.collar_bolt_z:
        # 螺栓两端各留一个 Ø18 × 25 的手指空间
        space = cyl_x(c.collar_slit_w / 2 + c.collar_ear_w, c.collar_slit_w / 2 + c.collar_ear_w + 25,
                      c.collar_or + 8, bz, 18.0)
        space += cyl_x(-(c.collar_slit_w / 2 + c.collar_ear_w + 25),
                       -(c.collar_slit_w / 2 + c.collar_ear_w), c.collar_or + 8, bz, 18.0)
        v = inter_vol(design.body, space)
        out.append(Result("SEQ-05", "SEQ", f"z={bz} 处螺栓有徒手操作空间",
                          v < tol, fmt(v), bolt_access._rule["why"], WARN))
    return out
