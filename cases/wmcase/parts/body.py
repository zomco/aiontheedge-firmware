# -*- coding: utf-8 -*-
"""
主体 ``body`` —— 抱箍 + 撑座 + 立板 + LED 座 + 镜托台 + 吊臂 + 吊舱。

**它必须是单一连通实体。** 这是第一条自检，也是历史上最高频的错误来源
（DESIGN_NOTES §7.8：v0.5~v1.0 连续多版"零件全部悬空"，每次都靠人看渲染
才发现，因为 CAD 对不相接的实体一样能编译通过）。

建模顺序（**刻意分成三段，不要打乱**）
--------------------------------------
1. :func:`_additions`  —— 所有"加料"，包括吊舱外壳毛坯
2. :func:`_subtractions` —— 所有"去料"，最后一次性减掉
3. :func:`_inner_features` —— 型腔挖好之后才能长出来的内部特征
   （板卡承台、导轨、天线框）

为什么这么分：吊臂在吊舱端会伸进主型腔，如果先挖腔再并吊臂，
腔里会留下一坨实心料，正好挡在板卡旁边——这种错误在渲染图上几乎看不见。
统一"先加后减"就从流程上消灭了它。
"""

from __future__ import annotations

import math

from build123d import Align, Axis, Box, Cylinder, Part, Plane, Pos, Rectangle, Rot, loft

from ..geometry import (
    bx,
    cyl_x,
    cyl_y,
    cyl_z,
    flatted_cylinder,
    mirror_x,
    safe_fillet,
    teardrop_z,
    yz_plate,
)
from ..layout import led_frame, pod_layout
from ..params import Config


# =============================================================================
#  1. 抱箍 —— 整机唯一的机械接口
# =============================================================================

def collar_bore_r(cfg: Config) -> float:
    """光孔半径 = 银圈半径 + 单边间隙（便于套入）。"""
    return cfg.meter.bezel_od / 2 + cfg.case.collar_bore_gap        # 41.40


def collar_rib_r(cfg: Config) -> float:
    """内棱内切半径 = 银圈半径 − 单边过盈（真正咬住的地方）。"""
    return cfg.meter.bezel_od / 2 - cfg.case.collar_rib_interf      # 40.85


def collar_top_z(cfg: Config) -> float:
    """抱箍的实际顶面 = 银圈顶面 + 座圈厚度。夹持带顶 ``collar_z1`` 比它更低。"""
    return cfg.meter.bezel_top_z + cfg.case.collar_seat_t


def build_seat_gap(cfg: Config) -> Part:
    """
    座圈在**墙侧**的让位口（去料）。

    让位口只切掉**向内伸的那圈沿**（和光孔同径以内），抱箍的外壁保持完整 ——
    外壁是抗弯的主要截面，不能为了让位在上沿开个大缺口。

    为什么必须开：
    * 蓝盖的**铰链凸耳**就长在 y≈−28、比固定环顶面高的位置，半径没量过。
      一圈完整的沿只要碰上它，整机就架在凸耳上而不是银圈上 —— 那就把
      "统一高度基准"这个唯一目的直接毁掉了，而且从外面完全看不出来。
    * 有了口，装配时蓝盖**开着也能**把整机套下去，不必强制"先合盖"。
    """
    import math as _m

    from build123d import Plane, Polyline, extrude, make_face

    c, mf, mt = cfg.case, cfg.mfg, cfg.meter
    if c.collar_seat_gap_deg <= 0.0:
        #  盖板已拆除 → 不开口，座圈是完整一圈。
        #  ⚠ 不能让半角 0 走下面那段 —— 扇形会退化成一条线，
        #    Polyline 上出现重复点，OCC 直接抛 BRep_API: command not done。
        #    **"把参数调到 0 就自动关掉这个特征"必须显式写出来**，
        #    指望退化几何自己消失，等来的是崩溃而不是空集。
        return Part()
    z0 = mt.bezel_top_z - mf.eps
    z1 = collar_top_z(cfg) + mf.eps
    r = c.collar_or + 5.0
    a0, a1 = -90.0 - c.collar_seat_gap_deg, -90.0 + c.collar_seat_gap_deg
    pts = [(0.0, 0.0)]
    for i in range(17):
        a = _m.radians(a0 + (a1 - a0) * i / 16)
        pts.append((r * _m.cos(a), r * _m.sin(a)))
    wedge = extrude(Plane.XY.offset(z0) * make_face(Polyline(*pts, close=True)),
                    amount=z1 - z0)
    return wedge & cyl_z(0, 0, z0, z1, 2 * collar_bore_r(cfg))


