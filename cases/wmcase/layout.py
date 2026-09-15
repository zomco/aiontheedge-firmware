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
#  2b. 板卡弹性卡钩 —— 装入路径上的"允许过盈"
# =============================================================================

def board_snap_strain(cfg: Config) -> float:
    """
    悬臂根部的最大弯曲应变（无量纲，0.012 = 1.2%）。

    判据式子（悬臂端部位移 δ 的经典解，写出来接受检查）::

        ε = 3 · t · δ / (2 · L²)
        t = 悬臂厚度（变形方向）  δ = 端部位移  L = 自由长度

    PETG 一次性装配的经验上限约 1.6%。超了不会当场断，
    但会留下白化的塑性铰，第二次拆装就断了 —— **一次性卡扣和可拆卸卡扣
    要用不同的应变上限**，本设计属于后者（每月抄表不动它，但换板要拆）。
    """
    c = cfg.case
    return 3.0 * c.board_arm_t * c.board_hook_overlap / (2.0 * c.board_arm_len ** 2)


def board_snap_bound(cfg: Config) -> float:
    """
    两个卡钩在装入路径上的名义过盈体积**上界**（mm³）。

    这是"弹性让位"，不是碰撞 —— 但装配仿真（SEQ-01）是拿布尔体积判碰撞的，
    分不出两者。所以给它一个**由几何算出来**的允许量，而不是随手填一个大数：

    * 卡钩：楔形伸进 PCB 边缘的那一段三角形 × 钩高
    * 压舌：满过盈平段 × PCB 板厚 × 舌高

    ``× 1.5`` 的余量留给数值误差。允许量一旦被算大了，真正的碰撞就会被它盖住，
    所以它必须跟着几何走，**不能是常数**。
    """
    c, p = cfg.case, pod_layout(cfg)
    hook_h = p.pcb_z1 - c.board_hook_z0
    f = c.board_hook_overlap / (c.board_hook_overlap + c.board_rib_clear)
    hook = 0.5 * c.board_hook_overlap * (c.board_hook_ramp_y * f) * hook_h
    tab = c.board_tab_overlap * (cfg.board.pcb_t_real + 0.6) * c.board_tab_h
    return 2.0 * (hook + tab)


def board_snap_allow(cfg: Config) -> float:
    """装配仿真里给板卡那一步的额外容差。"""
    return 1.5 * board_snap_bound(cfg)


# =============================================================================
#  3. 蓝色盖板的停放包络 —— 它决定托板能伸多靠后
# =============================================================================
#
#  这一节是本项目"外部活动件反向约束自家零件"的唯一实例，也是最容易漏的一类
#  尺寸链：蓝盖不是我们的零件，但它翻开之后就是一堵**长期立在那儿的墙**，
#  我们的托板、镜片、乃至相机能看到多大一圈表盘，全被它划死。


def cover_band(cfg: Config, angle_deg: float, worst_case: bool = True
               ) -> tuple[float, float]:
    """
    盖板翻开 ``angle_deg`` 时的两个关键边界：``(最靠房间侧的 Y, 下缘的 Z)``。

    判据式子（写出来接受检查，DESIGN_NOTES §7.7 的规矩）::

        铰链高度 h = cover_hinge_above_ring (+ cover_hinge_tol，最坏情况)
        铰链      (hy, hz) = (−dial_r, ring_h + h)
        闭合时圆心相对铰链  (a, b) = (dial_r, cover_t/2 − h)
        转 θ 后圆心         (hy + a·cosθ − b·sinθ,  hz + a·sinθ + b·cosθ)
        圆片在 Y 上的半宽   cover_r·|cosθ| + (cover_t/2)·|sinθ|
        圆片在 Z 上的半高   cover_r·|sinθ| + (cover_t/2)·|cosθ|

    逆向验算 θ=90°（标称 h=5）：
        max_y = −28.25 + 0 + 3.5 + 0 + 1.5 = −23.25   ✓ 铰链前方 5.0 的那条竖直面
        z_c   = 12.8 + 28.25 + 0 = 41.05，半高 30.9 → 下缘 10.15   ✓

    ``worst_case=True`` 时用 ``h + cover_hinge_tol``：铰链越高，翻开的盖板
    整片越往房间侧挪、下缘也越高。让位量一律按这个算，可视范围则两个都报。
    """
    m = cfg.meter
    h = m.cover_hinge_above_ring + (m.cover_hinge_tol if worst_case else 0.0)
    hy, hz = m.cover_hinge_y, m.ring_h + h
    th = math.radians(angle_deg)
    ct, st = math.cos(th), math.sin(th)
    a, b = m.dial_r, m.cover_t / 2 - h
    yc = hy + a * ct - b * st
    zc = hz + a * st + b * ct
    half_y = m.cover_r * abs(ct) + (m.cover_t / 2) * abs(st)
    half_z = m.cover_r * abs(st) + (m.cover_t / 2) * abs(ct)
    return yc + half_y, zc - half_z


def cover_max_y(cfg: Config, angle_deg: float, worst_case: bool = True) -> float:
    """盖板翻开 ``angle_deg`` 时最靠房间侧的 Y。"""
    return cover_band(cfg, angle_deg, worst_case)[0]


