#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===============================================================================
 水表光学抄表装置 — 外壳参数化模型 (build123d)
===============================================================================

 坐标系（贯穿全文，任何时候不要改）
 --------------------------------------------------------------------------
   原点 O  = 水表表盘玻璃面的中心
   +X      = 沿水表体轴线（左右），模型左右对称
   +Y      = 离墙方向（房间一侧），吊舱、滑盖抽出都在这一侧
   +Z      = 垂直向上；上方净空受限，是最紧的约束

 光路
 --------------------------------------------------------------------------
   表盘 --(垂直上行 42mm)--> 45°前表面反射镜 --(水平前行 80mm)--> 镜头
   总光程 122mm，景深容差约 ±11mm，单字符成像约 44px

 打印件
 --------------------------------------------------------------------------
   body          主体：抱箍 + 撑座 + 立板 + LED座 + 镜托台 + 吊臂 + 吊舱
   mirror_holder 镜片托板：45°托板 + 三角耳 + 支承脚（每月抄表时整块提起）
   slide_cover   滑盖：竖直下滑，无螺丝

 用法
 --------------------------------------------------------------------------
   python3 wm_rig.py                      # 校验 + 导出全部
   python3 wm_rig.py --board my.step      # 换一款 ESP32-S3 开发板
   python3 wm_rig.py --check-only         # 只跑校验，不导出
   python3 wm_rig.py --out ./dist         # 指定输出目录
===============================================================================
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
from dataclasses import dataclass, field, replace

from build123d import *  # noqa: F403


# =============================================================================
#  1. 参数区 —— 所有可调尺寸集中在这里
# =============================================================================

@dataclass
class Meter:
    """水表实测尺寸（卡尺测量值，改表型时只改这一段）"""
    bezel_od: float = 82.1      # 银圈外径
    silver_h: float = 21.1      # 银圈高度
    dial_vis: float = 56.5      # 可视表盘直径（蓝圈内径）
    glass_depth: float = 7.0    # 银圈顶面 → 表盘玻璃面 的深度
    ceiling: float = 70.0       # 银圈顶面 → 上方最近障碍（40台取最小值）
    boss_h: float = 2.8         # 银圈底部凸台高度（夹持带必须避开）

    @property
    def silver_top(self) -> float:
        return self.glass_depth                      # +7

    @property
    def silver_bot(self) -> float:
        return self.glass_depth - self.silver_h      # -14.1

    @property
    def boss_top(self) -> float:
        return self.silver_bot + self.boss_h         # -11.3

    @property
    def ceiling_z(self) -> float:
        return self.ceiling + self.glass_depth       # 77

    @property
    def well_r(self) -> float:
        return self.dial_vis / 2                     # 28.25


@dataclass
class Optics:
    """光学参数。改动会连锁影响镜片尺寸与净空，务必看校验输出。"""
    roi_r: float = 29.0         # 需成像半径（覆盖 Ø56.5 表盘 + 余量）
    mirror_z: float = 42.0      # 镜面中心高度 = 镜头光轴高度
    lens_y: float = 80.0        # 镜头前端面的 Y 坐标
    mirror_l: float = 70.0      # ★采购：前表面镜 长（沿45°斜面）
    mirror_w: float = 50.0      # ★采购：前表面镜 宽
    mirror_t: float = 2.0       # ★采购：前表面镜 厚
    hfov_deg: float = 66.0      # OV2640 水平视场角
    sensor_px: int = 1600       # 水平像素

    @property
    def path(self) -> float:
        return self.lens_y + self.mirror_z           # 122

    @property
    def k(self) -> float:
        return self.roi_r / self.path

    @property
    def beam_r_at_mirror(self) -> float:
        """光锥在镜面中心高度处的半径"""
        return self.roi_r - self.k * self.mirror_z   # 19.02

    @property
    def ellipse_y(self) -> tuple[float, float]:
        """45°平面 z=y+mirror_z 与光锥相交椭圆的 Y 向前后端"""
        b = self.beam_r_at_mirror
        return (-b / (1 - self.k), b / (1 + self.k))

    @property
    def y_center(self) -> float:
        y0, y1 = self.ellipse_y
        return (y0 + y1) / 2

    @property
    def need_mirror_len(self) -> float:
        y0, y1 = self.ellipse_y
        return (y1 - y0) * math.sqrt(2)

    @property
    def digit_px(self) -> float:
        """字轮单个数字的成像宽度（表盘上实测约 4.4mm）"""
        fov_w = 2 * self.path * math.tan(math.radians(self.hfov_deg / 2))
        return 4.4 * self.sensor_px / fov_w


@dataclass
class Board:
    """ESP32-S3-CAM 开发板。若提供 STEP，尺寸会被自动覆盖。"""
    w: float = 27.0             # 板宽（装到 X 方向）
    l: float = 40.0             # 板长（装到 Z 方向）
    t: float = 1.6
    lens_to_bot: float = 31.0   # 光轴 → 板下缘
    cam_h: float = 8.0          # 镜头前端面高出板面
    cam_sq: float = 27.0        # 摄像头模组见方
    cam_thk: float = 5.0        # 摄像头模组厚度
    pin_len: float = 10.0       # 排针长度（朝摄像头背面伸出）
    pin_x: float = 11.5         # 两排排针距光轴的 X 偏移
    esp_mod: tuple = (18.0, 3.2, 25.5)   # 背面模块 (X,Y,Z)


