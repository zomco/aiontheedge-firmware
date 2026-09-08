# -*- coding: utf-8 -*-
"""
镜片托板 ``mirror_holder`` —— 每月人工抄表时唯一需要动的零件。

为什么要把镜片单独做成一个可提起的件
------------------------------------
业主要求保留人工抄表（每月 1 日 + 租户争议时）。抄表时镜片正好挡住字轮，
必须移开。方案演进过四轮（DESIGN_NOTES §8）：

* 绕表盘轴旋转移开 → **旋转轴正好穿过反射镜，转了等于没转**
* 径向抽出燕尾     → 燕尾长期蠕变；且抬升行程会让镜片撞天花板
* 移动整条悬臂     → 要动 100g 的东西，还会破坏相机对位
* **只提起这块托板** ← 现在的方案

托板靠两片支承片落在立板的**两个等高**托台上，4 根竖直销约束平面内自由度。
动作只有两步：**垂直上提 8mm 脱离销，再沿 +Y 平推出来。**
相机、镜头、抱箍全都不动，所以放回去以后 ROI 不需要重新标定。

> 托台等高这件事看起来无关紧要，其实是可拆性的关键。
> 上一版按"托板底面是 45° 斜面"的直觉把两个托台做成一高一低，
> 结果整块托板**根本拿不出来** —— 抽出时低的那半段会扫过高的托台，
> 需要抬升 30mm 以上，而天花板只给 11mm。
> 这个错误静态干涉一条都报不出来，是 SEQ 的逐点路径仿真抓到的。
"""

from __future__ import annotations

from build123d import Axis, Box, Part, Plane, Pos

from ..geometry import bx, cyl_z, mirror_x, safe_fillet, yz_plate
from ..layout import mirror_frame
from ..params import Config


# =============================================================================
#  尺寸推导
# =============================================================================

#  局部 z 的零点定义（**改这里等于改整条光路，务必先读 optics.py**）
#  ------------------------------------------------------------------
#  ``layout.mirror_frame`` 的局部 z = 0 就是**镜片镀膜面**所在的平面，
#  也就是 ``z = y + mirror_z`` 这张 45° 面。光路计算全靠这个约定。
#
#      局部 z = +lip_t                唇口外表面（伸到镜面前方，兜住镜片）
#      局部 z =  0                    ★ 镜片镀膜面 = 光学基准面
#      局部 z = −mirror_t             镜片背面
#      局部 z = −mirror_t − wall      托板背面
#
#  早期版本把零点定在"托板正面"，结果镜片实际反射面比设计平面**退后 0.8mm**，
#  光线追踪直接打空。这是个只有射线求交才能发现的错误。

def plate_z_range(cfg: Config) -> tuple[float, float]:
    """托板在局部 z 上的起止（从背面到唇口外表面）。"""
    return (-(cfg.optics.mirror_t + cfg.mfg.wall), cfg.mfg.plate_t_extra)


def plate_thickness(cfg: Config) -> float:
    """托板厚度 = 唇口料 + 镜片 + 背板料。"""
    z0, z1 = plate_z_range(cfg)
    return z1 - z0                                                        # 5.3


def plate_length(cfg: Config) -> float:
    """托板沿 45° 斜面方向的长度 = 镜片长 + 两端壁厚。"""
    return cfg.optics.mirror_l + 2 * cfg.mfg.wall                          # 75


# =============================================================================
#  零件
# =============================================================================

def build_plate(cfg: Config) -> Part:
    """托板本体（还没开 T 型槽）。"""
    c = cfg.case
    z0, z1 = plate_z_range(cfg)
    plate = (mirror_frame(cfg) * Pos(0, 0, (z0 + z1) / 2)
             * Box(c.holder_plate_w, plate_length(cfg), z1 - z0))
    return safe_fillet(plate, plate.edges().filter_by(Axis.X), 2.0)


