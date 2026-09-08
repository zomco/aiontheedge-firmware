# -*- coding: utf-8 -*-
"""
光学自检 —— 回答"相机到底看不看得见字轮"。

分两层，**两层都要跑**：

* 体积法（受保护光锥 ∩ 结构件）—— 快，粗，能拦住"有东西伸进光路"这类大错；
* 射线法（逐点追踪 表盘→镜→镜头）—— 慢一点，但能定位到具体是哪一点、
  被谁、在哪个位置挡住的，还能验证镜片**有效口径**（唇口会吃掉两侧各 2.2mm）
  和镜头孔会不会渐晕。

这一节就是需求里的"组装后模拟镜面反射，验证 ESP32-S3-CAM 能读到表盘"。
"""

from __future__ import annotations

import collections
import math

from .. import optics as ox
from . import ERROR, INFO, WARN, Result, fmt, inter_vol, rule


# =============================================================================
#  射线追踪（核心）
# =============================================================================

@rule("OPT-01", "OPT", "表盘每一处都能经反射镜到达镜头（逐点光线追踪）",
      why="『会不会挡光』靠脑补是不可靠的——本项目所有结构性错误都是人看"
          "渲染图发现的（DESIGN_NOTES §7.9）。把它变成射线求交，机器就能查。")
def ray_trace(design):
    cfg = design.cfg
    blockers = {"主体": design.body, "镜片托板": design.mirror_holder}
    pts = ox.sample_dial_points(cfg, n_rim=24, n_ring=2)
    results = [(tag, ox.trace_dial_point(cfg, blockers, design.mirror_glass, x, y))
               for x, y, tag in pts]
    bad = [(tag, r) for tag, r in results if not r.ok]
    detail = f"{len(results) - len(bad)}/{len(results)} 条光线畅通"
    if bad:
        cnt = collections.Counter(f"{tag}:{r.label}" for tag, r in bad)
        detail += " —— " + "；".join(f"{k}×{v}" for k, v in list(cnt.items())[:6])
    yield Result("OPT-01", "OPT", "表盘每一处都能经反射镜到达镜头", not bad, detail,
                 ray_trace._rule["why"], ERROR)

    # 顺带把"镜片实际用到多大一块"报出来——这是选购镜片尺寸的直接依据
    hits = [r.mirror_point for _, r in results if r.mirror_point is not None]
    if hits:
        ys = [h.Y for h in hits]
        xs = [h.X for h in hits]
        span = (max(ys) - min(ys)) * math.sqrt(2)
        yield Result("OPT-01-USE", "OPT", "镜片实际用到的范围", True,
                     f"沿 45° 斜面 {span:.1f}mm（采购 {cfg.optics.mirror_l:.0f}），"
                     f"沿 X {max(xs) - min(xs):.1f}mm（采购 {cfg.optics.mirror_w:.0f}）；"
                     f"落点 Y∈[{min(ys):.1f},{max(ys):.1f}]",
                     "", INFO)


@rule("OPT-02", "OPT", "镜片有效口径（扣掉 T 型槽唇口）够用",
      why="镜片宽 50，但两侧各 2.2mm 被唇口盖住，实际能反射的只有 45.6。"
          "光学需要的宽度是 2×beam_r_at_mirror。差一点就会在画面两侧出现暗边。")
def aperture(design):
    o, c = design.cfg.optics, design.cfg.case
    effective = o.mirror_w - 2 * c.holder_lip
    need = o.need_mirror_width
    return effective >= need + 4.0, (
        f"有效口径 {effective:.1f} = 镜宽 {o.mirror_w:.0f} − 2×唇口 {c.holder_lip}；"
        f"光学需 {need:.1f}（要求余量 ≥4mm）")


@rule("OPT-03", "OPT", "采购镜片长度够用（含 5mm 余量）")
def mirror_len(design):
    o = design.cfg.optics
    return o.mirror_l >= o.need_mirror_len + 5.0, \
        f"需 {o.need_mirror_len:.1f}，采购 {o.mirror_l:.0f}"


