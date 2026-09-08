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

from .. import refs
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
