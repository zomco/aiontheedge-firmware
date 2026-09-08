# -*- coding: utf-8 -*-
"""
滑盖 ``slide_cover`` —— 吊舱的后盖，竖直下滑到位，**不用一颗螺丝**。

为什么不用螺丝
--------------
40 台设备、每台现场调试可能开合数次。螺丝意味着现场要带螺丝刀、
要防止掉落（下面是楼梯间）、自攻孔反复拧会滑牙。滑盖靠形状约束，
装上去只有一个动作：对准顶部开口，往下推到底。

约束是**逐自由度**核算的（DESIGN_NOTES §7.6 的教训：
v2.3 的"槽"只约束了 X，盖板可以直接向后掉出来——舌片有了，槽没有）::

    −Y  侧壁前沿挡住
    +Y  后压边（1.8mm）挡住
    ±X  两侧滑槽夹住舌片
    −Z  槽底限位
    +Z  重力；需要时向上抽出 80mm 即可取下

自检里每一条都有对应的**反向测试**（往那个方向推 0.6mm 必须产生干涉），
只测"不干涉"是不够的——那只说明装得进去，不说明装上后不会掉。
"""

from __future__ import annotations

from build123d import Axis, Part, Pos

from ..geometry import bx, cyl_y, safe_fillet
from ..params import Config


def cover_z_range(cfg: Config) -> tuple[float, float]:
    """盖板的 Z 起止。下端略高于槽底，留 0.5mm 落座余量。"""
    return (cfg.case.cav_z0 + 0.5, cfg.case.pod_z1)


def build_slide_cover(cfg: Config, lift: float = 0.0) -> Part:
    """
    :param lift: 沿 +Z 抬升的距离（自检模拟抽出动作时用）
    """
    c, m = cfg.case, cfg.mfg
    z0, z1 = cover_z_range(cfg)

    # ---- 主板 + 两侧舌片 ----
    cover = bx(-c.cav_half_x, c.cav_half_x, c.cover_y0, c.cover_y1, z0, z1)
    cover += bx(-c.cover_tongue_x, c.cover_tongue_x, c.cover_y0, c.cover_y1, z0, z1)

    # ---- 防呆：+X 舌片的**最下面一段**收窄，让位给槽底的定位筋 ----
    #  正装时筋落在收窄段里，毫无阻碍；
    #  上下颠倒或前后调头装，筋就会撞上满宽的舌片（自检 POKA-02 验证）。
    #  收窄段必须在最下面：盖板是从上往下滑进来的，只有舌片最下面这一段
    #  会经过筋所在的高度，别的位置都不会。
    key_top = c.cav_z0 + c.cover_key_len + m.fit_slide
    cover -= bx(c.cover_tongue_x - c.cover_key_depth - m.fit_slide, c.cover_tongue_x + m.eps,
                c.cover_y0 - m.eps, c.cover_y1 + m.eps,
                z0 - m.eps, key_top)

    cover = safe_fillet(cover, cover.edges().filter_by(Axis.Y).group_by(Axis.Z)[-1], 1.2)

    # ---- 顶部手指凹槽：拇指顶住往上抽 ----
    cover -= cyl_y(0, c.cover_y0 - m.eps, c.cover_y1 + m.eps, z1, c.cover_finger_d)

    # ---- 散热 / 排料孔（dfam_rules §8：槽宽 ≤2mm 才能完美桥接，
    #      这里用圆孔 Ø4，打印姿态下是竖直孔，无桥接问题）----
    z = z0 + 12.0
    while z < z1 - 12.0:
        cover -= cyl_y(0, c.cover_y0 - m.eps, c.cover_y1 + m.eps, z, c.cover_vent_d)
        z += 12.0

    return Pos(0, 0, lift) * cover


def build_foam_pad(cfg: Config) -> Part:
    """
    滑盖内侧的 EVA 泡棉（**外购件，不打印**）。

    它负责板卡的 +Y 约束：把板顶向前止挡面。
    用软泡棉而不是硬定位，是因为板背面元件高度有公差，硬顶会翘板。

    副作用是好的：镜头位置由**摄像头模组**在方腔里的落位决定，
    而不是由 PCB 决定 —— 光学重复精度反而更高。

    厚度必须覆盖"盖板前表面 → 板卡最后端"的间隙并留出压缩量，
    自检 FIT-05 会核算这条尺寸链。
    """
    from ..layout import pod_layout

    c, p = cfg.case, pod_layout(cfg)
    y1 = c.cover_y0
    y0 = y1 - c.cover_foam_t
    half_x = p.pcb_half_x
    return bx(-half_x, half_x, y0, y1, p.pcb_z0 + 1, p.pcb_z1 - 1)
