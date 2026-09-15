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

from .. import layout as lay, optics as ox
from . import ERROR, INFO, WARN, Result, fmt, inter_vol, rule


# =============================================================================
#  射线追踪（核心）
# =============================================================================

def _camera_blockers(design) -> dict:
    """
    会挡住"表盘 → 镜 → 镜头"这条光路的**全部**实体。

    ⚠ 这里以前只有 ``body`` 和 ``mirror_holder`` —— 两个我们自己的零件。
      水表自己的东西（蓝色固定环、**翻开停放的蓝色盖板**）一个都没进来，
      于是"蓝盖挡住表盘外缘"这件事在自检里完全不存在，只有做出来才会知道。
      **遮挡判据的可信度上限，等于它的遮挡物清单的完整度。**
    """
    return {
        "主体": design.body,
        "镜片托板": design.mirror_holder,
        "水表(含蓝环)": design.meter,
        "翻开的蓝盖": design.blue_cover,
    }


@rule("OPT-01", "OPT", "OCR 关键区每一处都能经反射镜到达镜头（逐点光线追踪）",
      why="『会不会挡光』靠脑补是不可靠的——本项目所有结构性错误都是人看"
          "渲染图发现的（DESIGN_NOTES §7.9）。把它变成射线求交，机器就能查。"
          "★ 判据从『整个表盘』收窄成『OCR 关键区』，因为翻开的蓝盖**必然**"
          "挡掉墙侧一圈外缘 —— 那是外购活动件的几何后果，设计不掉。"
          "把做不到的事写成 ERROR 只会让人学会忽略红字；"
          "**做不到的部分要单独量化（OPT-01-COV / OPT-11），不能混进硬判据里。**")
def ray_trace(design):
    import math as _m

    cfg = design.cfg
    m = cfg.meter
    blockers = _camera_blockers(design)

    #  分档和 OPT-11 保持一致：主数据（r ≤ 20）是硬判据，小盘最外那一圈
    #  （r ≤ 25）是警告。两条判据说的是同一件事，档位必须对齐 ——
    #  **同一个现象被一条规则判红、另一条判黄，读报告的人只会两条都不信。**
    crit = ox.ocr_critical_points(cfg)
    primary = [(x, y, t) for x, y, t in crit
               if _m.hypot(x, y) <= m.ocr_primary_r + 0.01]
    outer = [(x, y, t) for x, y, t in crit
             if _m.hypot(x, y) > m.ocr_primary_r + 0.01]

    def run(points):
        bad = []
        for x, y, tag in points:
            r = ox.trace_dial_point(cfg, blockers, design.mirror_glass, x, y)
            if not r.ok:
                bad.append((tag, r))
        return bad

    bad_p = run(primary)
    detail = f"{len(primary) - len(bad_p)}/{len(primary)} 个主数据点畅通（r ≤ {m.ocr_primary_r:.0f}）"
    if bad_p:
        cnt = collections.Counter(f"{t}:{r.label}" for t, r in bad_p)
        detail += " —— " + "；".join(f"{k}×{v}" for k, v in list(cnt.items())[:6])
    yield Result("OPT-01", "OPT", "OCR 主数据全部可见", not bad_p, detail,
                 ray_trace._rule["why"], ERROR)

    bad_o = run(outer)
    d2 = f"{len(outer) - len(bad_o)}/{len(outer)} 个小盘外缘点畅通（r = {m.ocr_full_r:.0f}）"
    if bad_o:
        cnt = collections.Counter(f"{t}:{r.label}" for t, r in bad_o)
        d2 += " —— " + "；".join(f"{k}×{v}" for k, v in list(cnt.items())[:4])
        d2 += "。都落在墙侧，是翻开的蓝盖必然挡掉的那一圈，定量见 OPT-11-M"
    yield Result("OPT-01-OUT", "OPT", "指针小盘**最外一圈**也可见", not bad_o, d2,
                 ray_trace._rule["why"], WARN)

    # ---- 全表盘覆盖率：报数字，不判定 ----
    pts = ox.sample_dial_points(cfg, n_rim=24, n_ring=2)
    results = [(tag, ox.trace_dial_point(cfg, blockers, design.mirror_glass, x, y))
               for x, y, tag in pts]
    bad = [(tag, r) for tag, r in results if not r.ok]
    cov = f"{len(results) - len(bad)}/{len(results)} 条光线畅通"
    if bad:
        cnt = collections.Counter(f"{r.blocker or r.label}" for _t, r in bad)
        cov += " —— 被挡原因：" + "；".join(f"{k}×{v}" for k, v in cnt.items())
    yield Result("OPT-01-COV", "OPT", "全表盘覆盖率（含必然被蓝盖挡掉的外缘）",
                 True, cov,
                 "丢的是墙侧最外一圈（蓝圈、刻度），没有 OCR 数据；"
                 "边界值由 OPT-11 定量。", INFO)

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