def build_t_slot(cfg: Config) -> Part:
    """
    T 型槽（去料）—— 镜面朝下也不会掉出来。

    直通方槽的问题：反射面必须朝下（朝表盘），镜片只靠重力压在槽底，
    整机一晃就掉。所以把开口收窄，两侧各留 ``holder_lip`` 宽的唇口::

        深部  50.2 宽  ← 容纳镜片
        开口  45.6 宽  ← 两侧各 2.2mm 唇口兜住

    镜片从局部 −Y 一端滑入（全局方向是斜向上前方），在台面上装好，
    **不在现场装**。现场只做"整块托板提起 / 放回"。
    """
    o, m, c = cfg.optics, cfg.mfg, cfg.case
    loc = mirror_frame(cfg)
    pl = plate_length(cfg)
    lip_t = m.plate_t_extra
    # 让槽从 −Y 端伸出托板之外，形成插入口
    slot_len = o.mirror_l + m.fit_static + pl / 2
    y_off = -pl / 4

    # 深部：容纳镜片，局部 z 从 −mirror_t−0.1 到 +0.1（镀膜面在 z=0）
    deep = (loc * Pos(0, y_off, -(o.mirror_t + 0.2) / 2 + 0.1)
            * Box(o.mirror_w + m.fit_static, slot_len, o.mirror_t + 0.2))
    # 开口：穿透唇口那一层，宽度收窄，两侧各留 holder_lip
    mouth = (loc * Pos(0, y_off, lip_t / 2)
             * Box(o.mirror_w - 2 * c.holder_lip, slot_len, lip_t + 2 * m.eps))
    return deep + mouth


def build_bracket_half(cfg: Config) -> Part:
    """
    支承片（+X 半边）—— 一片顶三样用：把托板接到托台上、包住定位销、当提手的根。

    早期版本是"三角耳 + 两只支承脚"两组零件，配两个**不等高**的托台。
    那个方案的致命问题不是强度也不是干涉，而是**拿不出来**：
    平推时后半段会扫过前托台（详见 params.Case 里 pad_front_z 的注释）。
    现在托台等高，支承片的底边就是一条水平线，抬 8mm 即可平推脱离。

    三个硬约束（都写在 params.Case.holder_bracket_x 上）：

    * 内缘 ≤ 托板半宽，否则接不到托板；
    * 外缘 < LED 灯座凸台最内缘，否则平推时撞灯座（自检 SEQ-02）；
    * 整片要包住定位销。
    """
    c = cfg.case
    return yz_plate(c.holder_bracket_profile, 2.0,
                    c.holder_bracket_t, c.holder_bracket_x[0])


def build_pin_holes(cfg: Config) -> Part:
    """
    定位销孔（去料）。

    **防呆**：前后销直径不同（后 Ø4 / 前 Ø5），孔也跟着不同。
    托板前后装反时，Ø4.2 的后孔套不进 Ø5 的前销，物理上装不上去。
    自检 POKA-01 会把托板前后调头再算一次干涉来验证。
    """
    c, m = cfg.case, cfg.mfg
    cuts = Part()
    for (y0, y1), z_pad, pin_d in (
        (c.pad_rear_y, c.pad_rear_z, c.pin_d_rear),
        (c.pad_front_y, c.pad_front_z, c.pin_d_front),
    ):
        cuts += cyl_z(c.pin_x, (y0 + y1) / 2, z_pad - m.eps, z_pad + c.pin_h + 2,
                      pin_d + m.fit_static)
    return mirror_x(cuts)