def build_collar(cfg: Config) -> Part:
    """
    抱箍：光孔 + N 条内棱过盈 + **座圈** + 剖分缝 + 双 M4 夹紧 + 备用径向顶紧孔。

    为什么是"大孔 + 内棱"而不是"小孔直接过盈"
    ------------------------------------------
    v2.3 用的是"内孔比银圈大一点，靠拧缝夹紧"，结果尺寸链不闭合：
    直径间隙 2.4mm，而剖分缝只有 2.2mm，缝完全闭合内孔也只缩小
    ``2.2/π = 0.70mm``，永远碰不到银圈（DESIGN_NOTES §7.3）。

    现在：光孔单边留 +0.35 便于套入，但 16 条半圆内棱单边**过盈 0.25**。
    只有棱尖接触，局部压强高十几倍，既好装又抗转。

    座圈（内沿圆环）—— 本轮新增，解决"每台装出来高度都不一样"
    ----------------------------------------------------------
    内棱只管**转**和**掉**，管不了**高度**：往下压多少全靠手感。
    而镜片托板的高度直接决定光程和 ROI 标定，40 台各压各的等于 40 套标定。

    所以在银圈顶面那一层长一圈向内的沿，压到沿贴住银圈顶面为止。
    **接触面是银圈的顶面（一个真实的、平的、和表盘平行的加工面）**，
    从此整机的 Z 基准和表盘刚性关联，不再和拧螺栓的力气有关。

    径向厚度受一条硬约束：不能超过银圈自己的径向厚度，否则沿会探进
    表盘上方 —— 那里下面是空的（蓝色固定环只有 Ø61.8），既没支承又挡光。
    自检 DIM-12 盯着。
    """
    c, m, f = cfg.case, cfg.mfg, cfg.fast
    mt = cfg.meter
    z0, z1 = c.collar_z0, c.collar_z1
    ztop = collar_top_z(cfg)
    eps = m.eps

    ring = cyl_z(0, 0, z0, ztop, 2 * c.collar_or)
    # 夹紧耳分居剖分缝两侧；用 mirror_x 保证严格对称
    ear = bx(c.collar_slit_w / 2, c.collar_slit_w / 2 + c.collar_ear_w,
             c.collar_or - 6, c.collar_or + 14, z0, ztop)
    solid = ring + mirror_x(ear)

    # ---- 去料 ----
    #  光孔只开到**银圈顶面**；再往上内孔收到 collar_seat_ir，收出来的那圈
    #  就是座圈。两个减法体在 Z 上刻意重叠 eps —— 只相切会留退化边（TOPO-04）。
    solid -= cyl_z(0, 0, z0 - eps, mt.bezel_top_z, 2 * collar_bore_r(cfg))
    solid -= cyl_z(0, 0, mt.bezel_top_z - eps, ztop + eps, 2 * c.collar_seat_ir)
    solid -= build_seat_gap(cfg)                                         # 墙侧让位口
    solid -= bx(-c.collar_slit_w / 2, c.collar_slit_w / 2,               # 剖分缝
                collar_bore_r(cfg) - 10, c.collar_or + 16, z0 - eps, ztop + eps)
    for bz in c.collar_bolt_z:                                           # 两颗 M4
        solid -= cyl_x(-30, 30, c.collar_or + 8, bz, f.m4_clearance)
    set_hole = Rot(0, 0, c.collar_set_ang) * cyl_y(
        0, c.collar_or - 12, c.collar_or + 2, (z0 + z1) / 2, f.set_screw_d)
    solid -= mirror_x(set_hole)                                          # 备用顶紧孔
    solid -= build_nut_pockets(cfg)                                      # 六角螺母沉槽

    # ---- 内棱 ----
    # 落在剖分缝里的棱会被切成孤立薄片（自检 TOPO-01 立刻报 solids>1）。
    # 与其等自检报错，不如在这里就跳过它们。
    rib_r = collar_bore_r(cfg)
    ribs = Part()
    for i in range(c.collar_rib_n):
        ang = i * 360.0 / c.collar_rib_n
        rx = rib_r * math.cos(math.radians(ang))
        ry = rib_r * math.sin(math.radians(ang))
        if ry > 0 and abs(rx) < c.collar_slit_w / 2 + c.collar_rib_d:
            continue
        ribs += Rot(0, 0, ang) * cyl_z(rib_r, 0, z0, z1, c.collar_rib_d)
    return solid + ribs