@dataclass
class Mfg:
    """制造相关：壁厚、圆角、配合间隙"""
    wall: float = 2.5           # 标准壁厚（0.4喷嘴3道走线）
    fillet: float = 3.0         # 统一外圆角 R3
    fit_clr: float = 0.20       # 静态插接间隙
    eps: float = 0.01           # 布尔微元，杜绝共面
    min_wall: float = 1.6       # 校验用：允许的最薄壁


@dataclass
class Cfg:
    meter: Meter = field(default_factory=Meter)
    opt: Optics = field(default_factory=Optics)
    brd: Board = field(default_factory=Board)
    mfg: Mfg = field(default_factory=Mfg)

    # ---- 抱箍（无衬垫，靠内棱过盈咬住银圈漆面）----
    bore_r: float = 41.40       # 光孔半径：单边 0.35 间隙，便于套入
    rib_r: float = 40.80        # 棱纹内切半径：单边 0.25 过盈
    rib_n: int = 16
    rib_d: float = 1.20
    collar_or: float = 47.60
    grip_z0: float = -10.0      # 夹持带下沿（高于底部凸台顶 -11.3）
    grip_z1: float = 6.5        # 夹持带上沿（低于银圈顶 7）
    slit_w: float = 4.0         # 剖分缝，留弹性行程
    ear_w: float = 9.0
    m4_d: float = 4.4
    m4_z: tuple = (-6.0, 2.5)   # 上下两颗夹紧螺栓
    set_ang: float = 55.0       # 备用径向顶紧螺钉的方位角
    set_d: float = 3.2

    # ---- 立板 ----
    mast_in: float = 42.5
    mast_t: float = 7.0
    but_z1: float = 17.0        # 撑座顶面
    mast_pts: tuple = ((-28, 10), (22, 10), (22, 50), (10, 54), (-14, 48), (-28, 34))

    # ---- LED（5mm 草帽白光 120°）----
    led_r: float = 38.0         # 灯珠头部所在半径
    led_z: float = 30.0         # 灯珠头部高度
    led_bore: float = 5.6
    led_slot: float = 4.2       # 上开口宽 < Ø5 → 压入卡持
    led_boss_d: float = 12.0
    led_boss_l: float = 9.0
    led_half_deg: float = 21.0  # 需要 20.6° 半角覆盖整个表盘

    # ---- 镜托支承（v2.4：整条链退到立板内侧面之内）----
    pad_xi: float = 34.0        # 托台内缘
    pad1_y: tuple = (-20.0, -12.0)
    pad1_z: float = 20.0        # 顶面低于该段托板底面(22) 2mm
    pad2_y: tuple = (10.0, 18.0)
    pad2_z: float = 50.0        # 顶面低于该段托板底面(52) 2mm
    pin_x: float = 38.0
    pin_d: float = 4.0
    pin_h: float = 5.0
    ear_xi: float = 32.0        # 三角耳 X 32~38
    ear_t: float = 6.0
    foot_xi: float = 34.0       # 支承脚 X 34~42（离立板内面 42.5 尚有 0.5）
    foot_xo: float = 42.0
    plate_w: float = 64.0       # 托板宽 ±32
    ear_pts: tuple = ((-22, 20), (18, 60), (18, 68), (-22, 28))

    # ---- 吊舱 ----
    cav_x: float = 17.0
    pod_x: float = 21.5
    pod_z0: float = -11.5
    pod_z1: float = 62.0
    cav_z0: float = -9.0
    cav_z1: float = 57.0
    front_t: float = 3.0
    cav_y1: float = 114.0       # 型腔后端（贯通到吊舱后表面）
    lens_bore: float = 14.0

    # ---- 滑盖（真正的 C 型槽：侧壁槽 + 后压边）----
    sc_y0: float = 109.0        # 盖板前表面
    sc_y1: float = 112.0        # 盖板后表面
    sc_grv_x: float = 19.5      # 槽底 X
    sc_tongue_x: float = 19.3   # 舌片外缘 X
    sc_lip_y: float = 112.2     # 后压边前沿（→ 压边厚 1.8mm）

    # ---- 吊臂（下开口 U 型）----
    arm_h: float = 16.0
    arm_ch_w: float = 2.6
    arm_ch_h: float = 10.0
    arm_pod_x: float = 17.5

    # ---- 天线 / 驱动板 / 线缆 ----
    ant_w: float = 15.0
    ant_l: float = 65.0
    ant_t: float = 0.9
    ant_y0: float = 91.0
    pwr_d: float = 4.5

    # ---- 派生 ----
    @property
    def mast_out(self) -> float:
        return self.mast_in + self.mast_t          # 49.5

    @property
    def brd_y(self) -> float:
        """板前表面 Y = 阶梯止挡面"""
        return self.opt.lens_y + self.brd.cam_h    # 88

    @property
    def brd_z0(self) -> float:
        return self.opt.mirror_z - self.brd.lens_to_bot   # 11

    @property
    def plate_t(self) -> float:
        return self.opt.mirror_t + 0.8 + self.mfg.wall    # 5.3


CFG = Cfg()


# =============================================================================
#  2. 建模辅助 —— 用「起止坐标」而不是「中心+对齐」，从源头消除定位错误
# =============================================================================

