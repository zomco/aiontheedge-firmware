# -*- coding: utf-8 -*-
"""
照明自检 —— 回答"字轮上会不会有一片高光 / 一条阴影"。

核心事实（DESIGN.md §4.4）：表盘是一个 Ø56.5、深 7mm 的井，上面盖着
弧面玻璃 + 液封介质。**同轴照明（板载闪光灯）必然在字轮上打出镜面高光，
这是几何问题，调亮度无效。** 解法是离轴，而且必须是对置两颗。
"""

from __future__ import annotations

import math

from .. import optics as ox
from ..layout import led_grazing_height, led_incidence_deg
from . import ERROR, INFO, WARN, Result, fmt, inter_vol, rule


@rule("LED-01", "LED", "LED 必需出射锥 ∩ 主体 ≈ 0",
      why="判据取『覆盖表盘所需的那一份锥』而不是全部 120°："
          "120° 的光必然打到立板上，那不是缺陷。")
def cone_clear(design):
    v = inter_vol(ox.led_cone(design.cfg), design.body)
    return v < 40.0, f"{fmt(v)}（灯座根部允许微量）"


@rule("LED-02", "LED", "光线能越过银圈内缘照进表盘井里",
      why="曾经用错误的式子 `20×(38−30.9)/38 = 3.7mm` 断言 LED 会被银圈挡住，"
          "并据此推翻了一个本来正确的方案（DESIGN_NOTES §7.7）。"
          "正确式子：z(ρ) = z_led · ρ / R_led。式子写在这里，接受检查。")
def grazing(design):
    m, lg = design.cfg.meter, design.cfg.light
    h = led_grazing_height(design.cfg, m.dial_r)
    return h > m.glass_depth + 3.0, (
        f"z({m.dial_r:.2f}) = {lg.pos_z} × {m.dial_r:.2f} / {lg.pos_r} = {h:.2f}mm "
        f"> 井深 {m.glass_depth} + 3")


@rule("LED-03", "LED", "灯珠发光角覆盖整个表盘",
      why="普通 5mm 圆头 LED 只有 15~30° 半角，会打出中心亮斑、四个指针全黑。"
          "必须用 120° 全角的草帽灯。")
def beam_angle(design):
    lg = design.cfg.light
    return lg.half_angle_deg >= lg.need_half_angle_deg, \
        f"灯珠半角 {lg.half_angle_deg:.0f}° ≥ 需 {lg.need_half_angle_deg:.0f}°"


@rule("LED-04", "LED", "镜面反射瓣打不进采集锥（不会出现高光）",
      why="判据：LED 在表盘上的镜面反射方向与采集方向的夹角，"
          "必须明显大于采集锥半角。这是『高光』这件事唯一可计算的判据。")
def specular_misses(design):
    cfg = design.cfg
    lg, o = cfg.light, cfg.optics
    # 入射角（自法线）= 反射角；反射瓣方向与竖直采集方向的夹角 = 2×入射角
    inc = led_incidence_deg(cfg, 0.0)
    collect_half = math.degrees(math.atan(o.roi_r / o.path))
    margin = inc - collect_half
    return margin > 5.0, (
        f"表盘中心入射角 {inc:.1f}°，采集锥半角 {collect_half:.1f}°，"
        f"余量 {margin:.1f}°（要求 >5°）")


@rule("LED-05", "LED", "两颗对置 LED —— 阴影互补", severity=INFO,
      why="不是冗余，是几何必需：单颗 LED 在这个入射角下，井壁会在对侧"
          "投出约 12mm 宽的阴影带，正好压住最外圈指针。")
def two_leds(design):
    m, lg = design.cfg.meter, design.cfg.light
    # 井壁投影宽度 ≈ 井深 × tan(入射角)
    inc = led_incidence_deg(design.cfg, m.dial_r)
    shadow = m.glass_depth * math.tan(math.radians(inc))
    return True, (f"单颗在最外圈投出的阴影带约 {shadow:.1f}mm 宽 "
                  f"（井深 {m.glass_depth} × tan{inc:.1f}°），由对侧那颗补上")


@rule("LED-06", "LED", "灯珠不侵入受保护光锥")
def led_out_of_beam(design):
    from .. import refs
    v = inter_vol(ox.protected_cone(design.cfg), refs.led_bodies(design.cfg))
    return v < design.cfg.mfg.vol_tol, fmt(v)
