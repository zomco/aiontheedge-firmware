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

    # ---------------- 爆炸图 ----------------
    def exploded(self, spread: float = 1.0, guides: bool = True) -> Compound:
        """
        爆炸图 —— 回答"**谁装在谁上面、按什么顺序、从哪个方向装进去**"。

        三条设计意图：

        1. **分离方向 = 装入方向的反向**，而且直接取自 :mod:`wmcase.assembly`
           的装配步骤。所以爆炸图上各件拉开的方向，就是装配时它该走的方向，
           不用再对着说明书猜。改了装配顺序，爆炸图自动跟着变。
        2. **子件名字带装配序号**（``01_body`` / ``07_board`` …），
           在 CAD 的模型树里一眼就能读出顺序。
        3. **引导杆**把每个件从爆炸位置连回安装位置，
           人眼不用在空中猜"这块是塞哪儿的"。

        :param spread: 分离距离的倍数，1.0 是默认间距
        :param guides: 是否画引导杆
        """
        from build123d import Part as _Part

        from .assembly import exploded_offsets, install_sequence, led_explode_axis
        from .geometry import mirror_x, rod
        from .refs import led_single

        offsets = exploded_offsets(self.cfg)
        order = {st.part: st.index for st in install_sequence(self.cfg) if st.part != "-"}

        def moved(part: Part, key: str) -> Part:
            dx, dy, dz = offsets.get(key, (0.0, 0.0, 0.0))
            return Pos(dx * spread, dy * spread, dz * spread) * part

        children: list[Part] = [
            _Part((moved(self.meter, "meter")).wrapped, label="00_meter_mock"),
            _Part(moved(self.body, "body").wrapped, label="01_body"),
        ]

        # 两颗 LED 各自沿自己的灯轴向外推 —— 一个平移向量没法把对称的两颗同时拉开，
        # 所以先推 +X 那颗，再整体镜像（镜像会把位移一起镜像过去）。
        ax = led_explode_axis(self.cfg)
        led_step = next(st for st in install_sequence(self.cfg) if st.part == "leds")
        base = offsets["body"]
        d = led_step.explode_mm * spread
        one = Pos(base[0] * spread + ax[0] * d,
                  base[1] * spread + ax[1] * d,
                  base[2] * spread + ax[2] * d) * led_single(self.cfg)
        children.append(_Part(mirror_x(one).wrapped, label="03_leds"))

        for key, label in (("board", "07_esp32s3cam"), ("foam", "08_eva_foam"),
                           ("slide_cover", "09_slide_cover"),
                           ("mirror_glass", "11_mirror_glass"),
                           ("mirror_holder", "12_mirror_holder")):
            src = {"board": self.board, "foam": self.foam,
                   "slide_cover": self.slide_cover,
                   "mirror_glass": self.mirror_glass,
                   "mirror_holder": self.mirror_holder}[key]
            children.append(_Part(moved(src, key).wrapped, label=label))

        if guides:
            installed = {"body": self.body, "board": self.board, "foam": self.foam,
                         "slide_cover": self.slide_cover,
                         "mirror_glass": self.mirror_glass,
                         "mirror_holder": self.mirror_holder}
            bars = Part()
            for key, part in installed.items():
                dx, dy, dz = offsets.get(key, (0.0, 0.0, 0.0))
                if (dx, dy, dz) == (0.0, 0.0, 0.0):
                    continue
                c = part.bounding_box().center()
                bars += rod((c.X, c.Y, c.Z),
                            (c.X + dx * spread, c.Y + dy * spread, c.Z + dz * spread),
                            1.6)
            if bars.volume > 0:
                children.append(_Part(bars.wrapped, label="99_assembly_guides"))
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