def bx(x0, x1, y0, y1, z0, z1) -> Part:
    """由两个对角点定义的长方体。所有实体都用它，避免 align 混淆。"""
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Box(x1 - x0, y1 - y0, z1 - z0)


def cyl_z(x, y, z0, z1, d) -> Part:
    """沿 +Z 的圆柱"""
    return Pos(x, y, (z0 + z1) / 2) * Cylinder(d / 2, z1 - z0)


def cyl_y(x, y0, y1, z, d) -> Part:
    """沿 +Y 的圆柱"""
    return Pos(x, (y0 + y1) / 2, z) * Rot(-90, 0, 0) * Cylinder(d / 2, y1 - y0)


def cyl_x(x0, x1, y, z, d) -> Part:
    """沿 +X 的圆柱"""
    return Pos((x0 + x1) / 2, y, z) * Rot(0, 90, 0) * Cylinder(d / 2, x1 - x0)


def yz_profile(pts, radius, thickness, x0) -> Part:
    """
    把 (Y,Z) 二维轮廓沿 +X 挤出成板。
    Plane.YZ 的局部 x→全局 Y，局部 y→全局 Z，法线→全局 X。
    """
    sk = make_face(Polyline(*[(p[0], p[1]) for p in pts], close=True))
    if radius > 0:
        sk = fillet(sk.vertices(), radius)
    return Pos(x0, 0, 0) * extrude(Plane.YZ * sk, amount=thickness)


def mirror_x(part: Part) -> Part:
    """左右镜像并合并——对称性由语法保证，而不是靠人工记住符号"""
    return part + mirror(part, Plane.YZ)


def mirror_frame(cfg: Cfg) -> Location:
    """
    45°镜面姿态。
      局部 +Z → 全局 (0, +0.707, -0.707)  即反射面法线，朝下偏前
      局部 +X → 全局 +X                    托板宽度方向
      局部 +Y → 全局 (0, -0.707, -0.707)  沿斜面向下向后
    局部原点落在反射面中心。
    """
    yc = cfg.opt.y_center
    return Pos(0, yc, cfg.opt.mirror_z + yc) * Rot(-135, 0, 0)


# =============================================================================
#  3. 主体 body
# =============================================================================

def build_collar(c: Cfg) -> Part:
    """抱箍：光孔 + 16内棱过盈 + 4mm剖分缝 + 双M4 + 备用径向顶紧"""
    z0, z1 = c.grip_z0, c.grip_z1
    e = c.mfg.eps

    ring = cyl_z(0, 0, z0, z1, 2 * c.collar_or)
    # 夹紧耳：分居剖分缝两侧，由 mirror_x 保证对称
    ear = bx(c.slit_w / 2, c.slit_w / 2 + c.ear_w, c.collar_or - 6, c.collar_or + 14, z0, z1)
    solid = ring + mirror_x(ear)

    # 减：光孔 / 剖分缝 / 两颗M4 / 两个备用顶紧孔
    solid -= cyl_z(0, 0, z0 - e, z1 + e, 2 * c.bore_r)
    solid -= bx(-c.slit_w / 2, c.slit_w / 2, c.bore_r - 10, c.collar_or + 16, z0 - e, z1 + e)
    for mz in c.m4_z:
        solid -= cyl_x(-30, 30, c.collar_or + 8, mz, c.m4_d)
    set_hole = Rot(0, 0, c.set_ang) * cyl_y(0, c.collar_or - 12, c.collar_or + 2,
                                            (z0 + z1) / 2, c.set_d)
    solid -= mirror_x(set_hole)

    # 加：内棱（只有棱接触银圈，局部压强高，抗转）
    # 内棱：跳过落在剖分缝内的，否则会被切成孤立薄片（自检 solids>1 会报）
    ribs = Part()
    for i in range(c.rib_n):
        a = i * 360.0 / c.rib_n
        rx = c.bore_r * math.cos(math.radians(a))
        ry = c.bore_r * math.sin(math.radians(a))
        if ry > 0 and abs(rx) < c.slit_w / 2 + c.rib_d:
            continue
        ribs += Rot(0, 0, a) * cyl_z(c.bore_r, 0, z0, z1, c.rib_d)
    return solid + ribs


def build_buttress_half(c: Cfg) -> Part:
    """抱箍 → 立板 的过渡撑座（约 64°，自支撑，DfAM 1.3）"""
    s1 = Plane.XY.offset(c.grip_z0) * Pos((42.5 + 45) / 2, 0) * Rectangle(2.5, 20)
    s2 = Plane.XY.offset(c.but_z1) * Pos((c.mast_in + c.mast_out) / 2, -3) * Rectangle(c.mast_t, 50)
    return loft([s1, s2])


def build_mast_half(c: Cfg) -> Part:
    return yz_profile(c.mast_pts, c.mfg.fillet, c.mast_t, c.mast_in)


def led_axis_loc(c: Cfg) -> Location:
    """LED 局部坐标系：局部 +Z 指向表盘中心，原点在灯珠头部"""
    ang = -(180 - math.degrees(math.atan2(c.led_r, c.led_z)))
    return Pos(c.led_r, 0, c.led_z) * Rot(0, ang, 0)


def build_led_boss_half(c: Cfg) -> Part:
    loc = led_axis_loc(c)
    return loc * Pos(0, 0, -c.led_boss_l / 2 + 1) * Cylinder(c.led_boss_d / 2, c.led_boss_l + 2)