def build_nut_pockets(cfg: Config) -> Part:
    """
    夹紧螺栓的**六角螺母沉槽**（去料），只开在 −X 那只夹紧耳的外表面。

    没有沉槽的话，拧螺栓时必须一手扳手按住螺母、一手拧螺丝 —— 而现场是
    站在楼梯上、单手扶着整机。沉槽让螺母被"抓死"，变成单手作业。

    两个细节都不是随手定的：

    * **只开一侧。** 螺栓头在 +X 耳、螺母在 −X 耳，左右不对称是有意的。
      所以这个减法体**不能**走 mirror_x。
    * **六边形要有一个顶点朝全局 +Y。** 推荐打印姿态是主体绕 X 轴 +90°，
      全局 +Y 就是打印时的"上"。顶点朝上 → 孔顶自然收成尖角，零支撑；
      平边朝上的话孔顶是一条 7.2mm 的水平桥，会塌。
    """
    from build123d import Plane, RegularPolygon, extrude

    c, f, m = cfg.case, cfg.fast, cfg.mfg
    af = f.m4_nut_af + 2 * f.nut_pocket_clr          # 对边 7.4
    circum = af / math.sqrt(3.0)                     # 外接圆半径
    depth = f.m4_nut_thick + 0.4
    x_out = -(c.collar_slit_w / 2 + c.collar_ear_w)  # −X 耳的外表面

    pockets = Part()
    for bz in c.collar_bolt_z:
        # Plane.YZ 的局部 x→全局 Y、局部 y→全局 Z，所以 rotation=0 时
        # 第一个顶点落在局部 +x = 全局 +Y ✓（= 打印姿态的正上方）
        sk = Plane.YZ.offset(x_out - m.eps) * Pos(c.collar_or + 8, bz) *             RegularPolygon(circum, 6, rotation=0)
        pockets += extrude(sk, amount=depth + m.eps)
    return pockets


# =============================================================================
#  2. 撑座与立板
# =============================================================================

def build_buttress_half(cfg: Config) -> Part:
    """
    抱箍 → 立板 的过渡撑座（+X 半边）。

    用 loft 从抱箍里的一小块长成立板截面，侧壁约 64°，自支撑
    （dfam_rules §1：悬垂 ≤45° 免支撑）。它同时也是抗弯的加强结构，
    符合"功能特征代支撑"。
    """
    c = cfg.case
    s_bottom = (Plane.XY.offset(c.collar_z0)
                * Pos((c.mast_inner_x + 45) / 2, 0) * Rectangle(2.5, 20))
    s_top = (Plane.XY.offset(c.buttress_top_z)
             * Pos((c.mast_inner_x + c.mast_outer_x) / 2, -3)
             * Rectangle(c.mast_t, 50))
    return loft([s_bottom, s_top])


def build_mast_half(cfg: Config) -> Part:
    """立板（+X 半边）：一块 7mm 厚的 YZ 板，外轮廓由 ``mast_profile`` 给出。"""
    c = cfg.case
    return yz_plate(c.mast_profile, cfg.mfg.fillet_out, c.mast_t, c.mast_inner_x)


# =============================================================================
#  3. LED 座 —— 带极性防呆切边
# =============================================================================

#: 灯座凸台前端面在 LED 局部坐标里的高度（法兰底面为 0，+Z = 出射方向）。
#: 灯珠总高 4.8、法兰厚 1.0，穹顶最宽的那个圆在 +3.2。
#: ★ 2.0 → 1.2：灯珠降到 z=17 之后出射更掠，凸台 Ø12 的**前缘**开始切穹顶
#:   下半边的光（LED-01 从 2.4% 升到 4.4%，LED-02 体积法报 94mm³）。
#:   凸台前端收到 1.2（刚好盖住 1.0 厚的法兰），穹顶露出 3.6mm，光型重新放开。
#:   **凸台是用来"扶住法兰"的，不是用来"包住灯珠"的** —— 多包的每一毫米
#:   都直接从光型里扣。
LED_BOSS_FRONT_Z = 1.2
#: 座孔往立板里钻的深度（自法兰底面算）
LED_SEAT_DEPTH = 5.0


def build_led_boss_half(cfg: Config) -> Part:
    """
    灯座凸台（+X 半边）：沿 LED 轴的一段 Ø12 圆柱，尾端埋进立板。

    灯珠顶点定在 ``(pos_r, 0, pos_z) = (38, 0, 30)``，法兰底面因此落在
    ``(41.77, 0, 32.98)``——正好贴着立板内侧面（X=42.5）。
    所以这里**不需要长长的悬臂灯座**，一个略微凸出内侧面的凸台就够了；
    凸台尾端（局部 z = −7）落在 X≈47.3，稳稳埋在立板里（42.5~49.5）。
    """
    lg = cfg.light
    loc = led_frame(cfg)
    z_back = LED_BOSS_FRONT_Z - lg.boss_l
    return (loc * Pos(0, 0, z_back)
            * Cylinder(lg.boss_d / 2, lg.boss_l,
                       align=(Align.CENTER, Align.CENTER, Align.MIN)))


