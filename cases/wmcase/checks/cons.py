# -*- coding: utf-8 -*-
"""
约束有效性 —— "装上以后会不会掉"。

**全部是反向测试**：往被约束的方向推一点，**必须**产生干涉。
只测"不干涉"是不够的，那只说明装得进去。

v2.3 的两个实物错误分别是这么来的：

* 托台顶死托板 —— 正向检查全过（不干涉），反向检查才会暴露
* 滑盖能向后掉出 —— "有舌片"被误当成"有槽"，Y 向根本没约束
"""

from __future__ import annotations

from build123d import Pos, Rot

from .. import layout as lay, refs
from ..geometry import bx
from . import ERROR, WARN, Result, fmt, inter_vol, rule


def _tol(design) -> float:
    return design.cfg.mfg.vol_tol


# =============================================================================
#  镜片托板
# =============================================================================

@rule("CONS-01", "CONS", "托板确实坐在托台上（不是悬空）",
      why="托台顶面水平、托板底面 45°，只要托台高了一点点就会变成"
          "『一端顶死一端悬空』。正向检查（不干涉）对此完全无感。")
def holder_seated(design):
    v = inter_vol(design.body, Pos(0, 0, -0.5) * design.mirror_holder)
    return v > _tol(design), f"下沉 0.5mm 产生干涉 {fmt(v)}"


@rule("CONS-02", "CONS", "托板被定位销约束住水平自由度")
def holder_pinned(design):
    out = []
    for dx, dy, nm in ((1.0, 0, "+X"), (-1.0, 0, "−X"), (0, 1.0, "+Y"), (0, -1.0, "−Y")):
        v = inter_vol(design.body, Pos(dx, dy, 0) * design.mirror_holder)
        out.append(Result("CONS-02", "CONS", f"托板 {nm} 向平移 1mm 应当干涉",
                          v > _tol(design), fmt(v), holder_pinned._rule["why"], ERROR))
    return out


@rule("CONS-03", "CONS", "镜片被 T 型槽唇口兜住（镜面朝下不会掉）",
      why="反射面必须朝下，直通方槽只靠重力压着，整机一晃镜片就掉。")
def glass_retained(design):
    v = inter_vol(design.mirror_holder, refs.mirror_glass(design.cfg, push_out=1.2))
    return v > _tol(design), f"镜片外推 1.2mm 产生干涉 {fmt(v)}"


# =============================================================================
#  滑盖 —— 逐自由度核算
# =============================================================================

@rule("CONS-04", "CONS", "滑盖的 Y 向被前沿和后压边双向锁住",
      why="v2.3 的挖除区贯穿了 X 全宽，把本该留作槽背衬的侧壁也挖掉了："
          "舌片有了，槽没有，盖板可以直接向后掉出来（DESIGN_NOTES §7.6）。")
def cover_y_locked(design):
    out = []
    for dy, nm in ((-0.6, "−Y（被前沿挡住）"), (0.6, "+Y（被后压边挡住）")):
        v = inter_vol(design.body, Pos(0, dy, 0) * design.slide_cover)
        out.append(Result("CONS-04", "CONS", f"滑盖 {nm}", v > _tol(design), fmt(v),
                          cover_y_locked._rule["why"], ERROR))
    return out


@rule("CONS-05", "CONS", "滑盖的 X 向被两侧滑槽锁住")
def cover_x_locked(design):
    out = []
    for dx, nm in ((0.8, "+X"), (-0.8, "−X")):
        v = inter_vol(design.body, Pos(dx, 0, 0) * design.slide_cover)
        out.append(Result("CONS-05", "CONS", f"滑盖 {nm} 向平移 0.8mm 应当干涉",
                          v > _tol(design), fmt(v), cover_x_locked._rule["why"], ERROR))
    return out


@rule("CONS-06", "CONS", "滑盖到底有限位（不会继续往下掉）")
def cover_bottom_stop(design):
    v = inter_vol(design.body, Pos(0, 0, -3.0) * design.slide_cover)
    return v > _tol(design), f"下沉 3mm 产生干涉 {fmt(v)}"


# =============================================================================
#  开发板 —— 六个自由度逐条核算
# =============================================================================

@rule("CONS-07", "CONS", "板卡的 −Y 被前腔台阶止住",
      why="板卡的 Y 定位基准只有一个：PCB 前表面顶在台阶上。"
          "如果台阶被让位槽挖穿了，板会一路顶到前壁，摄像头模组被压坏。")
def board_front_stop(design):
    v = inter_vol(design.body, Pos(0, -1.0, 0) * design.board)
    return v > _tol(design), f"板卡前推 1mm 产生干涉 {fmt(v)}"