@rule("OPT-03", "OPT", "镜片**前缘**够到房间侧的光锥边界",
      why="镜片的两端现在由两个完全不同的东西定：后缘被翻开的蓝盖顶死"
          "（layout.mirror_y_rear），前缘才是纯光学要求。"
          "所以判据不能再写成『镜长 ≥ 光学需求长度』—— 那条式子把两端混在一起，"
          "后缘一让，前缘看起来也『不够长』，实际上前缘一点问题都没有。"
          "**约束来自不同源头时，判据必须拆开写。**")
def mirror_front(design):
    o = design.cfg.optics
    front = lay.mirror_y_front(design.cfg)
    need = o.ellipse_y[1]
    margin = front - need
    return margin >= o.mirror_front_margin - 0.05, (
        f"镜片前缘 Y={front:.2f}，光锥边界 Y={need:.2f}，"
        f"余量 {margin:.2f}（要求 ≥{o.mirror_front_margin:.1f}）；"
        f"镜长 {o.mirror_l:.0f}，后缘 Y={lay.mirror_y_rear(design.cfg):.2f}")


@rule("OPT-03B", "OPT", "镜片**后缘**不比蓝盖更严（再加长也换不来可视范围）",
      why="后缘退到某个位置之后，限制可视范围的就变成蓝盖而不是镜片了。"
          "这条判据确认我们停在了正确的位置：镜片没有短到白白丢掉本来看得见的表盘，"
          "也没有长到（在托板上）撞进蓝盖。"
          "两者相差 <1mm 就说明这一维已经调到头了 —— 再花钱买长镜片没有任何收益。",
      severity=WARN)
def mirror_rear_balanced(design):
    _eff, by_cover, by_mirror = lay.dial_visible_limits(design.cfg)
    gap = by_mirror - by_cover      # >0 说明镜片更严（还有可挖的余地）
    return gap <= 1.0, (
        f"蓝盖给的可见边界 Y={by_cover:.2f}，镜片给的 Y={by_mirror:.2f}，"
        f"差 {gap:+.2f}mm（>1 说明镜片白白短了这么多）")


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
      why="表盘是一个井，字轮在井底、指针在不同高度，井口是**蓝色固定环的顶面**。"
          "判据里的井深因此该用 ring_h（玻璃面→环顶 7.8）而不是 glass_depth"
          "（银圈顶→玻璃面 4.0）—— 后者量的是另一段，只是碰巧也叫『深度』。"
          "把这两个数分开实测之后（7.8 / 4.0）才看得出原来用错了哪一个。"
          "判据式子：DoF_half ≈ N·c·s²/f²，见 params.Optics.dof_half_mm。")
def depth_of_field(design):
    o = design.cfg.optics
    need = design.cfg.meter.ring_h
    return o.dof_half_mm >= need, (
        f"景深半宽 ±{o.dof_half_mm:.1f}mm ≥ 井深 {need:.1f}mm（玻璃面→固定环顶；"
        f"f={o.focal_mm:.2f}, N={o.f_number}）")


@rule("OPT-09", "OPT", "镜头孔不产生渐晕",
      why="Ø13 的孔离镜头前端面只有 3mm，但光锥在那里已经收得很细。"
          "判据式子：孔处需要的半径 = 镜筒半径 + 壁厚×tan(HFOV/2)。")