def build_led_cut_half(cfg: Config) -> Part:
    """
    灯座的去料（+X 半边）：**带切边的座孔** + 引线过孔。

    防呆机制
    --------
    真实草帽灯的法兰上有一条切边标记阴极（``led.step`` 实测：
    法兰 Ø5.8，切边距轴心 2.4）。这里把座孔也做出同样的切边，
    灯珠**只能按唯一姿态压进去**——不靠标识、不靠说明书，靠形状。
    自检 POKA-03 会把灯珠绕自身轴转 180° 再算一次干涉来验证这一点。

    座孔开口必须**不低于**凸台前端面，否则前面会留一圈 Ø12 的料把灯珠挡住。
    这类"差 0.75mm 就装不进去"的错误在渲染图上看不出来，所以这里写死了
    ``LED_BOSS_FRONT_Z + 0.5`` 的关系，而不是各写各的数。
    """
    lg = cfg.light
    loc = led_frame(cfg)
    seat_d = lg.flange_d + 2 * lg.bore_clr                # Ø6.2
    seat_open_z = LED_BOSS_FRONT_Z + 0.5                  # 开口略高于凸台前端
    seat_len = seat_open_z + LED_SEAT_DEPTH
    # Rot(180,0,0)：把局部 +Z 翻成"往立板里钻"的方向；+X 不变，所以切边方位不受影响
    seat = flatted_cylinder(
        loc * Pos(0, 0, seat_open_z) * Rot(180, 0, 0),
        d=seat_d, length=seat_len,
        flat_at=lg.flange_flat + lg.bore_clr,
        flat_angle_deg=180.0,
    )
    # 引线过孔：沿灯轴再往里 1mm，破进立板内侧面的走线槽（自检 WIRE-01）。
    # 再深就会从立板**外**表面钻出去（自检 WIRE-04 会报），所以刻意做短。
    lead_len = LED_SEAT_DEPTH + lg.lead_bore_ext
    lead = (loc * Pos(0, 0, -lead_len)
            * Cylinder(lg.lead_bore_d / 2, lead_len + 1.0,
                       align=(Align.CENTER, Align.CENTER, Align.MIN)))
    return seat + lead


# =============================================================================
#  4. 镜托台 + 定位销（防呆：前后销径不同）
# =============================================================================

def build_pad_half(cfg: Config, y_range, z_top: float, pin_d: float) -> Part:
    """
    一级镜托台（+X 半边）+ 它的定位销。

    **最关键的约束**（v2.3 实物在这里翻车，DESIGN_NOTES §7.5）：
    托台顶面是**水平**的，托板底面是 **45° 斜面** ``z = y + mirror_z``。
    在托台的 Y 范围内，托板底面从 ``y0+42`` 升到 ``y1+42``，
    **托台顶面必须低于该段的最低点**（``y0 + mirror_z``），
    否则一端顶死、一端悬空，托板根本放不平。

    判据写进了自检 CONS-04/05，参数是 ``pad_clear``。
    """
    c = cfg.case
    y0, y1 = y_range
    # loft：从立板里的窄截面长成伸向内侧的托台，侧面自支撑
    s_top = (Plane.XY.offset(z_top)
             * Pos((c.pad_inner_x + c.mast_outer_x) / 2, (y0 + y1) / 2)
             * Rectangle(c.mast_outer_x - c.pad_inner_x, y1 - y0))
    s_bot = (Plane.XY.offset(z_top - c.pad_drop)
             * Pos((c.mast_inner_x + c.mast_outer_x) / 2, (y0 + y1) / 2)
             * Rectangle(c.mast_t, y1 - y0))
    pad = loft([s_bot, s_top])
    # 竖直定位销：零支撑打印；前后销**直径不同**，托板前后装反就插不进去
    pin = cyl_z(c.pin_x, (y0 + y1) / 2, z_top - 0.5, z_top + c.pin_h, pin_d)
    return pad + pin


# =============================================================================
#  5. 吊臂 —— 下开口 U 型槽
# =============================================================================

def build_arm_half(cfg: Config, hollow: bool = False) -> Part:
    """
    吊臂（+X 半边）。``hollow=True`` 返回的是要减掉的 U 型腔。

    一个结构同时满足三件事：

    * **走线**：LED 线从立板走到吊舱，全程内藏，外表面看不到线；
    * **DfAM**：dfam_rules 禁止大块实心；
    * **力学**：同样重量下 U 型截面的比刚度高于实心杆。

    腔是**下开口**的（顶部靠 ≤4mm 桥接自封），所以打印时不需要支撑，
    线也能从下方塞进去。

    **为什么是三段而不是一根斜杆**：直杆会从立板顶部一路斜插到吊舱，
    正好横穿镜片托板每月抽出时扫过的空间（自检 SEQ-02 报出 1053mm³ 干涉）。
    现在先贴着立板那一侧（X≈46）平着前伸，越过托板的抽出范围之后
    再收进来、降下去 —— 托板整个在 X≤38，和第一段根本不共面。
    """
    c = cfg.case
    p = pod_layout(cfg)
    w = c.arm_channel_w if hollow else c.mast_t
    h = c.arm_channel_h if hollow else c.arm_h
    dz = -cfg.mfg.eps if hollow else 0.0
    # Plane.XZ 的法线是 −Y，所以 offset(−d) 表示 y = +d
    s_mast = (Plane.XZ.offset(-c.arm_mast_y)
              * Pos(c.arm_mast_x, c.arm_mast_z + h / 2 + dz) * Rectangle(w, h))
    s_mid = (Plane.XZ.offset(-c.arm_mid_y)
             * Pos(c.arm_mast_x, c.arm_mid_z + h / 2 + dz) * Rectangle(w, h))
    pod_x = c.arm_channel_pod_x if hollow else c.arm_pod_x
    s_pod = (Plane.XZ.offset(-(p.pcb_face_y + 4))
             * Pos(pod_x, h / 2 + dz) * Rectangle(w, h))
    # ruled=True：段与段之间走直线，不要样条鼓包——鼓出来的部分正好又伸回托板路径
    return loft([s_mast, s_mid, s_pod], ruled=True)


