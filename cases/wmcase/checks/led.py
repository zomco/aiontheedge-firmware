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
    """
    所有可能挡住 LED 光的实体。

    ⚠ 这份清单错过两轮了，每次都是同一类错误 —— **少列了一个真实存在的东西**：
      第一轮少了 ``mirror_holder``（挡光的正是托板支承片：报 0% 遮挡，实为 46%）；
      第二轮少了水表**自己**的件 —— 蓝色固定环（实测高 7.8mm，就立在表盘外缘上）
      和翻开停放的蓝色盖板。LED-05 的说明里甚至写着"环会在外缘投下一圈阴影，
      靠对置的另一颗灯补上，本条逐点验证"——可环根本没进过清单，
      那句话从来没被验证过。
      **文档写了『自检会验』不等于自检真的在验。**
    """
    return {
        "主体": design.body,
        "镜片托板": design.mirror_holder,
        "水表(含蓝环)": design.meter,
        "翻开的蓝盖": design.blue_cover,
    }


def _our_blockers(design) -> dict:
    """
    只算**我们自己的零件**。

    为什么要分两份清单：水表的蓝色固定环挡掉一部分掠射光是**几何必然**，
    不是设计缺陷 —— 同侧 LED 打向同侧外缘的光必然被 7.8mm 高的环切掉一段
    （对侧那颗补上，LED-05 验证这件事）。
    把它算进"结构件遮挡率"里，那个百分比就再也没法用来判断设计好坏了。
    **判据要能区分"我们造成的"和"世界本来就这样"，否则它只能告诉你有问题，
    不能告诉你该改谁。**
    """
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
    blockers = _our_blockers(design)
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
    for name, part in _our_blockers(design).items():
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
    # 要越过的是**蓝色固定环的内缘顶角**（高 ring_h = 7.8 实测），不是银圈顶面。
    # 拿 glass_depth（4.0）当门槛会把这条判据放宽将近一倍。
    need = m.ring_h
    return h > need + 3.0, (
        f"z({m.dial_r:.2f}) = {lg.pos_z} × {m.dial_r:.2f} / {lg.pos_r} = {h:.2f}mm "
        f"> 固定环内缘高 {need} + 3")


@rule("LED-05", "LED", "表盘没有全黑点；OCR 关键区被**两颗**灯照到",
      why="两颗对置不是冗余，是几何必需：单颗 LED 在这个入射角下，"
          "井壁会在对侧投出一条阴影带，正好压住最外圈指针。"
          "★ 但把遮挡物补全（加上 7.8mm 高的蓝色固定环）之后，"
          "原来那条『每一点都要两灯可达』的判据**在物理上就不可能满足**了："
          "同侧 LED 打向同侧最外缘的掠射光必然被环切掉 —— "
          "从 (38,0,20) 射向 (24,0,0) 的光线在 r=28.25 处只有 6.1mm 高，"
          "低于环顶 7.8mm。这是几何，不是缺陷。\n"
          "  所以判据拆成两级：**任何一点都不许全黑**（硬判据），"
          "**OCR 关键区要两灯可达**（有方向性阴影就读不准）。"
          "外缘单灯可达是可以接受的 —— 那里没有要读的东西。\n"
          "  **一条永远满足不了的判据比没有判据更糟**：它会让人习惯于忽略红字。")
def both_leds_reach(design):
    cfg = design.cfg
    blockers = _blockers(design)          # 这里要用**完整**清单：环的阴影是真的
    tips = ox.led_tips(cfg)

    def lit_count(x, y) -> int:
        target = ox.Vector(x, y, 0.0)
        n = 0
        for tip in tips:
            vec = target - tip
            unit = vec.normalized()
            if not any(ox._first_hit(s, tip, unit, vec.length - 0.3, t_min=0.5)
                       for s in blockers.values()):
                n += 1
        return n

    pts = ox.sample_dial_points(cfg, n_rim=16, n_ring=2)
    single, dark = [], []
    for x, y, tag in pts:
        n = lit_count(x, y)
        if n == 0:
            dark.append(tag)
        elif n == 1:
            single.append(tag)
    yield Result("LED-05", "LED", "表盘上没有全黑的点", not dark,
                 f"{len(pts)} 点中：两灯可达 {len(pts) - len(single) - len(dark)}，"
                 f"仅单灯 {len(single)}（多在墙侧/同侧最外缘，被固定环切掉掠射光），"
                 f"全黑 {len(dark)}" + (f" —— {dark[:5]}" if dark else ""),
                 both_leds_reach._rule["why"], ERROR)

    crit = ox.ocr_critical_points(cfg)
    c_single = [t for x, y, t in crit if lit_count(x, y) == 1]
    c_dark = [t for x, y, t in crit if lit_count(x, y) == 0]
    yield Result("LED-05-OCR", "LED", "OCR 关键区两灯可达", not c_single and not c_dark,
                 f"{len(crit)} 个关键点中：单灯 {len(c_single)}，全黑 {len(c_dark)}"
                 + (f" —— {sorted(set(c_single))[:6]}" if c_single else ""),
                 both_leds_reach._rule["why"], WARN)


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