def build_led_cut_half(c: Cfg) -> Part:
    """LED 上开口卡槽：灯珠从开口压入，引线直接落进内侧走线槽"""
    loc = led_axis_loc(c)
    bore = loc * Pos(0, 0, -c.led_boss_l / 2 + 1.5) * Cylinder(c.led_bore / 2, c.led_boss_l + 5)
    slot = loc * Pos(8, 0, -c.led_boss_l / 2 + 1.5) * Box(16, c.led_slot, c.led_boss_l + 5)
    return bore + slot


def build_pad_half(c: Cfg, yr, ztop) -> Part:
    """
    镜托台。v2.4 关键修复：托台可以伸进立板，但托板的支承脚不行。
    顶面必须低于该段托板底面 (z = y + mirror_z) 的最低点。
    """
    s1 = Plane.XY.offset(ztop) * Pos((c.pad_xi + c.mast_out) / 2, (yr[0] + yr[1]) / 2) * \
        Rectangle(c.mast_out - c.pad_xi, yr[1] - yr[0])
    s2 = Plane.XY.offset(ztop - 12) * Pos((c.mast_in + c.mast_out) / 2, (yr[0] + yr[1]) / 2) * \
        Rectangle(c.mast_t, yr[1] - yr[0])
    pad = loft([s2, s1])
    pin = cyl_z(c.pin_x, (yr[0] + yr[1]) / 2, ztop - 0.5, ztop + c.pin_h, c.pin_d)
    return pad + pin


def build_arm_half(c: Cfg, hollow=False) -> Part:
    """下开口 U 型吊臂：走线在型腔内，从下方才看得见"""
    w = c.arm_ch_w if hollow else c.mast_t
    h = c.arm_ch_h if hollow else c.arm_h
    dz = -c.mfg.eps if hollow else 0.0
    s1 = Plane.XZ.offset(-16) * Pos(46, 34 + h / 2 + dz) * Rectangle(w, h)
    s2 = Plane.XZ.offset(-(c.brd_y + 4)) * Pos(c.arm_pod_x, h / 2 + dz) * Rectangle(w, h)
    return loft([s1, s2])


def build_wire_groove_half(c: Cfg) -> Part:
    """走线槽全部在立板内侧面，外表面保持干净"""
    g = bx(c.mast_in - c.mfg.eps, c.mast_in + 2.5, -1.8, 1.8, 34, 44)
    g += bx(c.mast_in - c.mfg.eps, c.mast_in + 2.5, -1.8, 20, 36, 39.6)
    return g


def build_pod(c: Cfg) -> Part:
    """吊舱：圆角长方体 + 阶梯型腔 + 真正的 C 型滑槽"""
    m, e = c.mfg, c.mfg.eps
    pod = bx(-c.pod_x, c.pod_x, c.opt.lens_y, c.cav_y1, c.pod_z0, c.pod_z1)
    pod = fillet(pod.edges().filter_by(Axis.Y), m.fillet)

    # 阶梯型腔前段：容纳 27×27 摄像头模组。高 28 < 板高 40 → 板进不去，天然前止挡
    cam = c.brd.cam_sq
    pod -= bx(-(cam / 2 + 0.4), cam / 2 + 0.4,
              c.opt.lens_y + c.front_t - e, c.brd_y + e,
              c.opt.mirror_z - cam / 2 - 0.5, c.opt.mirror_z + cam / 2 + 0.5)
    # 阶梯型腔后段：贯通到吊舱后表面，滑盖来封闭
    pod -= bx(-c.cav_x, c.cav_x, c.brd_y, c.cav_y1 + e, c.cav_z0, c.cav_z1)
    # 滑槽：切进两侧壁，顶部开口供滑盖插入
    pod -= bx(-c.sc_grv_x, c.sc_grv_x, c.sc_y0 - 0.2, c.sc_lip_y, c.cav_z0, c.pod_z1 + 8)
    # 镜头筒通孔 + 偏振片备用沉孔
    pod -= cyl_y(0, c.opt.lens_y - e, c.opt.lens_y + c.front_t + e, c.opt.mirror_z, c.lens_bore)
    pod -= cyl_y(0, c.opt.lens_y - e, c.opt.lens_y + 1.3, c.opt.mirror_z, 20)
    # 底部总进线孔（水滴形，尖角朝 +Y = 建议打印朝向的"上"）
    pod -= make_teardrop_z(0, c.cav_y1 - 16, c.pod_z0 - e, c.cav_z0 + e, c.pwr_d + 2)

    # 板卡下缘承台（自前壁阶梯挑出，不占用下方电子舱）
    pod += bx(-(cam / 2 + 0.4), cam / 2 + 0.4, c.brd_y, c.brd_y + 5, c.brd_z0 - 2, c.brd_z0)
    # 天线定位框（贴 +X 内壁，馈点朝上）
    fr_x0, fr_x1 = c.cav_x - 1.5, c.cav_x
    frame = bx(fr_x0, fr_x1, c.ant_y0, c.ant_y0 + c.ant_w + 3,
               c.cav_z1 - 3 - c.ant_l, c.cav_z1)
    frame -= bx(fr_x0 - e, fr_x1 + e, c.ant_y0 + 1.5, c.ant_y0 + 1.5 + c.ant_w,
                c.cav_z1 - 1.5 - c.ant_l, c.cav_z1 - 1.5)
    pod += frame
    return pod