def build_wire_groove_half(cfg: Config) -> Part:
    """
    立板内侧面的走线槽（+X 半边，去料）。

    全部开在**内侧面**，外表面保持干净。竖槽刻意做得比 LED 座孔更长，
    保证座孔一定破进槽里——"引线通道连通"这件事由自检 WIRE-01
    用布尔连通性来验证，而不是靠看图。
    """
    c, lg = cfg.case, cfg.light
    x0, x1 = c.mast_inner_x - cfg.mfg.eps, c.mast_inner_x + 2.6
    # 竖槽下沿跟着 LED 高度走 —— 写死数字的话，一改灯珠高度槽就接不上座孔了
    # （实测：LED 从 z=30 降到 20 之后，WIRE-01 立刻报"2 个连通域"）
    groove = bx(x0, x1, -2.4, 2.4, lg.pos_z - 4.0, c.arm_mast_z + 8.0)
    groove += bx(x0, x1, -2.4, c.arm_mast_y + 2.0,      # 横槽（去吊臂）
                 c.arm_mast_z + 2.0, c.arm_mast_z + 6.0)
    return groove


# =============================================================================
#  6. 吊舱
# =============================================================================

def build_pod_blank(cfg: Config) -> Part:
    """吊舱毛坯（还没挖腔）：圆角长方体。"""
    c, p = cfg.case, pod_layout(cfg)
    pod = bx(-c.pod_half_x, c.pod_half_x, p.pod_y0, c.pod_back_y, c.pod_z0, c.pod_z1)
    return safe_fillet(pod, pod.edges().filter_by(Axis.Y), cfg.mfg.fillet_out)


