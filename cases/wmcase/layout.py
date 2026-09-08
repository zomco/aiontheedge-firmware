# -*- coding: utf-8 -*-
"""
布局推导 —— 把 ``params.py`` 里的**输入**换算成建模用的**位置**。

为什么单独一层
--------------
``params.py`` 只放"从哪来的数字"，``parts/*.py`` 只放"怎么长出形状"。
中间这些换算（比如"PCB 前表面在 Y=88.07"）既不是输入也不是形状，
它们是**尺寸链**——而本项目历史上最贵的两次翻车都是尺寸链算错
（DESIGN_NOTES §7.3 抱箍夹不紧、§7.5 托台顶死托板）。

把尺寸链集中在一个文件里，好处是：

* 建模代码和自检代码用的是**同一份**推导，不会各算各的；
* 每条推导旁边可以写出判据式子，接受检查（§7.7 的教训）；
* 换开发板 / 换表型时，只有这个文件需要重新读一遍。

所有函数都是纯函数：``Config -> 数``或``Config -> Location``。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from build123d import Location, Plane, Pos, Rot

from .params import Config


# =============================================================================
#  1. 开发板在全局坐标里的姿态
# =============================================================================

def board_location(cfg: Config) -> Location:
    """
    把 ``esp32s3cam-*.step`` 的局部坐标搬到全局坐标。

    坐标变换映射（**必须写全并逆向验算**，DESIGN_NOTES §7.1）::

        局部 +Xs (PCB 长边, 0→40)  -> 全局 -Z   （Xs 增大 = 向下，光轴侧朝上）
        局部 +Ys (板厚, 摄像头侧)  -> 全局 -Y   （摄像头朝 -Y 看向反射镜）
        局部 +Zs (PCB 短边, 0→27)  -> 全局 -X

        全局 X = axis_zs        - Zs
        全局 Y = (lens_face_y + lens_face_ys) - Ys
        全局 Z = (mirror_z + axis_xs)         - Xs

    逆向验算（把三条映射代回去）：

    * Zs = axis_zs (13.51)  -> X = 0        ✓ 光轴在 X=0
    * Ys = lens_face_ys     -> Y = 80       ✓ 镜头前端面落在光学基准面
    * Xs = axis_xs (8.91)   -> Z = 42       ✓ 光轴落在镜面高度

    行列式检查：三条映射构成的矩阵行列式必须是 **+1**（纯旋转）。
    ``det[ex→(0,0,-1), ey→(0,-1,0), ez→(-1,0,0)] = +1`` ✓
    如果写成 ``ez→(+1,0,0)``，行列式是 −1 —— 那是**镜像**，
    会把 SD 卡座、排针悄悄挪到另一侧。这个坑很隐蔽，因为板子近似左右对称。
    """
    b, o = cfg.board, cfg.optics
    # Plane(origin, x_dir, z_dir)：局部 ex→x_dir, ez→z_dir, ey→z_dir×x_dir
    return Location(
        Plane(
            origin=(b.axis_zs, o.lens_face_y + b.lens_face_ys, o.mirror_z + b.axis_xs),
            x_dir=(0, 0, -1),
            z_dir=(-1, 0, 0),
        )
    )


# =============================================================================
#  2. 吊舱尺寸链 —— 全部由 BoardSpec 推出来
# =============================================================================

@dataclass(frozen=True)
class PodLayout:
    """吊舱内部各个 Y 基准面。从前（-Y，靠镜面）往后（+Y）排。"""

    pod_y0: float          # 吊舱前外表面
    wall_inner_y: float    # 前壁内表面 = 摄像头方腔的前端
    lens_face_y: float     # 镜头前端面（光学基准，标称值）
    holder_back_y: float   # 摄像头模组方形本体后端面
    cam_pocket_y1: float   # 摄像头方腔后端
    relief_y0: float       # 深级让位槽（SD 卡座 / 排线）前端
    smd_relief_y0: float   # 浅级让位槽（一圈贴片元件）前端
    pcb_face_y: float      # ★ PCB 前表面 = 板卡的唯一 Y 定位基准（止挡面）
    pcb_back_y: float      # PCB 后表面（按实物板厚 1.6 算）
    board_back_y: float    # 板卡最后端（排针尖）
    pod_back_y: float      # 吊舱后外表面

    # 摄像头方腔（决定光轴的 X/Z 重复精度）
    cam_half_x: float
    cam_z0: float
    cam_z1: float

    # 深级让位槽（SD 卡座 / 排线）
    relief_half_x: float
    relief_z0: float
    relief_z1: float

    # 浅级让位槽（贴片元件、引脚焊尾）
    smd_half_x: float
    smd_z0: float
    smd_z1: float

    # PCB 本体在全局的范围
    pcb_half_x: float
    pcb_z0: float
    pcb_z1: float


def pod_layout(cfg: Config) -> PodLayout:
    """
    推导吊舱型腔。判据全部写在注释里。

    结构（沿 +Y 依次）::

        [前壁 3mm, 开 Ø13 镜头孔]
        [摄像头方腔 9.2×9.2 —— 只夹模组本体，光轴由它定位]
        [深级让位槽 —— SD 卡座 + 排线，2.98mm 深，X±8.9]
        [浅级让位槽 —— 一圈贴片元件，2.14mm 深，X±13.4，Z 18.8 以上]
        ┃ ← PCB 前表面止挡（在 Z<18.8 那条干净的下缘带上）
        [主型腔 —— 板卡、天线、驱动板、走线]
        [滑盖]

    止挡面为什么落在**下缘带**而不是四周一圈：前侧贴片元件一直铺到
    X±12.81，而 PCB 只有 ±13.5，两侧根本剩不下台阶；只有 Z<19.36 那一段
    前侧是完全干净的（27 × 8mm），足够做止挡。这条结论是从 STEP 里一格一格
    量出来的，见 `python build.py inspect esp32s3cam-2.step`。
    """
    b, o, c, m = cfg.board, cfg.optics, cfg.case, cfg.mfg

    # ---- Y 方向 ----
    lens_face_y = o.lens_face_y                                   # 80.0（光学基准）
    wall_inner_y = lens_face_y - c.board_float_y                  # 79.5
    pod_y0 = wall_inner_y - c.pod_front_wall                      # 76.5
    # PCB 前表面：镜头前端面往后 lens_to_pcb_face（8.07）
    pcb_face_y = lens_face_y + b.lens_to_pcb_face                 # 88.07
    pcb_back_y = pcb_face_y + b.pcb_t_real                        # 89.67（用实物板厚）
    # 摄像头模组方形本体的后端面
    holder_back_y = lens_face_y + (b.lens_face_ys - b.holder_back_ys)   # 86.03
    cam_pocket_y1 = holder_back_y + c.cam_pocket_clr
    # 两级让位槽最靠前的元件
    relief_y0 = lens_face_y + (b.lens_face_ys - b.front_deep_ys) - c.front_relief_clr
    smd_relief_y0 = lens_face_y + (b.lens_face_ys - b.front_smd_ys) - c.front_relief_clr
    # 板卡最后端（排针尖）：PCB 后表面 + 背面最高元件伸出量
    board_back_y = pcb_back_y + b.back_depth                      # ≈ 98.7

    # ---- X / Z 方向：把 STEP 局部包络换算到全局 ----
    #  全局 X = axis_zs - Zs      全局 Z = (mirror_z + axis_xs) - Xs
    def gz(xs: float) -> float:
        return o.mirror_z + b.axis_xs - xs

    def gx(zs: float) -> float:
        return b.axis_zs - zs

    cam_half = b.holder_sq / 2 + c.cam_pocket_clr                 # ±4.60
    cam_z0 = o.mirror_z - cam_half
    cam_z1 = o.mirror_z + cam_half

    def envelope(zs_range, xs_range):
        x0, x1 = sorted((gx(zs_range[0]), gx(zs_range[1])))
        z0, z1 = sorted((gz(xs_range[0]), gz(xs_range[1])))
        return (max(abs(x0), abs(x1)) + c.front_relief_clr,
                z0 - c.front_relief_clr, z1 + c.front_relief_clr)

    relief_half_x, relief_z0, relief_z1 = envelope(b.front_deep_zs, b.front_deep_xs)
    smd_half_x, smd_z0, smd_z1 = envelope(b.front_smd_zs, b.front_smd_xs)

    pcb_z0, pcb_z1 = sorted((gz(b.pcb_x[0]), gz(b.pcb_x[1])))     # 10.91 .. 50.91

    return PodLayout(
        pod_y0=pod_y0,
        wall_inner_y=wall_inner_y,
        lens_face_y=lens_face_y,
        holder_back_y=holder_back_y,
        cam_pocket_y1=cam_pocket_y1,
        relief_y0=relief_y0,
        smd_relief_y0=smd_relief_y0,
        pcb_face_y=pcb_face_y,
        pcb_back_y=pcb_back_y,
        board_back_y=board_back_y,
        pod_back_y=c.pod_back_y,
        cam_half_x=cam_half,
        cam_z0=cam_z0,
        cam_z1=cam_z1,
        relief_half_x=relief_half_x,
        relief_z0=relief_z0,
        relief_z1=relief_z1,
        smd_half_x=smd_half_x,
        smd_z0=smd_z0,
        smd_z1=smd_z1,
        pcb_half_x=b.pcb_w / 2,
        pcb_z0=pcb_z0,
        pcb_z1=pcb_z1,
    )


# =============================================================================
#  3. 反射镜姿态
# =============================================================================

def mirror_frame(cfg: Config) -> Location:
    """
    45° 反射面的局部坐标系。原点落在**反射面中心**。

    坐标变换映射::

        局部 +Z -> 全局 (0, +0.7071, -0.7071)   反射面法线，朝前下方
        局部 +X -> 全局 (+1, 0, 0)              托板宽度方向
        局部 +Y -> 全局 (0, -0.7071, -0.7071)   沿斜面向后下（= 镜片滑入方向的反向）

    逆向验算：入射光沿 +Z 上行，反射后应当沿 +Y 前行。
    ``d_out = d_in − 2(d_in·n)n``，代入 ``d_in=(0,0,1)``、``n=(0,1,−1)/√2``：
    ``d_in·n = −1/√2`` → ``d_out = (0,0,1) + (0,1,−1) = (0,1,0)`` ✓
    """
    yc = cfg.optics.mirror_center_y
    return Pos(0, yc, cfg.optics.mirror_z + yc) * Rot(-135, 0, 0)


def mirror_plane_z(cfg: Config, y: float) -> float:
    """45° 镜面在给定 Y 处的高度：``z = y + mirror_z``。托台核算专用。"""
    return y + cfg.optics.mirror_z


# =============================================================================
#  4. LED 姿态
# =============================================================================

def led_frame(cfg: Config) -> Location:
    """
    +X 侧 LED 的局部坐标系（−X 侧由 :func:`geometry.mirror_x` 生成）。

    * 原点 = 灯珠**法兰底面**中心（和 ``led.step`` 的原点一致，可直接乘上去）
    * 局部 +Z = 出射方向 = 从灯珠顶点指向表盘中心
    * 局部 +X = 在 XZ 平面内与 +Z 垂直、朝"外上方"（灯座切边的参考方向）

    映射推导::

        顶点 P = (pos_r, 0, pos_z) = (38, 0, 30)
        出射方向 e = normalize(O − P) = (−0.785, 0, −0.620)
        法兰底面 = P − body_h·e = (41.77, 0, 32.98)
    """
    lg = cfg.light
    px, pz = lg.pos_r, lg.pos_z
    norm = math.hypot(px, pz)
    ex, ez = -px / norm, -pz / norm                  # 出射方向（指向原点）
    ox, oz = px - lg.body_h * ex, pz - lg.body_h * ez  # 法兰底面中心
    # x_dir 与 z_dir 垂直，取 XZ 平面内的法向（-ez, 0, ex）
    return Location(Plane(origin=(ox, 0.0, oz), x_dir=(-ez, 0.0, ex), z_dir=(ex, 0.0, ez)))


def led_tip(cfg: Config) -> tuple[float, float, float]:
    """灯珠顶点（发光中心的几何代表）在全局坐标里的位置。"""
    return (cfg.light.pos_r, 0.0, cfg.light.pos_z)


def led_grazing_height(cfg: Config, radius: float) -> float:
    """
    LED 射向表盘中心的光线，越过半径 ``radius`` 处时距离表盘面的高度。

    判据式子（DESIGN_NOTES §7.7：错误的手算曾经推翻过一个正确方案，
    所以式子必须写出来）::

        光线从 (R, z_led) 直线走到 (0, 0)，参数化后
        z(ρ) = z_led · ρ / R

    在银圈内缘 ρ = dial_r 处，若 z(ρ) > glass_depth，说明光能照进井里。
    """
    lg = cfg.light
    return lg.pos_z * radius / lg.pos_r


def led_incidence_deg(cfg: Config, radius: float = 0.0) -> float:
    """
    LED 光线打到表盘上距中心 ``radius``（沿 LED 方位）处的入射角（自法线算）。
    入射角越大，镜面反射瓣越偏离采集锥，高光越少。
    """
    lg = cfg.light
    dx = lg.pos_r - radius
    return math.degrees(math.atan2(abs(dx), lg.pos_z)) if lg.pos_z else 90.0