def make_teardrop_z(x, y, z0, z1, d) -> Part:
    """水滴孔，轴沿 +Z，尖角朝 +Y"""
    r = d / 2
    circ = Pos(x, y) * Circle(r)
    tip = Pos(x, y + 0.707 * d) * Circle(0.2)
    sk = make_hull((circ + tip).edges())
    return Pos(0, 0, z0) * extrude(Plane.XY * sk, amount=z1 - z0)


def build_body(c: Cfg) -> Part:
    """主体 = 抱箍 + 撑座 + 立板 + LED座 + 托台 + 吊臂 + 吊舱（单一连通实体）"""
    half = build_buttress_half(c) + build_mast_half(c) + build_led_boss_half(c)
    half += build_pad_half(c, c.pad1_y, c.pad1_z) + build_pad_half(c, c.pad2_y, c.pad2_z)
    half += build_arm_half(c, hollow=False)

    body = build_collar(c) + mirror_x(half) + build_pod(c)

    cut = build_led_cut_half(c) + build_wire_groove_half(c) + build_arm_half(c, hollow=True)
    body -= mirror_x(cut)
    return body


# =============================================================================
#  4. 镜片托板 mirror_holder
# =============================================================================

def build_mirror_holder(c: Cfg) -> Part:
    """
    45°托板 + 三角耳 + 支承脚。
    v2.4 关键修复：支承脚 X 34~42，止于立板内侧面(42.5)之前，不再扎进立板。
    """
    o, m = c.opt, c.mfg
    pl = o.mirror_l + 2 * m.wall            # 75
    loc = mirror_frame(c)

    # 托板本体：局部 Z 的 MAX 面就是反射面
    plate = loc * Pos(0, 0, -c.plate_t / 2) * Box(c.plate_w, pl, c.plate_t)
    plate = fillet(plate.edges().filter_by(Axis.X), 2.0)

    half = yz_profile(c.ear_pts, 2.0, c.ear_t, c.ear_xi)
    half += bx(c.foot_xi, c.foot_xo, c.pad1_y[0], c.pad1_y[1], c.pad1_z, c.pad1_z + 12)
    half += bx(c.foot_xi, c.foot_xo, c.pad2_y[0], c.pad2_y[1], c.pad2_z, c.pad2_z + 12)

    holder = plate + mirror_x(half)

    # T 型槽：深部容纳镜片，开口收窄两侧各留唇口，镜面朝下也不会掉
    lip = 2.2
    deep = loc * Pos(0, -pl / 4, -(o.mirror_t + 0.8) / 2 - 0.4) * \
        Box(o.mirror_w + m.fit_clr, o.mirror_l + m.fit_clr + pl / 2, o.mirror_t + 0.2)
    open_ = loc * Pos(0, -pl / 4, -0.4) * \
        Box(o.mirror_w - 2 * lip, o.mirror_l + m.fit_clr + pl / 2, 0.8 + 2 * m.eps)
    holder -= (deep + open_)

    # 定位销孔
    pin_cut = Part()
    for yr, zt in ((c.pad1_y, c.pad1_z), (c.pad2_y, c.pad2_z)):
        pin_cut += cyl_z(c.pin_x, (yr[0] + yr[1]) / 2, zt - m.eps, zt + c.pin_h + 2,
                         c.pin_d + m.fit_clr)
    holder -= mirror_x(pin_cut)
    return holder


def build_mirror_glass(c: Cfg, slide=0.0, out=0.0) -> Part:
    """
    镜片实体（校验与动画用）。
      slide 沿局部 -Y 滑出（T 型槽的装配方向）
      out   沿局部 +Z 外推（校验唇口是否真的挡得住）
    """
    o = c.opt
    return mirror_frame(c) * Pos(0, slide, -(o.mirror_t / 2) - 0.9 + out) * \
        Box(o.mirror_w, o.mirror_l, o.mirror_t)


# =============================================================================
#  5. 滑盖 slide_cover
# =============================================================================

def build_slide_cover(c: Cfg, lift=0.0) -> Part:
    """竖直下滑，无螺丝。舌片被侧壁槽约束 X，被后压边约束 Y。"""
    m = c.mfg
    z0, z1 = c.cav_z0 + 0.5, c.pod_z1
    cov = bx(-c.cav_x, c.cav_x, c.sc_y0, c.sc_y1, z0, z1)
    cov += bx(-c.sc_tongue_x, c.sc_tongue_x, c.sc_y0, c.sc_y1, z0, z1)
    cov = fillet(cov.edges().filter_by(Axis.Y).group_by(Axis.Z)[-1], 1.2)
    # 顶部手指凹槽 + 排料/散热孔（DfAM 2.3）
    cov -= cyl_y(0, c.sc_y0 - m.eps, c.sc_y1 + m.eps, z1, 16)
    for z in range(6, 52, 12):
        cov -= cyl_y(0, c.sc_y0 - m.eps, c.sc_y1 + m.eps, z, 4)
    return Pos(0, 0, lift) * cov


# =============================================================================
#  6. 元器件模型（用于核对吊舱空间；有 STEP 就用 STEP）
# =============================================================================