@rule("CONS-08", "CONS", "板卡的 ±X 被侧向导轨约束")
def board_x_guided(design):
    out = []
    for dx, nm in ((1.2, "+X"), (-1.2, "−X")):
        v = inter_vol(design.body, Pos(dx, 0, 0) * design.board)
        out.append(Result("CONS-08", "CONS", f"板卡 {nm} 向平移 1.2mm 应当干涉",
                          v > _tol(design), fmt(v), board_x_guided._rule["why"], ERROR))
    return out


@rule("CONS-14", "CONS", "板卡的 +Y 被下缘压唇挡住（不会掉出来）",
      why="这是人在装配体上直接看出来的问题：板卡装上去只有一个前止挡和一个"
          "底部承台，整机稍微一斜就掉出来。EVA 泡棉要等滑盖装上才起作用，"
          "在那之前板卡是完全自由的。"
          "现在下缘加了后压唇 —— 板卡抬高 board_lift 水平推入、落下就位之后，"
          "压唇扣住 PCB 下缘后角，**不依赖泡棉、不依赖滑盖**。")
def board_back_lip(design):
    v = inter_vol(design.body, Pos(0, 1.5, 0) * design.board)
    return v > _tol(design), f"板卡后推 1.5mm 产生干涉 {fmt(v)}"


@rule("CONS-15", "CONS", "板卡抬高后才推得进去（压唇确实挡住了平推）",
      why="压唇如果太矮或太靠里，平推也能进 —— 那它同样拦不住板卡掉出来。"
          "所以要正反两条一起验：抬高后路径**只剩卡钩的弹性过盈**、"
          "**不抬高则必然被挡**。"
          "★ 允许量取 layout.board_snap_allow()，由卡钩几何算出来而不是拍脑袋 —— "
          "允许量一旦定大了，真正的碰撞就会藏在它下面，检查等于没做。")
def board_lift_required(design):
    cfg, p = design.cfg, design.pod
    c = cfg.case
    lift = c.board_lift
    allow = lay.board_snap_allow(cfg)
    #  "压唇挡不挡得住平推"要**只看压唇那条 Z 带**（板下缘往上 board_lift）。
    #  拿整机去量的话，上端卡钩的弹性过盈会混进来，两个数就分不开了 ——
    #  和 DIM-13 一样：**反向判据要挑一个只有被测特征能到达的区域。**
    lip_band = bx(-40, 40, p.pcb_face_y - 2, c.pod_back_y,
                  p.pcb_z0 - 1.0, p.pcb_z0 + c.board_lift)
    lip = design.body & lip_band
    flat = max(inter_vol(lip, Pos(0, dy, 0) * design.board) for dy in (6, 3, 2, 1))
    lifted_lip = max(inter_vol(lip, Pos(0, dy, lift) * design.board)
                     for dy in (26, 12, 6, 2, 0))
    #  整条路径（含卡钩）只允许卡钩的名义弹性过盈
    lifted = max(inter_vol(design.body, Pos(0, dy, lift) * design.board)
                 for dy in (26, 12, 6, 2, 0))
    ok = lifted < allow and lifted_lip < _tol(design) and flat > 4 * _tol(design)
    return ok, (f"压唇带内：平推最大干涉 {fmt(flat)}（必须 > {4 * _tol(design):.0f}），"
                f"抬高后 {fmt(lifted_lip)}（必须 ≈0）；"
                f"整条路径抬高后 {fmt(lifted)} < 卡钩弹性让位允许 {allow:.1f}mm³")


# =============================================================================
#  开发板 —— 本轮新增：pitch 方向的约束
# =============================================================================

@rule("CONS-16", "CONS", "板卡不会从 **pitch** 方向倾侧掉出来",
      why="★ 这条是实物反馈逼出来的：上一版板卡装进去以后一摇就从 pitch 方向倒出来，"
          "而当时所有 CONS 检查全绿。"
          "原因是**判据只做了平移，没做转动**：+Y 平移会被下缘压唇挡住（CONS-14 通过），"
          "但板卡完全可以绕下缘压唇**转**出去 —— 上端根本没有任何约束。"
          "**平移试探测不出转动自由度。** 现在直接把失效动作本身做成判据："
          "绕下缘前棱把板卡向后仰 3°，必须被上端卡钩挡住。")
