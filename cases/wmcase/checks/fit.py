# -*- coding: utf-8 -*-
"""
配合与干涉 —— "装得进去吗"。

这一类只回答**正向**问题（不打架）。"装上以后会不会掉"是 :mod:`cons` 的事，
两类必须分开写，否则很容易只测了一半就以为验完了。
"""

from __future__ import annotations

from build123d import Vector

from .. import refs
from ..geometry import bx
from . import ERROR, INFO, WARN, Result, fmt, inter_vol, rule


def _tol(design) -> float:
    return design.cfg.mfg.vol_tol


# =============================================================================
#  打印件之间
# =============================================================================

@rule("FIT-01", "FIT", "主体 ∩ 镜片托板 = 0",
      why="托台曾经扎进托板（v2.3 实物：一端顶死 4mm、一端悬空 4mm）。")
def body_holder(design):
    v = inter_vol(design.body, design.mirror_holder)
    return v < _tol(design), fmt(v)


@rule("FIT-02", "FIT", "主体 ∩ 滑盖 = 0（滑盖能就位）")
def body_cover(design):
    v = inter_vol(design.body, design.slide_cover)
    return v < _tol(design), fmt(v)


@rule("FIT-03", "FIT", "镜片托板 ∩ 镜片 = 0（镜片装得进 T 型槽）")
def holder_glass(design):
    v = inter_vol(design.mirror_holder, design.mirror_glass)
    return v < _tol(design), fmt(v)


@rule("FIT-04", "FIT", "镜片能从 T 型槽端口滑入 / 滑出",
      why="镜片是在台面上装进托板的。如果提手或加强筋横在槽口，"
          "装配时才会发现——那时零件已经打出来了。")
def glass_slide(design):
    worst = 0.0
    for s in (-20, -40, -60, -80):
        worst = max(worst, inter_vol(design.mirror_holder,
                                     refs.mirror_glass(design.cfg, slide=s)))
    return worst < _tol(design), f"滑出 20/40/60/80mm 最大干涉 {fmt(worst)}"


# =============================================================================
#  开发板
# =============================================================================

@rule("FIT-05", "FIT", "开发板 STEP 与 BoardSpec 对得上",
      why="BoardSpec 里的数字是人从 STEP 里量出来抄进参数表的。"
          "换 STEP 却忘了改参数表，模型会静默地按老尺寸建腔——"
          "这条检查专门拦这个。")
def board_spec_matches(design):
    b = design.cfg.board
    if design.board_ref.trust != refs.AUTHORITATIVE:
        return Result("FIT-05", "FIT", "开发板 STEP 与 BoardSpec 对得上", False,
                      f"没有加载到 STEP（{design.board_ref.source}）",
                      board_spec_matches._rule["why"], WARN),
    from ..layout import board_location
    raw = refs.load_step(design.cfg, b.step_file)
    bb = raw.bounding_box()
    got = ((bb.min.X, bb.min.Y, bb.min.Z), (bb.max.X, bb.max.Y, bb.max.Z))
    want = (b.bbox_min, b.bbox_max)
    dev = max(abs(g - w) for gp, wp in zip(got, want) for g, w in zip(gp, wp))
    return dev <= b.bbox_tol, (f"包围盒最大偏差 {dev:.2f}mm（容差 {b.bbox_tol}）"
                               f" 实测 {got[0]}~{got[1]}")


@rule("FIT-06", "FIT", "开发板 ∩ 主体 = 0（装得进吊舱）")
def board_body(design):
    v = inter_vol(design.body, design.board)
    return v < _tol(design), fmt(v)


@rule("FIT-07", "FIT", "开发板完全落在型腔包络内",
      why="板卡越界不一定表现为干涉——它可能刚好从滑盖开口那侧探出去，"
          "布尔算出来是 0，实物却盖不上。所以要单独查包围盒。")
def board_envelope(design):
    c, p = design.cfg.case, design.pod
    bb = design.board.bounding_box()
    ok = (bb.min.X > -c.cav_half_x and bb.max.X < c.cav_half_x
          and bb.min.Y >= p.wall_inner_y - 0.05 and bb.max.Y < c.cover_y0
          and bb.min.Z > c.cav_z0 and bb.max.Z < c.cav_z1)
    return ok, (f"X[{bb.min.X:.1f},{bb.max.X:.1f}] Y[{bb.min.Y:.1f},{bb.max.Y:.1f}] "
                f"Z[{bb.min.Z:.1f},{bb.max.Z:.1f}] vs 腔 X±{c.cav_half_x} "
                f"Y[{p.wall_inner_y:.1f},{c.cover_y0}] Z[{c.cav_z0},{c.cav_z1}]")


@rule("FIT-08", "FIT", "摄像头模组落在方腔里（光轴由方腔定位）",
      why="光轴的 X/Z 重复精度完全取决于模组在方腔里的间隙。"
          "如果模组根本没进方腔，光轴就由 PCB 的公差决定，每台都要重新标 ROI。")