def build_board_mock(c: Cfg) -> Part:
    """按参数生成的开发板替身（没有 STEP 时使用）"""
    b, o = c.brd, c.opt
    p = bx(-b.w / 2, b.w / 2, c.brd_y, c.brd_y + b.t, c.brd_z0, c.brd_z0 + b.l)
    p += bx(-b.cam_sq / 2, b.cam_sq / 2, c.brd_y - b.cam_thk, c.brd_y,
            o.mirror_z - b.cam_sq / 2, o.mirror_z + b.cam_sq / 2)
    p += cyl_y(0, o.lens_y, o.lens_y + 3, o.mirror_z, 10)
    p += bx(-b.esp_mod[0] / 2, b.esp_mod[0] / 2, c.brd_y + b.t, c.brd_y + b.t + b.esp_mod[1],
            o.mirror_z - b.esp_mod[2] / 2, o.mirror_z + b.esp_mod[2] / 2)
    pin = bx(b.pin_x - 1.3, b.pin_x + 1.3, c.brd_y + b.t, c.brd_y + b.t + b.pin_len,
             c.brd_z0 + 4, c.brd_z0 + b.l - 4)
    return p + mirror_x(pin)


def load_board(c: Cfg, step_path: str | None):
    """
    载入开发板 STEP 并自动对齐到吊舱坐标系。
    对齐规则：把 STEP 的包围盒中心平移到「板前表面 + 光轴高度」的位置。
    ⚠ 不同厂商 STEP 的原点/朝向不一，导入后务必看校验输出里的包围盒。
    """
    if not step_path:
        return build_board_mock(c), "参数替身（未提供 STEP）"
    if not os.path.isfile(step_path):
        print(f"  ! STEP 未找到：{step_path} —— 回退到参数替身")
        return build_board_mock(c), "参数替身（STEP 路径无效）"
    try:
        shp = import_step(step_path)
        bb = shp.bounding_box()
        # 平移：让板的 -Y 面贴到 brd_y，中心对齐 X=0 与光轴高度
        shp = Pos(-bb.center().X, c.brd_y - bb.min.Y, c.opt.mirror_z - bb.center().Z) * shp
        return shp, f"STEP: {os.path.basename(step_path)}  尺寸 " \
                    f"{bb.size.X:.1f}×{bb.size.Y:.1f}×{bb.size.Z:.1f}"
    except Exception as ex:                                    # noqa: BLE001
        print(f"  ! STEP 读取失败（{type(ex).__name__}: {ex}）—— 回退到参数替身")
        return build_board_mock(c), "参数替身（STEP 读取失败）"


# =============================================================================
#  7. 校验套件 —— 目标是让设计错误在这里暴露，而不是在打印件上
# =============================================================================

VOL_TOL = 2.0      # mm³，布尔噪声容差


class Checker:
    def __init__(self):
        self.rows: list[tuple[str, bool, str]] = []

    def add(self, name, ok, detail=""):
        self.rows.append((name, bool(ok), detail))
        return ok

    def report(self) -> bool:
        w = max(len(r[0]) for r in self.rows)
        print("\n" + "=" * (w + 46))
        print("  自检结果")
        print("=" * (w + 46))
        for name, ok, det in self.rows:
            print(f"  [{'PASS' if ok else 'FAIL'}] {name.ljust(w)}  {det}")
        n_fail = sum(1 for _, ok, _ in self.rows if not ok)
        print("=" * (w + 46))
        print(f"  合计 {len(self.rows)} 项，失败 {n_fail} 项")
        print("=" * (w + 46) + "\n")
        return n_fail == 0


def light_cone(c: Cfg, shrink=1.5) -> Part:
    """
    受保护的光锥体：任何结构件进入它 = 遮挡。
    shrink 让锥体略微收缩，避免与合法终止面（镜片、镜头孔）产生假阳性。
    """
    o = c.opt
    vert = Pos(0, 0, shrink) * Cone(o.roi_r - shrink,
                                    o.beam_r_at_mirror - shrink,
                                    o.mirror_z - 2 * shrink - 2,
                                    align=(Align.CENTER, Align.CENTER, Align.MIN))
    horiz = Pos(0, shrink, o.mirror_z) * Rot(-90, 0, 0) * \
        Cone(o.beam_r_at_mirror - shrink, 1.0, o.lens_y - 2 * shrink,
             align=(Align.CENTER, Align.CENTER, Align.MIN))
    return vert + horiz


def led_cone(c: Cfg) -> Part:
    """LED 出射光锥（从灯珠头部前方 3mm 起算，避开灯座自身）"""
    loc = led_axis_loc(c)
    ax = math.hypot(c.led_r, c.led_z)
    r_end = (ax - 3) * math.tan(math.radians(c.led_half_deg))
    cone = loc * Pos(0, 0, 3) * Cone(1.0, r_end, ax - 4,
                                     align=(Align.CENTER, Align.CENTER, Align.MIN))
    return mirror_x(cone)


def vol(p) -> float:
    try:
        return float(p.volume)
    except Exception:                                          # noqa: BLE001
        return 0.0


def inter_vol(a, b) -> float:
    try:
        r = a & b
        return vol(r)
    except Exception:                                          # noqa: BLE001
        return 0.0