def build_pod_cuts(cfg: Config) -> Part:
    """
    吊舱的全部去料。**这是整个设计里尺寸链最长的一段**，
    所有 Y 基准都来自 :func:`layout.pod_layout`，不许在这里现算。

    从前往后::

        [前壁]  开 Ø13 镜头孔 + Ø20×1.2 偏振片沉孔（外侧）
        [方腔]  9.2×9.2，只夹摄像头模组本体 → 光轴的 X/Z 由它决定
        [让位]  排线 / SD 卡座的让位槽，比方腔宽但仍窄于 PCB
        ┃ PCB 前表面止挡（三面台阶）
        [主腔]  贯通到吊舱后表面（**必须贯通**，否则打印要架桥）
        [滑槽]  切进两侧壁，顶部开口供滑盖插入
    """
    c, m, p = cfg.case, cfg.mfg, pod_layout(cfg)
    eps = m.eps
    cuts = Part()

    # ---- 镜头孔 + 偏振片沉孔 ----
    cuts += cyl_y(0, p.pod_y0 - eps, p.wall_inner_y + eps, cfg.optics.mirror_z, c.lens_bore_d)
    cuts += cyl_y(0, p.pod_y0 - eps, p.pod_y0 + c.polarizer_depth,
                  cfg.optics.mirror_z, c.polarizer_d)

    # ---- 摄像头方腔（带入口导向倒角，盲装时好对准）----
    #  方腔在 Z 上要留出板卡的**抬升行程**（见 board_lift）：板卡是抬高
    #  board_lift 水平推入、再落下 board_lift 就位的，模组也跟着上下走。
    cam = bx(-p.cam_half_x, p.cam_half_x, p.wall_inner_y - eps, p.cam_pocket_y1,
             p.cam_z0, p.cam_z1 + c.board_lift)
    lead = c.cam_pocket_lead_in
    cam += bx(-(p.cam_half_x + lead), p.cam_half_x + lead,
              p.cam_pocket_y1 - lead, p.cam_pocket_y1 + eps,
              p.cam_z0 - lead, p.cam_z1 + c.board_lift)
    cuts += cam

    # ---- 两级让位槽 ----
    #  深级：SD 卡座 + 摄像头排线（伸出 PCB 约 2.98mm，集中在中间）
    cuts += bx(-p.relief_half_x, p.relief_half_x, p.relief_y0, p.pcb_face_y + eps,
               p.relief_z0, p.relief_z1 + c.board_lift)
    #  浅级：一圈贴片元件和引脚焊尾（只伸出 2.14mm，但一直铺到 X±13.4）
    #  它把止挡面挤到了 PCB 下缘那条干净的带上 —— 见 layout.pod_layout 的说明
    #  两级让位槽的上边界都要加上 board_lift：板卡抬高推入时，
    #  SD 卡座和排线也跟着抬高，让位槽得容得下那段行程。
    cuts += bx(-p.smd_half_x, p.smd_half_x, p.smd_relief_y0, p.pcb_face_y + eps,
               p.smd_z0, p.smd_z1 + c.board_lift)

    # ---- 主型腔：从 PCB 前表面一直通到吊舱后表面 ----
    #   为什么必须贯通：推荐打印姿态是主体绕 X 轴 −90°（+Y 朝上），
    #   若后端封死，就会出现 34×66mm 的大平顶悬空，远超 15mm 桥接上限。
    cuts += bx(-c.cav_half_x, c.cav_half_x, p.pcb_face_y, c.pod_back_y + eps,
               c.cav_z0, c.cav_z1)

    # ---- 弹性卡钩的**变形空间**（切进两侧壁）----
    #  悬臂外表面在 X=15.5，型腔壁在 17.0 —— 只有 1.5mm，而卡钩要让 1.5mm，
    #  正好顶死。**"做了弹性件"不等于"它让得开"**，必须显式把让位空间挖出来。
    #  自检 CONS-18 会核算 (相当于) 侧壁到悬臂外表面的距离 > 需要的变形量。
    _rib_in, _rib_out = board_rail_x(cfg)
    cuts += mirror_x(bx(c.cav_half_x - eps, c.cav_half_x + c.board_arm_relief,
                        p.pcb_back_y, p.pcb_back_y + c.board_hook_ramp_y + 1.5,
                        board_arm_z0(cfg) - 3.0, p.pcb_z1 + c.board_tab_gap + 3.0))

    # ---- 滑盖 C 型槽：切进两侧壁，上方开口 ----
    cuts += bx(-c.cover_groove_x, c.cover_groove_x,
               c.cover_y0 - m.fit_slide, c.cover_lip_y,
               c.cav_z0, c.pod_z1 + 8)

    # ---- 底部总进线孔（水滴形，尖角朝 +Y = 打印姿态的"上"）----
    cuts += teardrop_z(0, c.pod_back_y - 16, c.pod_z0 - eps, c.cav_z0 + eps,
                       c.power_hole_d, tip_dir=(0, 1))

    # ---- 吊臂 → 吊舱 的走线过孔（保证线能从 U 型腔进电子舱）----
    #  用方孔而不是圆孔，而且**刻意和 U 型腔的末端有 3mm 体积重叠**：
    #  两个减法体只在一个平面上相切的话，布尔会留下退化边，
    #  STEP 依然合法但 3MF 网格化会失败。宁可多切一点，也不要相切。
    pass_through = bx(c.cav_half_x - 3, c.pod_half_x + eps,
                      p.pcb_face_y + 1, p.pcb_face_y + 7, 2.0, 8.0)
    cuts += mirror_x(pass_through)

    return cuts


def board_rail_x(cfg: Config) -> tuple[float, float]:
    """侧向导轨（也是弹性悬臂）的 X 范围。"""
    p, c = pod_layout(cfg), cfg.case
    rib_in = p.pcb_half_x + c.board_rib_clear
    return rib_in, rib_in + c.board_rib_t


def board_arm_z0(cfg: Config) -> float:
    """弹性悬臂的**根部** Z（= 下段刚性导轨的顶面）。悬臂自由长度自此往上算。"""
    p, c = pod_layout(cfg), cfg.case
    return p.pcb_z1 - c.board_arm_len


def build_board_rail_half(cfg: Config) -> Part:
    """
    +X 侧的**刚性**段：侧向导轨 + 下缘后压唇。

    导轨只做到悬臂根部为止 —— 再往上如果还有整面墙，悬臂就被墙背着，
    在 X 方向根本弹不动。**"做了一个悬臂"和"这个悬臂能动"是两件事**，
    后者要靠把周围的料清干净来保证（自检 CONS-18 用应变公式反查）。
    """
    c, p = cfg.case, pod_layout(cfg)
    rib_in, rib_out = board_rail_x(cfg)
    lip_y0 = p.pcb_back_y + c.board_slot_clr
    lip_y1 = lip_y0 + c.board_lip_t
    rail = bx(rib_in, rib_out, p.pcb_face_y, lip_y1 + 0.5,
              p.pcb_z0, board_arm_z0(cfg))
    #  压唇从导轨内伸出来盖住 PCB 下缘后角；X 一直画到 rib_out
    #  （和导轨**整段重叠**，不是擦边 0.01mm）—— 只相切会留退化边。
    lip_in = p.pcb_half_x - c.board_lip_overlap
    rail += bx(lip_in, rib_out, lip_y0, lip_y1,
               p.pcb_z0, p.pcb_z0 + c.board_lift - 0.3)
    return rail