def camera_in_pocket(design):
    p, cfg, b = design.pod, design.cfg, design.cfg.board
    # 取模组**方形本体**那一段来量，不能取整个前腔深度：
    # 摄像头排线也在前侧，它比模组宽得多（X±6.25 vs ±4.25），
    # 把排线一起量进来会得出"模组装不进方腔"的错误结论。
    holder_front_y = cfg.optics.lens_face_y + (b.lens_face_ys - b.holder_front_ys)
    band = bx(-40, 40, holder_front_y + 0.3, holder_front_y + 2.5, -40, 90)
    front = design.board & band
    if front.volume < 1.0:
        return False, "模组方形本体那一段没有实体——BoardSpec 的 holder_front_ys 可能不对"
    bb = front.bounding_box()
    ok = (abs(bb.min.X) < p.cam_half_x and abs(bb.max.X) < p.cam_half_x
          and bb.min.Z > p.cam_z0 and bb.max.Z < p.cam_z1)
    slack = p.cam_half_x - max(abs(bb.min.X), abs(bb.max.X))
    return ok, (f"模组包络 X[{bb.min.X:.2f},{bb.max.X:.2f}] Z[{bb.min.Z:.2f},{bb.max.Z:.2f}]"
                f" vs 方腔 X±{p.cam_half_x:.2f} Z[{p.cam_z0:.2f},{p.cam_z1:.2f}]；"
                f"单边间隙 {slack:.2f}mm（= 光轴的 X/Z 重复精度）")


@rule("FIT-09", "FIT", "EVA 泡棉能压住板卡（+Y 约束成立）",
      why="板卡的 +Y 靠泡棉顶住。泡棉太薄就压不到板，板会在腔里晃；"
          "太厚则装不上滑盖。这是一条纯尺寸链，必须算出来而不是拍脑袋。",
      severity=ERROR)
def foam_reach(design):
    c, p = design.cfg.case, design.pod
    gap = c.cover_y0 - p.board_back_y
    press = c.cover_foam_t - gap
    ok = 0.5 <= press <= 6.0
    return ok, (f"盖板前表面 {c.cover_y0} − 板卡最后端 {p.board_back_y:.2f} = 间隙 "
                f"{gap:.2f}mm；泡棉 {c.cover_foam_t}mm → 压缩量 {press:.2f}mm"
                f"（要求 0.5~6.0）")


@rule("FIT-10", "FIT", "泡棉不与主体 / 天线打架")
def foam_clear(design):
    v = inter_vol(design.body, design.foam)
    return v < _tol(design), fmt(v)


# =============================================================================
#  LED
# =============================================================================

@rule("FIT-11", "FIT", "灯珠本体 ∩ 主体 = 0（能压进灯座）",
      why="用灯珠本体而不是完整 STEP：25mm 引脚是可以弯的软线，"
          "它穿过立板不算缺陷；法兰坐不进座孔才算。")
def led_seats(design):
    v = inter_vol(design.body, refs.led_bodies(design.cfg))
    return v < _tol(design), fmt(v)


# =============================================================================
#  抱箍与水表
# =============================================================================

@rule("FIT-12", "FIT", "抱箍内棱对银圈**有**过盈（真的夹得住）",
      why="v2.3 的致命错误：内孔比银圈大 2.4mm 而剖分缝只有 2.2mm，"
          "缝完全闭合内孔也只缩小 0.70mm，永远碰不到银圈（DESIGN_NOTES §7.3）。"
          "所以这条是**反向**判据：必须干涉，不干涉才是错。")
def collar_grips(design):
    m = design.cfg.meter
    ring = refs.meter_mock(design.cfg).shape
    band = bx(-60, 60, -60, 60, design.cfg.case.collar_z0 - 1, design.cfg.case.collar_z1 + 1)
    v = inter_vol(design.body, ring & band)
    return v > 10.0, f"夹持带内干涉体积 {fmt(v)}（内棱咬进银圈漆面）"


@rule("FIT-13", "FIT", "抱箍不碰水表表体",
      why="夹持带只能咬银圈。碰到表体说明带子太长或位置太低，"
          "装的时候会被顶住，看起来像『装到位了』其实内棱根本没咬上。")
def collar_clears_body(design):
    m = design.cfg.meter
    body_block = bx(-m.body_len / 2, m.body_len / 2, -m.body_width / 2, m.body_width / 2,
                    m.bezel_bottom_z - (m.body_height - m.bezel_h), m.bezel_bottom_z)
    v = inter_vol(design.body, body_block)
    return v < _tol(design), fmt(v)


@rule("FIT-14", "FIT", "蓝盖翻开停放的空间不被占用", severity=WARN,
      why="光学读表要求蓝盖**常开**并朝墙侧停放。它停在哪、有多高，"
          "目前全是照片目测（params.Meter.cover_park_y / cover_open_top）。"
          "而镜片托板为了接住表盘外缘的光，必须一直伸到 y≈−31，两者非常接近。"
          "结论只和那两个估算值一样可信，所以是 WARN 不是 ERROR —— "
          "写成 ERROR 会给人虚假的安全感。**这是当前风险最高的一条未验证假设。**")
def blue_cover_space(design):
    m = design.cfg.meter
    y0, y1 = m.cover_park_y
    park = bx(-m.bezel_od / 2 - 2, m.bezel_od / 2 + 2, y0, y1,
              m.bezel_top_z, m.bezel_top_z + m.cover_open_top)
    v_body = inter_vol(design.body, park)
    v_holder = inter_vol(design.mirror_holder, park)
    return (v_body + v_holder) < 20.0, (
        f"主体重叠 {fmt(v_body)}，托板重叠 {fmt(v_holder)}；"
        f"停放带 Y[{y0},{y1}] Z[{m.bezel_top_z},{m.bezel_top_z + m.cover_open_top}] "
        f"（**估算值**，需实测蓝盖停放位置）")
