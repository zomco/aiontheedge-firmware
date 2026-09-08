# -*- coding: utf-8 -*-
"""
照明自检 —— 回答三件事：

1. **光被挡了吗** —— 逐点追踪 ``灯珠发光面 → 表盘``；
2. **照得全吗** —— 覆盖整个表盘需要多大的半锥角，灯珠给不给得起；
3. **会反光吗** —— 逐点算镜面反射方向和采集方向的夹角。

核心事实（DESIGN.md §4.5）：表盘是一个 Ø56.5、深 7mm 的井，上面盖着
弧面玻璃 + 液封介质。**同轴照明（板载闪光灯）必然在字轮上打出镜面高光，
这是几何问题，调亮度无效。** 解法是离轴，而且必须是对置两颗。

⚠ 这一节最贵的一个教训
----------------------
早先的 LED-01 有两个致命简化，导致它**无论设计怎么错都查不出来**：

* 只拿光锥和 ``body`` 求交，**从来没和 mirror_holder 求交过** ——
  而挡光的正是托板的支承片；
* 把灯珠当成**点光源**，只从顶点发射线。

实测代价：支承片底边和灯珠顶点等高时，点光源追踪 **0% 被挡**，
按真实 Ø5 穹顶取 9 个发光点追踪 **46% 被挡**（穹顶上半边整个被遮死）。
现在两个简化都去掉了。
"""

from __future__ import annotations

import math

from .. import optics as ox
from ..layout import led_grazing_height
from . import ERROR, INFO, WARN, Result, fmt, inter_vol, rule


def _blockers(design) -> dict:
    """所有可能挡住 LED 光的实体。**托板必须在里面。**"""
    return {"主体": design.body, "镜片托板": design.mirror_holder}


# =============================================================================
#  1. 光被挡了吗
# =============================================================================

@rule("LED-01", "LED", "灯珠发光面到表盘的光线不被遮挡（逐点追踪）",
      why="这条替代了原来的『光锥 ∩ 主体』体积判据，改了两处："
          "① 遮挡物加上了 mirror_holder —— 挡光的恰恰是托板的支承片；"
          "② 灯珠按真实 Ø5 穹顶取 9 个发光点，不再当成点光源。"
          "点光源 + 只查 body 的旧判据在同一个设计上报 0% 遮挡，"
          "而真实情况是 46%。**判据的分辨率不够时，它给出的『通过』毫无意义。**")
def illumination_trace(design):
    cfg = design.cfg
    blockers = _blockers(design)
    pts = ox.sample_dial_points(cfg, n_rim=16, n_ring=2)
    total = blocked = 0
    worst_emitter = None
    worst_n = -1
    for side in (+1, -1):
        for emitter in ox.led_emitter_points(cfg, side=side):
            n_blocked = 0
            for x, y, _tag in pts:
                target = ox.Vector(x, y, 0.0)
                vec = target - emitter
                length = vec.length
                unit = vec.normalized()
                if any(ox._first_hit(s, emitter, unit, length - 0.3, t_min=0.5)
                       for s in blockers.values()):
                    n_blocked += 1
                total += 1
            blocked += n_blocked
            if n_blocked > worst_n:
                worst_n, worst_emitter = n_blocked, emitter
    ratio = 100.0 * blocked / total if total else 0.0
    detail = (f"{len(pts)} 个表盘点 × 18 个发光点 = {total} 条光线，"
              f"被挡 {blocked}（{ratio:.1f}%）")
    if worst_n > 0:
        detail += (f"；最差的发光点 "
                   f"({worst_emitter.X:.1f},{worst_emitter.Y:.1f},{worst_emitter.Z:.1f}) "
                   f"被挡 {worst_n}/{len(pts)}")
    return ratio < 5.0, detail


@rule("LED-02", "LED", "有用光束（灯珠→表盘的斜锥）没有被结构件侵入",
      why="体积法粗筛，和 LED-01 的射线法互为补充："
          "射线法只查采样点，体积法能发现『采样点之间』的遮挡。"
          "锥体取『发光面到可视表盘圆盘』的斜锥，而不是绕灯轴的正圆锥 —— "
          "真正要保护的是能打到表盘的那一束光，不是某个角度范围。")
def useful_cone_clear(design):
    cone = ox.useful_led_cone(design.cfg)
    out = []
    for name, part in _blockers(design).items():
        v = inter_vol(cone, part)
        out.append(Result("LED-02", "LED", f"有用光束 ∩ {name}", v < 60.0,
                          f"{fmt(v)}（灯座根部允许微量）",
                          useful_cone_clear._rule["why"], ERROR))
    return out


# =============================================================================
#  2. 照得全吗
# =============================================================================

@rule("LED-03", "LED", "灯珠发光角覆盖整个表盘",
      why="覆盖整个表盘所需的半锥角是**几何唯一确定的派生量**，"
          "早先写成手填的 21°，后来 LED 从 z=30 降到 20，这个数没跟着变，"
          "『必需光锥』整整小了一半。**凡是能由几何唯一确定的量，"
          "都不许出现在参数表里。**"
          "另外：普通 5mm 圆头 LED 只有 15~30° 半角，会打出中心亮斑、四个指针全黑，"
          "必须用 120° 全角的草帽灯。")