def board_pitch_locked(design):
    p = design.pod
    py, pz = p.pcb_face_y, p.pcb_z0      # 转轴：PCB 下缘前棱
    out = []
    #  判据不是"某个固定角度下的干涉体积"，而是**板卡最多能转到几度**。
    #  用固定角度会踩两个坑，两个都实际发生过：
    #    · 3° 时干涉只有 4.4mm³，和布尔容差 2.0 差不到一个量级，判据很脆；
    #    · 角度取大反而更小（5° 只有 1.8mm³）—— 因为板卡的上缘已经整个转到
    #      卡钩**后面**去了，卡钩再也够不着它。**"推得越狠干涉越大"这个直觉
    #      对有限尺寸的挡块不成立。**
    #  改成扫角度找"第一个被挡住的角度"，读出来的数还有物理意义：
    #  它就是板卡在腔里能晃动的幅度。
    for sign, nm, limit in ((-1.0, "顶部后仰（+Y，卡钩挡）", 2.0),
                            (+1.0, "顶部前俯（−Y，前止挡挡）", 2.0)):
        stop = None
        for ang in (0.5, 1.0, 1.5, 2.0, 3.0, 4.0):
            tilted = (Pos(0, py, pz) * Rot(sign * ang, 0, 0)
                      * Pos(0, -py, -pz) * design.board)
            if inter_vol(design.body, tilted) > _tol(design):
                stop = ang
                break
        top_mm = 40.0 * (stop / 57.3) if stop else float("nan")
        out.append(Result("CONS-16", "CONS", f"板卡 {nm} 被限制在 ≤{limit:.1f}°",
                          stop is not None and stop <= limit,
                          (f"扫到 {stop:.1f}° 时被挡住（板上缘摆幅约 {top_mm:.1f}mm）"
                           if stop else "扫到 4° 仍无干涉 —— 这个方向**没有约束**"),
                          board_pitch_locked._rule["why"], ERROR))
    return out


@rule("CONS-17", "CONS", "板卡上抬行程被顶部压舌限死（压唇不会被抬脱）",
      why="上一版的失效链是：板卡能上抬 board_lift（所有让位腔都是按这个行程放大的）"
          "→ 抬到顶时下缘压唇（高 board_lift−0.3）刚好完全脱开 → 上端本来就没约束 "
          "→ 整块板转出去。**压唇的高度永远小于可上抬行程，这是几何必然**"
          "（见 params.Case 里的定理），所以必须另有东西限制上抬。"
          "顶部压舌把行程压到 board_tab_gap = 0.4mm，只有压唇高度的十分之一。")
def board_lift_locked(design):
    c = design.cfg.case
    gap = c.board_tab_gap
    probe = gap + 3.6
    v = inter_vol(design.body, Pos(0, 0, probe) * design.board)
    free = inter_vol(design.body, Pos(0, 0, gap - 0.2) * design.board)
    ok = v > 2 * _tol(design) and free < _tol(design)
    return ok, (f"上抬 {gap - 0.2:.1f}mm（间隙内）干涉 {fmt(free)}（应为 0）；"
                f"上抬 {probe:.1f}mm 干涉 {fmt(v)}（应被压舌挡住）；"
                f"压唇高 {c.board_lift - 0.3:.1f}mm ≫ 允许行程 {gap}mm")


@rule("CONS-18", "CONS", "弹性卡钩：让得开、弹得回、不过应变",
      why="**做了一个悬臂 ≠ 这个悬臂能动。** 三件事缺一不可，而且三件都是"
          "纯算术，没有理由不查：\n"
          "  ① 应变 ε = 3tδ/(2L²) 在材料许用范围内（否则装一次就白化断裂）；\n"
          "  ② 侧壁到悬臂外表面的空隙 ≥ 需要的变形量（本设计原本只有 1.5mm，"
          "正好等于过盈量 —— 悬臂会顶死在壁上，等于没有弹性）；\n"
          "  ③ 悬臂根部以上不能还被整面导轨背着（否则刚度是墙的刚度）。")