def _park_angles(cfg: Config, n: int = 60):
    lo, hi = cfg.meter.cover_park_range_deg
    return [lo + (hi - lo) * i / n for i in range(n + 1)]


def cover_clear_y(cfg: Config) -> float:
    """
    停放角区间内盖板侵入得**最厉害**的那个 Y。我们的零件必须全部留在它前面。

    扫整个区间而不是只算实测的那一个角度：盖板靠重力/摩擦停住，逐台有差异，
    而这条边界在 90°~105° 之间并不是单调的（90° 时最靠墙，105° 时最靠房间）。
    """
    return max(cover_max_y(cfg, a) for a in _park_angles(cfg))


def holder_rear_cut_y(cfg: Config) -> float:
    """托板后端的**竖直**切面 Y。"""
    return cover_clear_y(cfg) + cfg.case.holder_cover_clear


def holder_top_z(cfg: Config) -> float:
    """
    托板的削平高度。

    ``ceiling_z − holder_lift_clear − holder_top_margin``：
    只要托板整体不超过它，"抬起 8mm 不撞天花板"就是几何上不可能违反的，
    不再依赖有人记得同步调整提手/支承片上的一堆高度常数。
    """
    c, m = cfg.case, cfg.meter
    return m.ceiling_z - c.holder_lift_clear - c.holder_top_margin


# =============================================================================
#  4. 反射镜姿态
# =============================================================================
#
#  镜片的**后缘**由蓝盖倒推，**前缘**由光学要求（ellipse_y[1]）决定，
#  两者之间的距离就是要买多长的镜片。方向不能反过来：
#  先定镜长再摆位置的话，蓝盖那一头永远对不上。


def mirror_y_rear(cfg: Config) -> float:
    """镜片镀膜面的后缘 Y = 托板竖直切面 + 端壁厚度。"""
    return holder_rear_cut_y(cfg) + cfg.case.holder_rear_wall


def mirror_y_front(cfg: Config) -> float:
    """镜片镀膜面的前缘 Y。沿 45° 斜面走 mirror_l，在 Y 上就是 mirror_l/√2。"""
    return mirror_y_rear(cfg) + cfg.optics.mirror_l / math.sqrt(2.0)


def mirror_center_y(cfg: Config) -> float:
    """镜面有效区中心的 Y —— 托板以它为中心排布。"""
    return (mirror_y_rear(cfg) + mirror_y_front(cfg)) / 2.0


def dial_visible_limits(cfg: Config, worst_case: bool = True
                        ) -> tuple[float, float, float]:
    """
    表盘上**还能被相机看到**的最靠墙侧的 Y，以及两个限制各自的贡献。

    返回 ``(生效值, 蓝盖给的限制, 镜片后缘给的限制)``，三个都是负值，
    越接近 0 表示丢得越多。

    ★ 这是本轮新增的一条结论，而且是个**坏消息**，必须写清楚：
      翻开的蓝盖是一堵立在 y ≈ −23 处、从 z≈11 一直到 z≈72 的墙。
      表盘外缘（墙侧）发出的光要上行到虚拟相机，必须穿过这道墙 ——
      除非它能从墙的**下缘**钻过去。于是能不能看见就变成一条不等式：

          光线在 y = y_cover 处的高度   z = path·(1 − |y_cover| / |y0|)
          能看见  ⇔  z < 盖板下缘 z_b
          解出    |y0| < |y_cover| / (1 − z_b/path)

      **不管镜片做多大、相机放多远，这一段表盘都看不见。**
      它是外购活动件的几何后果，不是我们能设计掉的。

    镜片后缘的限制则是可设计的：从表盘点连到虚拟相机的直线必须落在镜面上，

          y_mirror = lens_face_y · y0 / (path + y0)   →   y0 = path·y_m / (lens_face_y − y_m)

    当前两者已经调到大致相当 —— 再加长镜片也换不来可视范围，因为盖板先挡住了。
    """
    o = cfg.optics
    y_m = mirror_y_rear(cfg)
    by_mirror = o.path * y_m / (o.lens_face_y - y_m)
    by_cover = -1e9
    for ang in _park_angles(cfg):
        y_c, z_b = cover_band(cfg, ang, worst_case)
        frac = 1.0 - z_b / o.path
        cand = -abs(y_c) / frac if frac > 1e-6 else -cfg.meter.dial_r
        by_cover = max(by_cover, cand)             # 取最严（最接近 0）
    return max(by_mirror, by_cover), by_cover, by_mirror


def dial_visible_y_min(cfg: Config) -> float:
    """表盘可见区的墙侧边界（最坏情况）。自检 OPT-11 拿它和 OCR 关键要素比。"""
    return dial_visible_limits(cfg)[0]


def cover_bottom_z(cfg: Config) -> float:
    """停放角区间内盖板下缘的**最低**高度（光线要从这下面钻过去）。"""
    return min(cover_band(cfg, a)[1] for a in _park_angles(cfg))


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
    yc = mirror_center_y(cfg)
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