def beam_angle(design):
    lg, m = design.cfg.light, design.cfg.meter
    need = lg.required_half_angle_deg(m.dial_r)
    return lg.half_angle_deg >= need + 5.0, (
        f"灯珠标称半角 {lg.half_angle_deg:.0f}° ≥ 需 {need:.1f}° + 5°；"
        f"最难照到的是侧后方的表盘边缘，不是正对面")


@rule("LED-04", "LED", "光线能越过银圈内缘照进表盘井里",
      why="曾经用错误的式子 `20×(38−30.9)/38 = 3.7mm` 断言 LED 会被银圈挡住，"
          "并据此推翻了一个本来正确的方案（DESIGN_NOTES §7.7）。"
          "正确式子：z(ρ) = z_led · ρ / R_led。式子写在这里，接受检查。")
def grazing(design):
    m, lg = design.cfg.meter, design.cfg.light
    h = led_grazing_height(design.cfg, m.dial_r)
    return h > m.glass_depth + 3.0, (
        f"z({m.dial_r:.2f}) = {lg.pos_z} × {m.dial_r:.2f} / {lg.pos_r} = {h:.2f}mm "
        f"> 井深 {m.glass_depth} + 3")


@rule("LED-05", "LED", "每个表盘采样点都被**两颗**灯照到",
      why="两颗对置不是冗余，是几何必需：单颗 LED 在这个入射角下，"
          "井壁会在对侧投出一条阴影带，正好压住最外圈指针。"
          "所以判据不是『至少一颗照到』，而是『两颗都照到』。")
def both_leds_reach(design):
    cfg = design.cfg
    blockers = _blockers(design)
    pts = ox.sample_dial_points(cfg, n_rim=16, n_ring=2)
    tips = ox.led_tips(cfg)
    single, dark = [], []
    for x, y, tag in pts:
        target = ox.Vector(x, y, 0.0)
        lit = 0
        for tip in tips:
            vec = target - tip
            unit = vec.normalized()
            if not any(ox._first_hit(s, tip, unit, vec.length - 0.3, t_min=0.5)
                       for s in blockers.values()):
                lit += 1
        if lit == 0:
            dark.append(tag)
        elif lit == 1:
            single.append(tag)
    ok = not dark and not single
    return ok, (f"{len(pts)} 点中：两灯可达 {len(pts) - len(single) - len(dark)}，"
                f"仅单灯 {len(single)}，全黑 {len(dark)}"
                + (f"；单灯点示例 {single[:5]}" if single else ""))


# =============================================================================
#  3. 会反光吗
# =============================================================================

@rule("LED-06", "LED", "OCR 关键区不会出现镜面高光",
      why="判据只看**字轮窗 + 四个指针盘** —— 表盘最外缘（蓝圈、刻度）"
          "有没有反光不影响读数，把它算进去只会得到一个吓人但没意义的数字。"
          "式子见 optics.specular_separation_deg。"
          "⚠ 计算把表盘玻璃当成平面，实际是弧面 + 液封，反射瓣会展宽，"
          "所以要留足余量，不要卡着阈值用。")
def no_glare_on_ocr(design):
    cfg = design.cfg
    tips = ox.led_tips(cfg)
    worst, where = 180.0, ""
    for x, y, tag in ox.ocr_critical_points(cfg):
        p = ox.Vector(x, y, 0.0)
        for tip in tips:
            a = ox.specular_separation_deg(cfg, p, tip)
            if a < worst:
                worst, where = a, f"{tag}({x:+.0f},{y:+.0f})"
    return worst > 25.0, (f"关键区最小『反射-采集』夹角 {worst:.1f}°（要求 >25°），"
                          f"最差在 {where}")


@rule("LED-07", "LED", "整个表盘的镜面高光分布", severity=INFO,
      why="外缘的高光不影响 OCR，但值得知道它在哪 —— "
          "现场如果看到一圈亮弧，对照这里就知道是几何必然，不用去查别的原因。")
def glare_map(design):
    cfg = design.cfg
    tips = ox.led_tips(cfg)
    worst, where = 180.0, ""
    for i in range(0, 21):
        r = cfg.meter.dial_r * i / 20
        for j in range(36):
            a = 2 * math.pi * j / 36
            p = ox.Vector(r * math.cos(a), r * math.sin(a), 0.0)
            for tip in tips:
                sep = ox.specular_separation_deg(cfg, p, tip)
                if sep < worst:
                    worst, where = sep, f"r={r:.1f} 处"
    return True, (f"全表盘最小夹角 {worst:.1f}°（{where}，通常落在同侧最外缘）；"
                  f"该处是蓝圈/刻度区，没有 OCR 数据")


@rule("LED-08", "LED", "灯珠不侵入相机的受保护光锥")
def led_out_of_beam(design):
    from .. import refs
    v = inter_vol(ox.protected_cone(design.cfg), refs.led_bodies(design.cfg))
    return v < design.cfg.mfg.vol_tol, fmt(v)
