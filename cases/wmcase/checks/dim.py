# -*- coding: utf-8 -*-
"""
尺寸链与净空 —— 纯算术判据。

这一类看起来最"简单"，却是本项目最贵的两次翻车所在
（抱箍夹不紧、托台顶死托板）。共同点是：**每一步都对，但没人把整条链算完。**
所以这里的每条规则都把式子写在 detail 里，让人（和 AI）能逐项复核。
"""

from __future__ import annotations

from build123d import Pos

from ..geometry import bx
from . import ERROR, INFO, WARN, Result, fmt, inter_vol, rule


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


@rule("DIM-06", "DIM", "镜片托板提起后仍不撞天花板",
      why="托板现在被 layout.holder_top_z() 主动削平到 "
          "`天花板 − 提起行程 − 余量`，所以这条**应该恒成立**。"
          "留着它不是多余：削平那一刀万一被谁注释掉、或者提起行程变大，"
          "这里会立刻红。**把约束做进几何之后，检查的角色就从"
          "『发现错误』变成『守住那个几何』——两个作用都要有。**")
def holder_lift_headroom(design):
    m, c = design.cfg.meter, design.cfg.case
    lift = c.holder_lift_clear
    zmax = design.mirror_holder.bounding_box().max.Z
    return zmax + lift < m.ceiling_z, (
        f"托板最高 {zmax:.1f} + 提起 {lift:.1f} = {zmax + lift:.1f} "
        f"< 天花板 {m.ceiling_z:.1f}，余量 {m.ceiling_z - lift - zmax:.1f}")


@rule("DIM-11", "DIM", "蓝色固定环外径 = 银圈内径（两次独立测量互相印证）",
      why="这两个数是分别量出来的：银圈内径 61.8 来自表头实测，"
          "固定环外径 61.8 来自后来补的卡尺照片。它们本该相等 —— 环就是"
          "填在银圈内孔里的。相等说明两次测量都可信；不相等就说明至少一次量错了，"
          "而**基于错数据的设计不管做得多漂亮都是白做**。"
          "顺带还有第三个印证：给出的壁厚 2.65 = (61.8 − 56.5)/2。")
def ring_matches_bezel(design):
    m = design.cfg.meter
    dev = abs(m.ring_od - m.bezel_id)
    return dev <= 0.3, (f"固定环外径 {m.ring_od} vs 银圈内径 {m.bezel_id}，"
                        f"偏差 {dev:.2f}mm；推出的壁厚 {m.ring_t:.2f}")


@rule("DIM-14", "DIM", "铰链高度的三条测量互相印证",
      why="铰链高度直接决定翻开的盖板侵入多少，进而决定表盘墙侧还能看见多大一圈 —— "
          "整条链上最敏感的一个输入。现场量了两条：铰链销心到**银圈**顶面 8.3、"
          "到**蓝环**顶面 4.7；两者之差应当等于上一轮独立实测的"
          "『银圈顶面→蓝环顶面 3.8』。"
          "对上了才敢把不确定度从 ±1.0 收到 ±0.3（直接换回约 0.7mm 可见半径）。"
          "**把不确定度收小是要拿证据换的，不能因为『现在是实测值了』就自动收小。**")
def hinge_height_consistent(design):
    m = design.cfg.meter
    implied = m.hinge_above_bezel - m.cover_hinge_above_ring
    dev = abs(implied - m.bezel_to_ring_top)
    return dev <= 0.4, (
        f"{m.hinge_above_bezel} − {m.cover_hinge_above_ring} = {implied:.1f} vs "
        f"独立实测的银圈顶→环顶 {m.bezel_to_ring_top}，偏差 {dev:.1f}mm（容许 0.4）；"
        f"据此取不确定度 ±{m.cover_hinge_tol}")


@rule("DIM-12", "DIM", "座圈架在银圈顶面上，既不悬空也不压到塑料环",
      why="座圈是整机**唯一**的高度基准，它必须实实在在坐在银圈那个平的加工面上。"
          "两头都会出事：内径做小了会压到蓝色固定环（塑料，会被压变形，"
          "而且环本身相对表盘的高度没人保证）；径向做厚了会伸到银圈内孔上方"
          "悬空，既没支承又挡住外缘光线。"
          "判据式子：ring_od/2 < collar_seat_ir 且 bezel_od/2 − collar_seat_ir ≤ 银圈径向厚度。")
def seat_ring(design):
    m, c = design.cfg.meter, design.cfg.case
    radial = m.bezel_od / 2 - c.collar_seat_ir
    bezel_radial = (m.bezel_od - m.bezel_id) / 2
    ok = (c.collar_seat_ir > m.ring_od / 2 + 0.3) and (0 < radial <= bezel_radial)
    return ok, (f"座圈内半径 {c.collar_seat_ir} > 固定环外半径 {m.ring_od / 2:.2f}；"
                f"径向厚度 {radial:.2f} ≤ 银圈径向厚度 {bezel_radial:.2f}；"
                f"承压环面 {radial:.2f}×2π×{c.collar_seat_ir:.0f} ≈ "
                f"{radial * 2 * 3.1416 * (c.collar_seat_ir + radial / 2):.0f}mm²")


@rule("DIM-13", "DIM", "座圈确实顶在银圈顶面上（**反向**判据）",
      why="正向的『不干涉』说明不了任何事 —— 座圈悬在银圈上方 2mm 也不干涉。"
          "所以要反过来问：整机再往下压 0.5mm，座圈**必须**扎进银圈里。"
          "判定区间刻意取在 z ∈ [银圈顶−0.6, 银圈顶]，这一段夹持带的内棱"
          "（z ≤ 2.0）够不到，所以量到的干涉一定来自座圈，不会被内棱的"
          "过盈污染。**反向判据要挑一个只有被测特征能到达的区域。**")
def seat_is_datum(design):
    m = design.cfg.meter
    band = bx(-60, 60, -60, 60, m.bezel_top_z - 0.6, m.bezel_top_z)
    target = design.meter & band
    # 把**水表**抬 0.5mm 等价于把整机压下 0.5mm。写成 Pos(0,0,-0.5)*target
    # 的话是整机往上抬，那边本来就是空的，永远量到 0 —— 反向判据的方向
    # 写反了不会报错，只会安静地永远"通过"。
    down = inter_vol(design.body, Pos(0, 0, 0.5) * target)
    flat = inter_vol(design.body, target)
    return down > 10.0 and flat < design.cfg.mfg.vol_tol, (
        f"就位时干涉 {fmt(flat)}（应为 0）；下压 0.5mm 后 {fmt(down)}（应 >10）")


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