def build_board_catch_half(cfg: Config) -> Part:
    """
    +X 侧的**弹性**卡钩：一根沿 Z 向上的悬臂，头上带两个特征。

    ::

        z = pcb_z1 + gap + 2  ┬  ┌──┐ ← 顶部压舌：盖住 PCB 上缘，锁 +Z
        z = pcb_z1 + gap      ┤  └──┘   （间隙 gap 就是板卡能上抬的全部行程）
        z = pcb_z1            ┬  ┌──┐ ← 卡钩：顶住 PCB 后表面，锁 +Y（= 抗 pitch）
        z = board_hook_z0     ┤  └──┘   （只能落在背面无元件的那 2mm 里）
                              │  │  │
                              │  │  │ ← 悬臂，厚 board_arm_t，朝 +X 弹
        z = arm_z0            ┴  └──┘ ← 根部，接在下段刚性导轨上

    两个特征都带**沿 Y 的导入斜面**：板卡从 +Y 推进来时先顶到斜面，
    把悬臂顶开，推到底再弹回去。斜面做成 loft，一次成型不用倒角。

    为什么两个特征的过盈量不一样（钩 1.5 / 舌 0.9）：它们共用一根悬臂，
    让开的量由**大的那个**决定；小的那个必须在整个推入过程中都被带着让开，
    所以它的斜面得比钩子的更靠前、过盈更小。这一条由 CONS-18 的
    "推入路径上任一点的过盈体积 ≤ 名义值" 兜底。
    """
    from build123d import Plane, Rectangle, loft

    c, p = cfg.case, pod_layout(cfg)
    rib_in, rib_out = board_rail_x(cfg)
    lip_y0 = p.pcb_back_y + c.board_slot_clr
    arm_y1 = lip_y0 + c.board_hook_ramp_y
    hz0, hz1 = c.board_hook_z0, p.pcb_z1
    tab_z0 = p.pcb_z1 + c.board_tab_gap
    tab_z1 = tab_z0 + c.board_tab_h
    z_root = board_arm_z0(cfg)

    # 悬臂本体：刻意从根部再往下伸 1.5mm，和刚性导轨**体积重叠**而不是相切
    arm = bx(rib_in, rib_out, lip_y0, arm_y1, z_root - 1.5, tab_z1)

    def ramp(x_in: float, y_front: float, y_back: float, z0: float, z1: float) -> Part:
        """从 (x_in @ y_front) 斜到 (rib_in @ y_back) 的楔形，即导入斜面 + 卡台。"""
        s_f = (Plane.XZ.offset(-y_front) * Pos((x_in + rib_out) / 2, (z0 + z1) / 2)
               * Rectangle(rib_out - x_in, z1 - z0))
        s_b = (Plane.XZ.offset(-y_back) * Pos((rib_in + rib_out) / 2, (z0 + z1) / 2)
               * Rectangle(rib_out - rib_in, z1 - z0))
        return loft([s_f, s_b], ruled=True)

    # 卡钩（锁 +Y）
    arm += ramp(p.pcb_half_x - c.board_hook_overlap, lip_y0, arm_y1, hz0, hz1)
    # 顶部压舌（锁 +Z）：往前一直伸到 PCB 前表面附近才盖得住上缘。
    #  前段是**满过盈的平段**（不是从头斜到尾）：斜面越长，同一段 Y 上的
    #  有效盖住量越小，反向判据（CONS-17 抬起必须被挡）量到的体积就越接近
    #  布尔噪声。**防呆/约束类特征要留一段"实打实"的平面，别做成纯楔形。**
    tab_in = p.pcb_half_x - c.board_tab_overlap
    tab_y0 = p.pcb_face_y + 0.3
    tab_y1 = lip_y0 + 0.3                       # 平段末端（已伸到 PCB 后方）
    arm += bx(tab_in, rib_out, tab_y0, tab_y1, tab_z0, tab_z1)
    arm += ramp(tab_in, tab_y1 - 0.4, tab_y1 + 1.3, tab_z0, tab_z1)
    return arm