def run_checks(c: Cfg, body, holder, cover, glass, board) -> bool:
    ck = Checker()
    m = c.meter

    # --- A. 拓扑：单一连通实体。这条能立刻抓出"零件悬空"这类错误 ---
    for nm, p in (("主体", body), ("镜片托板", holder), ("滑盖", cover)):
        ns = len(p.solids())
        ck.add(f"{nm} 是单一连通实体", ns == 1, f"solids={ns}")
        ck.add(f"{nm} 拓扑有效", p.is_valid, "")

    # --- B. 零件之间不得干涉（Q1：托台曾经扎进托板/立板）---
    v = inter_vol(body, holder)
    ck.add("主体 ∩ 托板 = 0（无干涉）", v < VOL_TOL, f"{v:.2f} mm³")
    v = inter_vol(body, cover)
    ck.add("主体 ∩ 滑盖 = 0（可就位）", v < VOL_TOL, f"{v:.2f} mm³")
    v = inter_vol(holder, glass)
    ck.add("托板 ∩ 镜片 = 0（镜片装得进）", v < VOL_TOL, f"{v:.2f} mm³")

    # --- C. 装拆路径 ---
    v = inter_vol(body, Pos(0, 0, 10) * holder)
    ck.add("托板可垂直提起 10mm 脱离定位销", v < VOL_TOL, f"{v:.2f} mm³")
    v = inter_vol(body, Pos(0, 0, 80) * cover)
    ck.add("滑盖可向上抽出 80mm", v < VOL_TOL, f"{v:.2f} mm³")

    # --- D. 滑盖必须被 Y 向约束（Q3：v2.3 的槽只约束 X，盖板会向后掉出）---
    vf = inter_vol(body, Pos(0, -0.6, 0) * cover)
    vb = inter_vol(body, Pos(0, +0.6, 0) * cover)
    ck.add("滑盖被前沿挡住（-Y 受限）", vf > VOL_TOL, f"{vf:.2f} mm³")
    ck.add("滑盖被后压边挡住（+Y 受限）", vb > VOL_TOL, f"{vb:.2f} mm³")

    # --- D2. 约束有效性：不只是"不干涉"，还要证明确实被托住/挡住 ---
    v = inter_vol(body, Pos(0, 0, -0.5) * holder)
    ck.add("托板确实坐在托台上（非悬空）", v > VOL_TOL, f"下沉0.5mm 干涉 {v:.1f} mm³")
    v = inter_vol(body, Pos(0, 0, -3) * cover)
    ck.add("滑盖到底有限位", v > VOL_TOL, f"下沉3mm 干涉 {v:.1f} mm³")
    v = inter_vol(holder, build_mirror_glass(c, out=1.2))
    ck.add("镜片被 T 型槽唇口挡住（不会掉）", v > VOL_TOL, f"外推1.2mm 干涉 {v:.1f} mm³")

    # --- E. 光路不得被遮挡 ---
    cone = light_cone(c)
    v = inter_vol(cone, body)
    ck.add("主光锥 ∩ 主体 = 0", v < VOL_TOL, f"{v:.2f} mm³")
    v = inter_vol(cone, holder - build_mirror_holder_plate_only(c))
    ck.add("主光锥 ∩ 托板耳脚 = 0", v < VOL_TOL, f"{v:.2f} mm³")
    lc = led_cone(c)
    v = inter_vol(lc, body)
    ck.add("LED 光锥 ∩ 主体 = 0", v < 30.0, f"{v:.2f} mm³（灯座根部允许微量）")

    # --- F. 净空：表盘正上方区域不得超过天花板 ---
    over = (body + holder) & bx(-70, 70, -60, 60, -30, 200)
    zmax = over.bounding_box().max.Z
    ck.add(f"表盘上方最高点 < 天花板 {m.ceiling_z:.0f}", zmax < m.ceiling_z,
           f"zmax={zmax:.1f}")

    # --- G. 整机拆卸：抱箍需抬升 (grip_z1-grip_z0) 才脱离银圈 ---
    lift = c.grip_z1 - c.grip_z0 + 0.5
    over_lift = (body & bx(-70, 70, -60, 60, -30, 200)).bounding_box().max.Z + lift
    ck.add(f"取下托板后整机可抬升 {lift:.1f}mm 拆卸",
           over_lift < m.ceiling_z, f"抬升后 zmax={over_lift:.1f}")

    # --- H. 抱箍过盈量必须为正，否则夹不紧（v2.3 的致命错误）---
    grip = m.bezel_od / 2 - c.rib_r
    ck.add("抱箍内棱对银圈有过盈", 0.10 <= grip <= 0.45, f"单边 {grip:.2f} mm")
    ck.add("夹持带避开银圈底部凸台", c.grip_z0 > m.boss_top,
           f"带底 {c.grip_z0} > 凸台顶 {m.boss_top:.1f}")
    ck.add("夹持带不超过银圈顶面", c.grip_z1 < m.silver_top,
           f"带顶 {c.grip_z1} < 银圈顶 {m.silver_top}")
    ck.add("夹持带高度容得下两颗 M4",
           abs(c.m4_z[1] - c.m4_z[0]) >= 8 and
           min(c.m4_z) > c.grip_z0 + 2 and max(c.m4_z) < c.grip_z1 - 2,
           f"螺栓 z={c.m4_z}，带 {c.grip_z0}~{c.grip_z1}")

    # --- I. 托台顶面必须低于该段托板底面（Q1 根因）---
    for nm, yr, zt in (("后", c.pad1_y, c.pad1_z), ("前", c.pad2_y, c.pad2_z)):
        low = yr[0] + c.opt.mirror_z
        ck.add(f"{nm}托台顶低于该段托板底面", zt <= low - 1.0,
               f"托台 {zt} vs 托板底最低 {low:.0f}")
    ck.add("支承脚止于立板内侧面之前", c.foot_xo < c.mast_in,
           f"脚外缘 {c.foot_xo} < 立板内面 {c.mast_in}")

    # --- J. 光学余量 ---
    o = c.opt
    ck.add("采购镜片长度足够", o.mirror_l >= o.need_mirror_len + 5,
           f"需 {o.need_mirror_len:.1f}，采购 {o.mirror_l}")
    ck.add("单字符成像 ≥ 20px", o.digit_px >= 20, f"{o.digit_px:.1f} px")

    # --- K. 开发板与吊舱的配合 ---
    v = inter_vol(body, board)
    ck.add("开发板 ∩ 主体 = 0（装得进吊舱）", v < VOL_TOL, f"{v:.2f} mm³")
    bb = board.bounding_box()
    ck.add("开发板完全落在型腔内",
           bb.min.X > -c.cav_x and bb.max.X < c.cav_x and
           bb.max.Y < c.sc_y0 and bb.min.Z > c.cav_z0 and bb.max.Z < c.cav_z1,
           f"板bbox X[{bb.min.X:.1f},{bb.max.X:.1f}] "
           f"Y[{bb.min.Y:.1f},{bb.max.Y:.1f}] Z[{bb.min.Z:.1f},{bb.max.Z:.1f}]")

    return ck.report()