def snap_arm(design):
    from ..parts.body import board_arm_z0, board_rail_x

    cfg = design.cfg
    c, p = cfg.case, design.pod
    out = []

    strain = lay.board_snap_strain(cfg)
    out.append(Result("CONS-18", "CONS", "悬臂应变在 PETG 许用范围内",
                      strain <= 0.016,
                      f"ε = 3×{c.board_arm_t}×{c.board_hook_overlap}/"
                      f"(2×{c.board_arm_len}²) = {strain * 100:.2f}%（上限 1.6%）",
                      snap_arm._rule["why"], ERROR))

    _rib_in, rib_out = board_rail_x(cfg)
    space = (c.cav_half_x + c.board_arm_relief) - rib_out
    out.append(Result("CONS-18-SP", "CONS", "悬臂有足够的变形空间",
                      space >= c.board_hook_overlap + 0.3,
                      f"侧壁让位后到 X={c.cav_half_x + c.board_arm_relief:.1f}，"
                      f"悬臂外表面 X={rib_out:.1f} → 空隙 {space:.2f}mm "
                      f"≥ 过盈 {c.board_hook_overlap} + 0.3",
                      snap_arm._rule["why"], ERROR))

    #  ③ 悬臂段（根部以上）在 PCB 前表面那一侧必须是空的
    z0 = board_arm_z0(cfg)
    back_probe = bx(_rib_in - 0.2, rib_out + 0.2, p.pcb_face_y, p.pcb_back_y,
                    z0 + 2.0, p.pcb_z1)
    v = inter_vol(design.body, back_probe)
    out.append(Result("CONS-18-FREE", "CONS", "悬臂根部以上没有被导轨背住",
                      v < 5.0,
                      f"悬臂段前侧（Y {p.pcb_face_y:.1f}~{p.pcb_back_y:.1f}）"
                      f"残留实体 {fmt(v)}（应接近 0，否则悬臂被墙背着弹不动）",
                      snap_arm._rule["why"], ERROR))
    return out


@rule("CONS-09", "CONS", "板卡的 −Z 落在承台上")
def board_shelf(design):
    v = inter_vol(design.body, Pos(0, 0, -1.5) * design.board)
    return v > _tol(design), f"板卡下沉 1.5mm 产生干涉 {fmt(v)}"


# =============================================================================
#  纯算术判据（不需要布尔，但同样是"约束成不成立"）
# =============================================================================

@rule("CONS-10", "CONS", "托台顶面低于该段托板底面的最低点",
      why="判据式子：托板底面 z = y + mirror_z，在托台 Y 范围内的最低点是 "
          "y0 + mirror_z。托台顶必须比它低 pad_clear。"
          "v2.3 就是把托台顶取成了区间中值，结果一端顶死一端悬空（§7.5）。")
def pad_below_plate(design):
    c, o = design.cfg.case, design.cfg.optics
    out = []
    for nm, (y0, y1), z_top in (("后托台", c.pad_rear_y, c.pad_rear_z),
                                ("前托台", c.pad_front_y, c.pad_front_z)):
        lowest = y0 + o.mirror_z
        ok = z_top <= lowest - c.pad_clear
        out.append(Result("CONS-10", "CONS", f"{nm}顶面低于托板底面最低点", ok,
                          f"托台顶 {z_top} ≤ {lowest:.1f} − {c.pad_clear} = "
                          f"{lowest - c.pad_clear:.1f}",
                          pad_below_plate._rule["why"], ERROR))
    return out


@rule("CONS-11", "CONS", "托板支承片止于立板内侧面之前",
      why="托台是主体的一部分，可以伸进立板；支承片是活动件，不行。"
          "支承片扎进立板会让托板提不起来。")
def bracket_inside_mast(design):
    c = design.cfg.case
    return (c.holder_bracket_x[1] < c.mast_inner_x,
            f"支承片外缘 {c.holder_bracket_x[1]} < 立板内面 {c.mast_inner_x}")


@rule("CONS-12", "CONS", "两个托台等高，托板支承面是一条水平底边",
      why="这是**可拆性**的硬约束，不是审美。托台不等高时，"
          "托板的支承结构就必然一高一低；平推抽出时低的那一段会扫过高的托台，"
          "需要的抬升量远超天花板允许的行程 —— 整块托板拿不出来。"
          "这条错误只有 SEQ 的逐点仿真能发现，静态干涉一条都报不出来。")
def pads_level(design):
    c = design.cfg.case
    same = abs(c.pad_rear_z - c.pad_front_z) < 1e-9
    bottom = min(z for _y, z in c.holder_bracket_profile)
    flat = abs(bottom - c.pad_rear_z) < 1e-9
    return same and flat, (f"后托台 {c.pad_rear_z} / 前托台 {c.pad_front_z}；"
                           f"支承片底边 z={bottom}")


@rule("CONS-13", "CONS", "托台内伸斜面在免支撑角度内",
      why="托台是从立板 loft 出来的，向内伸出越多、落差越小，下表面越平。"
          "判据式子：atan((mast_inner_x − pad_inner_x) / pad_drop) ≤ 45°（自竖直算）。")
def pad_overhang(design):
    import math
    c = design.cfg.case
    ang = math.degrees(math.atan2(c.mast_inner_x - c.pad_inner_x, c.pad_drop))
    return ang <= design.cfg.mfg.max_overhang_deg, (
        f"atan(({c.mast_inner_x} − {c.pad_inner_x}) / {c.pad_drop}) = {ang:.1f}° "
        f"≤ {design.cfg.mfg.max_overhang_deg}°")