def build_pod_inner_features(cfg: Config) -> Part:
    """
    型腔挖好之后才能长出来的内部特征：板卡承台、侧向导轨、天线框。

    板卡的六个自由度是这样锁住的（自检 CONS-07~09 / 14~18 逐条验证）::

        −Y  摄像头方腔的前端面 + 前壁台阶
        +Y  下缘后压唇（底部） + 上端弹性卡钩（顶部）← 两点，所以 pitch 也锁住了
        ±X  两条侧向导轨夹住 PCB 边（间隙 0.4）
        −Z  板下缘落在承台上
        +Z  顶部压舌，间隙只留 board_tab_gap
        绕 X（pitch）  上下两点的 +Y 约束
        绕 Y / Z       导轨 + 承台

    ★ 上一版的 +Y 只有底部一点、+Z 完全没有约束，靠的是"重力 + 泡棉摩擦"。
      实物结论：一摇就掉。**"重力 + 摩擦"不是约束，写进自由度表里就是自欺欺人。**
      EVA 泡棉现在退化成减振垫，不再承担定位职责。
    """
    c, p = cfg.case, pod_layout(cfg)
    feat = Part()

    # ---- 板下缘承台 ----
    #  半宽取 pcb_half_x − 0.5，是为了和压唇（内缘 pcb_half_x − board_lip_overlap）
    #  有 0.5mm 的**体积重叠**。两者刚好相切的话会留下退化边，
    #  STEP 照样合法但 3MF 网格化直接失败（自检 TOPO-04 抓到过一次）。
    shelf_x = p.pcb_half_x - 0.5
    feat += bx(-shelf_x, shelf_x, p.pcb_face_y, p.pcb_face_y + c.board_shelf_len,
               p.pcb_z0 - c.board_shelf_t, p.pcb_z0)

    # ---- 侧向导轨 + 下缘后压唇 + **上端弹性卡钩**（板卡的 +Y / +Z 固定）----
    #  下缘压唇只做在 Z pcb_z0 ~ pcb_z0+board_lift 那一小段：板卡是抬高
    #  board_lift 水平推入、再落下就位的，压唇落在别处都会挡住水平推入。
    #  落下之后它扣住 PCB 的下缘后角。
    #
    #  ⚠ 上一版**只有**这个压唇，实物一摇板子还是会从 pitch 方向倒出来。
    #    原因见 params.Case 里那条几何定理：可上抬行程恒 ≥ 抬升行程 > 压唇高度，
    #    板一抬到顶压唇就脱开，上端又完全自由。刚性件解决不了，必须上弹性件。
    feat += mirror_x(build_board_rail_half(cfg))
    feat += mirror_x(build_board_catch_half(cfg))

    # ---- 天线定位框（贴 +X 内壁，馈点朝上）----
    fx1 = c.cav_half_x
    fx0 = fx1 - 1.5
    frame = bx(fx0, fx1, c.ant_y0, c.ant_y0 + c.ant_w + 3,
               c.cav_z1 - 3 - c.ant_l, c.cav_z1)
    frame -= bx(fx0 - cfg.mfg.eps, fx1 + cfg.mfg.eps,
                c.ant_y0 + 1.5, c.ant_y0 + 1.5 + c.ant_w,
                c.cav_z1 - 1.5 - c.ant_l, c.cav_z1 - 1.5)
    feat += frame

    # ---- 滑盖防呆定位筋（只在 +X 侧，且**紧贴槽底**）----
    #  盖板 +X 舌片的**最下面一段**是收窄的，正装时这条筋刚好落进收窄段。
    #  为什么必须贴着槽底：盖板是从上往下滑进来的，筋放在中段的话，
    #  舌片的满宽部分下滑时一定会先撞上它 —— 正装也装不进去。
    #  贴着槽底就只有舌片最下面那 10mm 会经过筋所在的高度。
    #  上下颠倒 → 收窄段跑到顶部且换到 −X 侧；前后调头 → 收窄段换到 −X 侧。
    #  两种装反都会让满宽舌片撞上筋（自检 POKA-02）。
    feat += bx(c.cover_groove_x - c.cover_key_depth, c.cover_groove_x,
               c.cover_y0 - 0.1, c.cover_y1 + 0.1,
               c.cav_z0, c.cav_z0 + c.cover_key_len)
    return feat


# =============================================================================
#  7. 装配成主体
# =============================================================================

def _additions(cfg: Config) -> Part:
    half = (build_buttress_half(cfg)
            + build_mast_half(cfg)
            + build_led_boss_half(cfg)
            + build_pad_half(cfg, cfg.case.pad_rear_y, cfg.case.pad_rear_z,
                             cfg.case.pin_d_rear)
            + build_pad_half(cfg, cfg.case.pad_front_y, cfg.case.pad_front_z,
                             cfg.case.pin_d_front)
            + build_arm_half(cfg, hollow=False))
    return build_collar(cfg) + mirror_x(half) + build_pod_blank(cfg)


def _subtractions(cfg: Config) -> Part:
    half = (build_led_cut_half(cfg)
            + build_wire_groove_half(cfg)
            + build_arm_half(cfg, hollow=True))
    return mirror_x(half) + build_pod_cuts(cfg)


def build_body(cfg: Config) -> Part:
    """主体总装：**先加，再减，最后长内部特征**（顺序不要打乱，理由见模块头）。"""
    body = _additions(cfg) - _subtractions(cfg)
    return body + build_pod_inner_features(cfg)