def no_vignetting(design):
    o, c, b = design.cfg.optics, design.cfg.case, design.cfg.board
    need_r = b.barrel_d / 2 + c.pod_front_wall * math.tan(math.radians(o.hfov_deg / 2))
    return c.lens_bore_d / 2 >= need_r + 1.0, \
        f"孔半径 {c.lens_bore_d / 2:.1f} ≥ 需 {need_r:.2f} + 1.0"


@rule("OPT-11", "OPT", "被蓝盖挡掉的那圈表盘外缘里没有 OCR 主数据",
      why="★ 翻开的蓝盖是一堵立在 y≈−23 的墙，表盘墙侧外缘的光要上行到相机"
          "必须穿过它 —— **镜片做多大、相机放多远都改变不了这一点**。"
          "判据分两档，因为丢掉的那一圈有多宽，后果完全不同："
          "① **主数据**（字轮窗 + 四个小盘的**盘心**，r ≤ 20）丢了 = 读不出数 → ERROR；"
          "② **小盘最外那一圈**（r ≤ 25，刻度环的边）丢零点几毫米 → WARN。"
          "  用一条判据把两者混在一起，结论就没法指导决策了：报红你不知道是"
          "『整个盘看不见』还是『边缘少了 0.1mm』。"
          "  ⚠ 可见范围在停放角区间里**不是单调的**：90° 时 25.4mm，110° 时 24.9mm，"
          "180° 时 29.1mm（完全不挡）。**翻得越开不一定越好**，翻到一半反而最糟。")
def cover_shadow(design):
    cfg = design.cfg
    m = cfg.meter
    eff, by_cover, by_mirror = lay.dial_visible_limits(cfg, worst_case=True)
    nom = lay.dial_visible_limits(cfg, worst_case=False)[0]
    vis = abs(eff)
    # 逐个停放角报一遍，让人看得出最糟的角度在哪
    per_angle = []
    for ang in (90, 100, 110, 130, 150, 180):
        lim = abs(lay.dial_visible_limits(cfg, worst_case=True, only_angle=ang)[1])
        per_angle.append(f"{ang}°:{lim:.1f}")

    yield Result("OPT-11", "OPT", f"主数据（r ≤ {m.ocr_primary_r:.0f}）全部可见",
                 vis >= m.ocr_primary_r,
                 f"可见半径 {vis:.2f}mm（最坏；标称 {nom:+.2f} 的绝对值 {abs(nom):.2f}）"
                 f"[蓝盖 {abs(by_cover):.2f} / 镜片 {abs(by_mirror):.2f}]；"
                 f"主数据需 {m.ocr_primary_r:.0f}mm，余量 {vis - m.ocr_primary_r:+.2f}mm。"
                 f"按停放角：{' '.join(per_angle)}",
                 cover_shadow._rule["why"], ERROR)

    margin = vis - m.ocr_full_r
    yield Result("OPT-11-M", "OPT", f"指针小盘**整圈**（r ≤ {m.ocr_full_r:.0f}）也可见",
                 margin >= 0.0,
                 f"余量 {margin:+.2f}mm（小盘外缘 {m.ocr_full_r:.0f}mm vs 可见 {vis:.2f}mm）。"
                 f"★ 六台一组里只有**两台**盖板被墙挡住（停在 90°~？），"
                 f"另外四台能翻过 180° —— 那四台完全不挡（可见 29.1mm）。"
                 f"这两台如果发现最外圈刻度读不全，办法有三个："
                 f"把盖板再往墙侧压一点（90° 比 110° 好）、把盖板取下来、"
                 f"或者接受只读字轮窗（AI-on-the-edge 本来也主要读字轮）。",
                 cover_shadow._rule["why"], WARN)


@rule("OPT-10", "OPT", "画面是镜像的 —— 固件侧必须知道", severity=INFO,
      why="奇数次反射会让画面左右翻转。ROI 是在翻转后的画面上框的，"
          "如果按直觉去框会左右对不上。这不是缺陷，是必须写进文档的事实。")
def mirrored_image(design):
    return True, "光路含 1 次反射 → 传感器画面左右镜像；ROI 标定与固件配置见 DESIGN.md §4.6"
