# -*- coding: utf-8 -*-
"""
一次设计的全部实体 —— 建一次，到处用。

布尔运算很贵（整机一轮大约十几秒），而自检要反复拿同样的实体做几十次
干涉计算。所以这里把"一次配置对应的所有实体"打包成 :class:`Design`，
建完缓存起来；自检、导出、报告都从同一个 ``Design`` 取。

好处不只是快：**自检和导出用的是同一份实体**，
不会出现"自检过了但导出的是另一版"这种事。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from functools import cached_property

from build123d import Compound, Part, Pos

from . import refs
from .layout import PodLayout, pod_layout
from .params import CFG, Config
from .parts import (
    build_body,
    build_foam_pad,
    build_mirror_holder,
    build_plate_envelope,
    build_slide_cover,
)


@dataclass
class Design:
    """一次配置下的完整设计。所有实体都是懒加载 + 缓存的。"""

    cfg: Config = field(default_factory=lambda: CFG)
    timings: dict[str, float] = field(default_factory=dict)

    # ---------------- 打印件 ----------------
    @cached_property
    def body(self) -> Part:
        return self._timed("body", build_body)

    @cached_property
    def mirror_holder(self) -> Part:
        return self._timed("mirror_holder", build_mirror_holder)

    @cached_property
    def slide_cover(self) -> Part:
        return self._timed("slide_cover", build_slide_cover)

    @property
    def printed_parts(self) -> dict[str, Part]:
        """要 3D 打印的三个件。导出和拓扑自检都遍历它。"""
        return {
            "body": self.body,
            "mirror_holder": self.mirror_holder,
            "slide_cover": self.slide_cover,
        }

    # ---------------- 参考件 ----------------
    @cached_property
    def board_ref(self) -> refs.RefModel:
        return self._timed("board", lambda c: refs.board(c))

    @property
    def board(self) -> Part:
        return self.board_ref.shape

    @cached_property
    def led_ref(self) -> refs.RefModel:
        return refs.led_pair(self.cfg)

    @property
    def leds(self) -> Part:
        return self.led_ref.shape

    @cached_property
    def mirror_glass(self) -> Part:
        return refs.mirror_glass(self.cfg)

    @cached_property
    def meter_ref(self) -> refs.RefModel:
        return refs.meter_mock(self.cfg)

    @property
    def meter(self) -> Part:
        return self.meter_ref.shape

    @cached_property
    def foam(self) -> Part:
        return build_foam_pad(self.cfg)

    @cached_property
    def plate_envelope(self) -> Part:
        """托板本体的包络，用来把"耳脚"从托板里分出来。"""
        return build_plate_envelope(self.cfg)

    @cached_property
    def holder_ears_and_feet(self) -> Part:
        """托板去掉本体之后剩下的部分（三角耳 + 支承脚 + 提手）。"""
        return self.mirror_holder - self.plate_envelope

    # ---------------- 布局 ----------------
    @cached_property
    def pod(self) -> PodLayout:
        return pod_layout(self.cfg)

    # ---------------- 装配体 ----------------
    def assembly(self, include_illustrative: bool = False) -> Compound:
        """
        供人眼检视的装配体。

        ``include_illustrative=True`` 会带上 ``watermeter-dn25.step``——
        它只是"长得像"，尺寸是 DN25，**任何自检都不许引用它**。
        """
        children = [
            Part(self.body.wrapped, label="body"),
            Part(self.mirror_holder.wrapped, label="mirror_holder"),
            Part(self.slide_cover.wrapped, label="slide_cover"),
            Part(self.mirror_glass.wrapped, label="mirror_glass"),
            Part(self.board.wrapped, label="esp32s3cam"),
            Part(self.leds.wrapped, label="leds"),
            Part(self.foam.wrapped, label="eva_foam"),
            Part(self.meter.wrapped, label="meter_mock"),
        ]
        if include_illustrative:
            ill = refs.meter_illustrative(self.cfg)
            if ill is not None:
                children.append(Part(ill.shape.wrapped, label="meter_dn25_illustrative"))
        return Compound(children=children)

    # ---------------- 工具 ----------------
    def _timed(self, name: str, fn):
        t0 = time.time()
        out = fn(self.cfg)
        self.timings[name] = time.time() - t0
        return out


def build(cfg: Config | None = None) -> Design:
    """建一份设计。这是外部唯一的入口。"""
    return Design(cfg or CFG)