# =============================================================================
#  体积法粗筛
# =============================================================================

@rule("OPT-04", "OPT", "受保护光锥 ∩ 主体 = 0")
def cone_body(design):
    v = inter_vol(ox.protected_cone(design.cfg), design.body)
    return v < design.cfg.mfg.vol_tol, fmt(v)


@rule("OPT-05", "OPT", "受保护光锥 ∩ 托板的耳/脚/提手 = 0",
      why="托板本体挡住光锥是正常的（它就是反射面所在的位置），"
          "耳、脚、提手挡住就是错误。所以要把两者分开算。")
def cone_holder_extras(design):
    v = inter_vol(ox.protected_cone(design.cfg), design.holder_ears_and_feet)
    return v < design.cfg.mfg.vol_tol, fmt(v)


# =============================================================================
#  成像质量（纯算术，但式子必须写出来接受检查）
# =============================================================================

@rule("OPT-06", "OPT", "单个字轮数字的成像宽度 ≥ 20px",
      why="AI-on-the-edge 的 dig-class100 模型在 20px 以下识别率断崖下跌。"
          "判据式子：digit_px = digit_w_mm × sensor_px_h / (2·path·tan(HFOV/2))")
def digit_px(design):
    o = design.cfg.optics
    return o.digit_px >= o.min_digit_px, \
        f"{o.digit_px:.1f} px（下限 {o.min_digit_px:.0f}）"


@rule("OPT-07", "OPT", "整个表盘落在画幅内（按较小的垂直视场算）",
      why="判据取 min(HFOV, VFOV)/2 而不是 HFOV/2 —— "
          "传感器长轴到底对着全局 X 还是 Z，取决于模组内部的芯片朝向，"
          "我们没有可信资料。取小的那个，结论才与朝向无关。")
def roi_fits(design):
    half = ox.roi_half_angle_deg(design.cfg)
    limit = min(design.cfg.optics.hfov_deg, ox.vfov_deg(design.cfg)) / 2
    return half <= limit - 3.0, \
        f"ROI 半张角 {half:.2f}° ≤ {limit:.2f}° − 3°（VFOV={ox.vfov_deg(design.cfg):.1f}°）"


@rule("OPT-08", "OPT", "景深覆盖表盘井深",
      why="表盘是一个 glass_depth 深的井，字轮在井底、指针在不同高度。"
          "判据式子：DoF_half ≈ N·c·s²/f²，见 params.Optics.dof_half_mm。")
def depth_of_field(design):
    o = design.cfg.optics
    need = design.cfg.meter.glass_depth
    return o.dof_half_mm >= need, \
        f"景深半宽 ±{o.dof_half_mm:.1f}mm ≥ 井深 {need:.1f}mm（f={o.focal_mm:.2f}, N={o.f_number}）"


@rule("OPT-09", "OPT", "镜头孔不产生渐晕",
      why="Ø13 的孔离镜头前端面只有 3mm，但光锥在那里已经收得很细。"
          "判据式子：孔处需要的半径 = 镜筒半径 + 壁厚×tan(HFOV/2)。")
def no_vignetting(design):
    o, c, b = design.cfg.optics, design.cfg.case, design.cfg.board
    need_r = b.barrel_d / 2 + c.pod_front_wall * math.tan(math.radians(o.hfov_deg / 2))
    return c.lens_bore_d / 2 >= need_r + 1.0, \
        f"孔半径 {c.lens_bore_d / 2:.1f} ≥ 需 {need_r:.2f} + 1.0"


@rule("OPT-10", "OPT", "画面是镜像的 —— 固件侧必须知道", severity=INFO,
      why="奇数次反射会让画面左右翻转。ROI 是在翻转后的画面上框的，"
          "如果按直觉去框会左右对不上。这不是缺陷，是必须写进文档的事实。")
def mirrored_image(design):
    return True, "光路含 1 次反射 → 传感器画面左右镜像；ROI 标定与固件配置见 DESIGN.md §4.6"