def build_mirror_holder_plate_only(c: Cfg) -> Part:
    """只有托板本体（校验时用来把耳脚单独分出来）"""
    pl = c.opt.mirror_l + 2 * c.mfg.wall
    return mirror_frame(c) * Pos(0, 0, -c.plate_t / 2) * Box(c.plate_w + 1, pl + 1, c.plate_t + 1)


# =============================================================================
#  8. 导出
# =============================================================================

def export_all(parts: dict[str, Part], outdir: str):
    os.makedirs(outdir, exist_ok=True)
    for name, p in parts.items():
        sp = os.path.join(outdir, f"{name}.step")
        export_step(p, sp)
        mp = os.path.join(outdir, f"{name}.3mf")
        mesher = Mesher(unit=Unit.MM)
        mesher.add_shape(p, linear_deflection=0.03, angular_deflection=0.15)
        mesher.write(mp)
        print(f"  · {name:<16} STEP {os.path.getsize(sp)//1024:>5} KB   "
              f"3MF {os.path.getsize(mp)//1024:>5} KB   "
              f"体积 {p.volume/1000:.1f} cm³")


# =============================================================================
#  9. 入口
# =============================================================================

def main(argv=None):
    ap = argparse.ArgumentParser(description="水表抄表装置外壳生成器")
    ap.add_argument("--board", default=None, help="ESP32-S3 开发板 STEP 路径")
    ap.add_argument("--out", default="./out", help="输出目录")
    ap.add_argument("--check-only", action="store_true", help="只校验不导出")
    ap.add_argument("--assembly", action="store_true",
                    help="额外导出装配体 STEP（含开发板与镜片，供整体检视）")
    a = ap.parse_args(argv)

    c = CFG
    t0 = time.time()
    print("=" * 70)
    print("  水表光学抄表装置 · 外壳生成")
    print("=" * 70)
    o = c.opt
    print(f"  光程 {o.path:.0f}mm   镜面倾角 45°   单字符 {o.digit_px:.0f}px")
    print(f"  镜片：需 {o.need_mirror_len:.0f}×{2*o.beam_r_at_mirror:.0f}，"
          f"采购 {o.mirror_l:.0f}×{o.mirror_w:.0f}×{o.mirror_t:.0f} 前表面镜")
    print(f"  抱箍：光孔 Ø{2*c.bore_r:.1f}，内棱 Ø{2*c.rib_r:.1f}，"
          f"银圈 Ø{c.meter.bezel_od}，单边过盈 {c.meter.bezel_od/2-c.rib_r:.2f}mm")

    print("\n  建模中 …")
    body = build_body(c)
    holder = build_mirror_holder(c)
    cover = build_slide_cover(c)
    glass = build_mirror_glass(c)
    board, src = load_board(c, a.board)
    print(f"  开发板来源：{src}")
    print(f"  建模耗时 {time.time()-t0:.1f}s")

    ok = run_checks(c, body, holder, cover, glass, board)

    if not a.check_only:
        print("  导出中 …")
        export_all({"body": body, "mirror_holder": holder, "slide_cover": cover}, a.out)
        if a.assembly:
            asm = Compound(children=[
                Part(body.wrapped, label="body"),
                Part(holder.wrapped, label="mirror_holder"),
                Part(cover.wrapped, label="slide_cover"),
                Part(glass.wrapped, label="mirror_glass"),
                Part(board.wrapped, label="esp32_board"),
            ])
            ap_ = os.path.join(a.out, "assembly.step")
            export_step(asm, ap_)
            print(f"  · assembly         STEP {os.path.getsize(ap_)//1024:>5} KB")

    print(f"  总耗时 {time.time()-t0:.1f}s")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
