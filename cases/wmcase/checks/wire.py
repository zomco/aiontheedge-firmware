# -*- coding: utf-8 -*-
"""
走线自检 —— "线真的走得通吗"。

走线路径是一串首尾相接的**空腔**：

    LED 座孔 → 引线过孔 → 立板内侧竖槽 → 横槽 → 吊臂 U 型腔 → 吊舱型腔

"每一段都挖了"不等于"它们连成一条"。差 0.3mm 没接上，模型看起来毫无异样，
现场却要拆开重钻。把这些空腔并起来查连通性，是唯一能自动发现这件事的办法
—— 和 TOPO-01 查实体连通性是同一个套路，只是查的是"洞"。
"""

from __future__ import annotations

from build123d import Part

from ..geometry import bx, mirror_x
from ..parts.body import (
    build_arm_half,
    build_led_cut_half,
    build_pod_cuts,
    build_wire_groove_half,
)
from . import ERROR, WARN, Result, rule


@rule("WIRE-01", "WIRE", "LED 引线通道与立板走线槽连通",
      why="LED 座孔和走线槽是两次独立的布尔，各自都『挖对了』也可能差一点没接上。")
def led_to_groove(design):
    cfg = design.cfg
    void = build_led_cut_half(cfg) + build_wire_groove_half(cfg)
    n = len(void.solids())
    return n == 1, f"座孔 ∪ 走线槽 = {n} 个连通域（应为 1）"


@rule("WIRE-02", "WIRE", "整条走线路径连通：LED → 立板 → 吊臂 → 吊舱",
      why="这是把 TOPO-01 的思路用在『洞』上：把路径上所有空腔并起来，"
          "连通域数必须是 1。差 0.3mm 没接上，模型看起来毫无异样。")
def full_route(design):
    cfg = design.cfg
    void = (build_led_cut_half(cfg)
            + build_wire_groove_half(cfg)
            + build_arm_half(cfg, hollow=True)
            + build_pod_cuts(cfg))
    n = len(void.solids())
    return n == 1, f"座孔 ∪ 走线槽 ∪ 吊臂腔 ∪ 吊舱腔 = {n} 个连通域（应为 1）"


@rule("WIRE-03", "WIRE", "电源进线孔在吊舱底面（防结露倒灌）",
      why="楼梯间潮湿有结露风险。进线孔朝下，冷凝水就不会沿线灌进电子舱。"
          "这条是位置判据，不是形状判据。")
def power_entry_down(design):
    c = design.cfg.case
    # 进线孔从吊舱底面 pod_z0 打到型腔底 cav_z0，方向是 +Z（朝上进腔）
    return c.pod_z0 < c.cav_z0, \
        f"进线孔自底面 z={c.pod_z0} 通到腔底 z={c.cav_z0}，开口朝下"


@rule("WIRE-04", "WIRE", "走线槽全部开在内表面，外观面无槽", severity=WARN,
      why="外表面开槽会积灰、进水，而且难看。判据：立板外侧面（X=mast_outer_x）"
          "所在的薄层里不应该有走线槽留下的空腔。")
def grooves_hidden(design):
    cfg = design.cfg
    c = cfg.case
    skin = bx(c.mast_outer_x - 0.6, c.mast_outer_x + 0.6, -40, 40, 0, 70)
    skin = mirror_x(skin)
    groove = mirror_x(build_wire_groove_half(cfg) + build_led_cut_half(cfg))
    try:
        v = (skin & groove).volume
    except Exception:  # noqa: BLE001
        v = 0.0
    return v < 1.0, f"外表面薄层内的槽体积 {v:.2f} mm³"