#: 提手：从两片支承片前端伸出的**水平**悬臂 + 一根横梁。
#:
#: 为什么长这样（三条约束同时成立才行）：
#:
#: * **不能加高** —— 天花板只剩 ~10mm 余量，竖直提手会把提起行程吃掉；
#: * **不能放中间**（X≈0）—— 中间是 T 型槽的插入口，横穿过去既会被
#:   槽切断（实测：托板会裂成 2 个孤立实体），也会挡住镜片滑入；
#: * **不能挡光** —— 放在 X ±32~38，径向早已跑出光锥（该处锥半径 <15mm）；
#:   横梁虽然过中心，但 z 58~64 高于该处反射光束上缘（y=32 处约 53.8）。
GRIP_EAR_X = (31.0, 39.0)   # 与 holder_bracket_x 一致（提手是支承片的延伸）
GRIP_Y = (18.0, 34.0)          # 从支承片前缘伸到 y=34（越过立板前缘 y=22）
GRIP_Z = (58.0, 64.0)
GRIP_BAR_Y = (28.0, 34.0)      # 横梁：让人一只手就能提，也是防呆刻字的载体


def build_grip(cfg: Config) -> Part:
    """
    提手。

    每月抄表时人从 +Y 方向伸手进来，握住横梁垂直上提 8mm 即可脱离定位销。
    支承片和立板之间只有 4.5mm 间隙，手指伸不进去，所以必须有它。
    立板前缘只到 y=22，所以 y>22 的那段是完全敞开的，抓握没有障碍。
    """
    x0, x1 = GRIP_EAR_X
    tab = bx(x0, x1, GRIP_Y[0], GRIP_Y[1], GRIP_Z[0], GRIP_Z[1])
    grip = mirror_x(tab)
    grip += bx(-x1, x1, GRIP_BAR_Y[0], GRIP_BAR_Y[1], GRIP_Z[0], GRIP_Z[1])
    return safe_fillet(grip, grip.edges().filter_by(Axis.Z), 2.0)


def build_face_marker(cfg: Config) -> Part:
    """
    镜面朝向标识（去料，刻在提手上表面）。

    前表面镜**必须镀膜面朝下**（朝表盘）。装反了会变成普通背镀镜，
    玻璃前后两次反射产生双像鬼影，字轮重影，OCR 直接失效。
    这一条**无法做成几何防呆**（一块矩形玻璃两面都能装），
    所以只能刻字提醒 —— 这是本设计里唯一一处"靠说明书"的地方，
    ASSEMBLY.md 里有对应的检查步骤。

    字体不可用时降级成一个箭头三角形（永远不会因为字体问题让建模失败）。
    """
    depth = 0.6
    z_top = GRIP_Z[1]
    plane = Plane(origin=(0, (GRIP_BAR_Y[0] + GRIP_BAR_Y[1]) / 2, z_top - depth),
                  x_dir=(1, 0, 0), z_dir=(0, 0, 1))
    try:
        from build123d import Text, extrude
        sketch = Text("COATED SIDE DOWN", font_size=4.0)
        return extrude(plane * sketch, amount=depth + cfg.mfg.eps)
    except Exception:  # noqa: BLE001  字体环境有问题时降级成一个箭头，绝不让建模失败
        from build123d import Polyline, extrude, make_face
        arrow = make_face(Polyline((-6, 2), (6, 2), (0, -3), close=True))
        return extrude(plane * arrow, amount=depth + cfg.mfg.eps)


# =============================================================================
#  总装
# =============================================================================

def build_mirror_holder(cfg: Config) -> Part:
    """托板总装：托板 + 提手 + 两片支承片 − T型槽 − 销孔 − 刻字。"""
    holder = build_plate(cfg) + build_grip(cfg) + mirror_x(build_bracket_half(cfg))
    holder -= build_t_slot(cfg)
    holder -= build_pin_holes(cfg)
    holder -= build_face_marker(cfg)
    return holder


def build_plate_envelope(cfg: Config) -> Part:
    """
    只包含托板本体的包络（比实际托板略大）。

    用途：自检时要单独回答"**支承片和提手**有没有挡光"——托板本体挡住光锥是
    正常的（它就是反射面所在的位置），支承片挡住就是错误。用它把两者分开。
    """
    z0, z1 = plate_z_range(cfg)
    return (mirror_frame(cfg) * Pos(0, 0, (z0 + z1) / 2)
            * Box(cfg.case.holder_plate_w + 1, plate_length(cfg) + 1, z1 - z0 + 1))
