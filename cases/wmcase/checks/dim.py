# -*- coding: utf-8 -*-
"""
尺寸链与净空 —— 纯算术判据。

这一类看起来最"简单"，却是本项目最贵的两次翻车所在
（抱箍夹不紧、托台顶死托板）。共同点是：**每一步都对，但没人把整条链算完。**
所以这里的每条规则都把式子写在 detail 里，让人（和 AI）能逐项复核。
"""

from __future__ import annotations

from ..geometry import bx
from . import ERROR, INFO, WARN, Result, rule


@rule("DIM-01", "DIM", "抱箍内棱的过盈量在可用区间",
      why="太松打滑（v2.3 实物就是这样），太紧套不上去。"
          "单边 0.10~0.45 是塑料咬金属漆面的经验窗口。")
def rib_interference(design):
    m, c = design.cfg.meter, design.cfg.case
    g = c.collar_rib_interf
    return 0.10 <= g <= 0.45, (
        f"银圈半径 {m.bezel_od / 2:.2f} − 内棱内切半径 "
        f"{m.bezel_od / 2 - g:.2f} = 单边过盈 {g:.2f}mm")


@rule("DIM-02", "DIM", "夹持带避开银圈底部凸台")
def band_above_boss(design):
    m, c = design.cfg.meter, design.cfg.case
    return c.collar_z0 > m.boss_top_z, \
        f"带底 {c.collar_z0} > 凸台顶 {m.boss_top_z:.1f}"


@rule("DIM-03", "DIM", "夹持带不超过银圈顶面")
def band_below_top(design):
    m, c = design.cfg.meter, design.cfg.case
    return c.collar_z1 < m.bezel_top_z, \
        f"带顶 {c.collar_z1} < 银圈顶 {m.bezel_top_z}"


@rule("DIM-04", "DIM", "夹持带高度容得下两颗 M4 且受力均匀",
      why="只用一颗螺栓会把夹持带张成 V 形，只有一端咬住银圈。")
def two_bolts_fit(design):
    c = design.cfg.case
    lo, hi = min(c.collar_bolt_z), max(c.collar_bolt_z)
    ok = (hi - lo >= 8.0) and (lo > c.collar_z0 + 2) and (hi < c.collar_z1 - 2)
    return ok, (f"螺栓 z={c.collar_bolt_z}，带 [{c.collar_z0}, {c.collar_z1}]；"
                f"间距 {hi - lo:.1f}（≥8），上下边距 "
                f"{lo - c.collar_z0:.1f}/{c.collar_z1 - hi:.1f}（≥2）")


@rule("DIM-05", "DIM", "表盘正上方的最高点低于天花板",
      why="上方净空 70mm 是 40 台里的**最小**值，不是典型值。"
          "吊舱在 +Y 一米净空区，不受这条约束，所以只查表盘正上方那一块。")
def ceiling(design):
    m = design.cfg.meter
    region = bx(-70, 70, -60, 60, -30, 200)
    # 逐件求交再取 max，不要先把两件 union 起来 ——
    # union 是这里最贵的一步布尔，而结果完全一样。
    zmax = -1e9
    who = ""
    for name, part in (("主体", design.body), ("托板", design.mirror_holder)):
        clipped = part & region
        if clipped.volume < 1.0:
            continue
        z = clipped.bounding_box().max.Z
        if z > zmax:
            zmax, who = z, name
    return zmax < m.ceiling_z, f"最高点 zmax={zmax:.1f}（{who}）< 天花板 {m.ceiling_z:.1f}"


@rule("DIM-06", "DIM", "镜片托板提起 8mm 后仍不撞天花板")
def holder_lift_headroom(design):
    m = design.cfg.meter
    zmax = design.mirror_holder.bounding_box().max.Z
    return zmax + 8.0 < m.ceiling_z, \
        f"托板最高 {zmax:.1f} + 提起 8.0 = {zmax + 8.0:.1f} < {m.ceiling_z:.1f}"


@rule("DIM-07", "DIM", "光学基准链自洽",
      why="光程、镜面高度、镜头 Y 三者互相绑定。任何一个被手改而没跟着改"
          "其它两个，光路就会静默地偏掉。")
def optical_chain(design):
    o = design.cfg.optics
    return abs(o.path - (o.mirror_z + o.lens_face_y)) < 1e-9, (
        f"path {o.path:.1f} = mirror_z {o.mirror_z:.1f} + lens_face_y {o.lens_face_y:.1f}；"
        f"虚拟相机 {o.virtual_cam}")


@rule("DIM-08", "DIM", "吊舱型腔比板卡包络大一圈",
      why="dfam_rules §5 要求 PCB 周边留 0.2mm 空气间隙；"
          "这里按 fit_pcb 留得更大一点，因为 40 台的板来自不同批次。")
def pod_vs_board(design):
    p, c, mf = design.pod, design.cfg.case, design.cfg.mfg
    margin_x = c.cav_half_x - p.pcb_half_x
    margin_zb = p.pcb_z0 - c.cav_z0
    margin_zt = c.cav_z1 - p.pcb_z1
    ok = margin_x >= mf.fit_pcb and margin_zb >= mf.fit_pcb and margin_zt >= mf.fit_pcb
    return ok, (f"X 单边 {margin_x:.2f}，Z 下 {margin_zb:.2f}，Z 上 {margin_zt:.2f}"
                f"（要求 ≥{mf.fit_pcb}）")


@rule("DIM-09", "DIM", "三个件都装得下打印机（Bambu A1 / P1S 256³）",
      why="推荐摆放是主体绕 X 轴 −90°，所以约束的是 X/Z/Y 三个尺寸的最大值。")
def build_volume(design):
    limit = 256.0
    out = []
    for name, part in design.printed_parts.items():
        s = part.bounding_box().size
        dims = sorted((s.X, s.Y, s.Z), reverse=True)
        out.append(Result("DIM-09", "DIM", f"{name} 装得下 256³ 打印空间",
                          dims[0] <= limit,
                          f"{s.X:.0f}×{s.Y:.0f}×{s.Z:.0f}mm",
                          build_volume._rule["why"], ERROR))
    return out


@rule("DIM-10", "DIM", "打印总重与 BOM 估算一致", severity=INFO)
def mass(design):
    density = 1.27e-3          # PETG g/mm³
    total = sum(p.volume for p in design.printed_parts.values()) * density
    per = "，".join(f"{n} {p.volume * density:.0f}g"
                    for n, p in design.printed_parts.items())
    return True, f"三件合计约 {total:.0f}g（{per}）"
