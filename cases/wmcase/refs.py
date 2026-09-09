# -*- coding: utf-8 -*-
"""
参考件模型 —— 我们**不生产**、但设计必须绕开的东西。

三种可信度，代码里严格区分（这一条是硬规矩）：

===============  ===========================================================
``AUTHORITATIVE``  厂家 STEP，尺寸可信 → **可以**作为自检的判定依据
``MOCK``           我们按卡尺实测数据参数化搭的替身 → **可以**判定
``ILLUSTRATIVE``   形似但尺寸不对的模型 → **只能**看，不许进判定
===============  ===========================================================

第三类目前只有 ``watermeter-dn25.step``：它的表盘外观和 LXSY-15E2 很像，
但那是 **DN25**，实测用表是 **DN15**。放进装配体供人眼检视没问题，
拿它算干涉就是自欺欺人。:func:`meter_mock` 才是判定用的水表模型。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from build123d import Box, Cylinder, Location, Part, Pos, Rot, import_step

from .geometry import bx, cyl_x, cyl_z, mirror_x
from .layout import board_location, led_frame, mirror_frame
from .params import Config

AUTHORITATIVE = "authoritative"
MOCK = "mock"
ILLUSTRATIVE = "illustrative"


@dataclass
class RefModel:
    """一个参考件：形体 + 它有多可信 + 从哪来。"""

    name: str
    shape: Part
    trust: str
    source: str

    @property
    def usable_for_checks(self) -> bool:
        return self.trust in (AUTHORITATIVE, MOCK)


# =============================================================================
#  STEP 载入（带缓存，STEP 解析很贵）
# =============================================================================

def _refs_root(cfg: Config) -> str:
    """参考模型目录（默认就是 ``cases/`` 本身）。"""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.normpath(os.path.join(here, cfg.refs_dir))


@lru_cache(maxsize=8)
def _load_step(path: str):
    return import_step(path)


def load_step(cfg: Config, filename: str):
    """载入 ``cases/`` 下的一个 STEP。找不到返回 None（调用方负责降级）。"""
    path = os.path.join(_refs_root(cfg), filename)
    if not os.path.isfile(path):
        return None
    return _load_step(path)


@lru_cache(maxsize=8)
def _fused(path: str) -> Part:
    """
    把 STEP 里成百上千个零散实体**熔成一个** Part。

    ⚠ 这一步不是优化，是**正确性**问题。``import_step`` 返回的嵌套 Compound
    直接参与布尔运算时，OCC 会静默地返回空集：``body & board`` 恒等于 0，
    于是所有关于开发板的干涉检查全部"通过"——这是最危险的一类假阴性，
    因为它长得和"设计没问题"一模一样。

    发现它的过程：CONS-07/08/09（板卡三个方向的约束）同时报 0 干涉。
    三条独立的检查同时给出同一个可疑答案，基本可以断定是工具问题而不是设计问题。
    """
    shp = _load_step(path)
    return Part() + shp.solids()


def load_step_fused(cfg: Config, filename: str) -> Part | None:
    """载入并熔合。**任何要参与布尔运算的 STEP 都必须走这里。**"""
    path = os.path.join(_refs_root(cfg), filename)
    if not os.path.isfile(path):
        return None
    return _fused(path)


# =============================================================================
#  开发板
# =============================================================================

def board(cfg: Config) -> RefModel:
    """
    ESP32-S3-CAM 开发板，已摆到全局坐标里。

    姿态由 :func:`layout.board_location` 给出，**不做任何自动对齐**——
    自动对齐（比如"把包围盒中心搬到某处"）看起来省事，但它会掩盖
    "这块板和 BoardSpec 对不上"这件事。宁可硬编码变换 + 自检核对包络。
    """
    shp = load_step_fused(cfg, cfg.board.step_file)
    if shp is None:
        return RefModel(
            name="board",
            shape=board_mock(cfg),
            trust=MOCK,
            source=f"参数替身（找不到 {cfg.board.step_file}）",
        )
    return RefModel(
        name="board",
        shape=board_location(cfg) * shp,
        trust=AUTHORITATIVE,
        source=cfg.board.step_file,
    )


def board_mock(cfg: Config) -> Part:
    """
    没有 STEP 时的兜底替身：只有 PCB + 摄像头模组 + 背面包络三块。
    刻意做得"方"，因为它的用途是**保守**地占位，不是精确表达。
    """
    from .layout import pod_layout

    p = pod_layout(cfg)
    b = cfg.board
    pcb = bx(-p.pcb_half_x, p.pcb_half_x, p.pcb_face_y, p.pcb_back_y, p.pcb_z0, p.pcb_z1)
    holder = bx(-b.holder_sq / 2, b.holder_sq / 2,
                cfg.optics.lens_face_y, p.holder_back_y,
                cfg.optics.mirror_z - b.holder_sq / 2, cfg.optics.mirror_z + b.holder_sq / 2)
    back = bx(-p.pcb_half_x, p.pcb_half_x, p.pcb_back_y, p.board_back_y,
              p.pcb_z0 + 2, p.pcb_z1 - 2)
    return pcb + holder + back


# =============================================================================
#  LED（5mm 草帽白光）
# =============================================================================

def led_pair(cfg: Config) -> RefModel:
    """左右两颗 LED，已摆到灯座里。"""
    shp = load_step_fused(cfg, "led.step")
    if shp is None:
        one = led_mock(cfg)
        src = "参数替身（找不到 led.step）"
        trust = MOCK
    else:
        one = led_frame(cfg) * shp
        src = "led.step"
        trust = AUTHORITATIVE
    return RefModel(name="led_pair", shape=mirror_x(Part() + one), trust=trust, source=src)


def led_single(cfg: Config) -> Part:
    """+X 那一颗 LED（含引脚），已摆到灯座里。−X 那颗用 mirror_x 生成。"""
    shp = load_step_fused(cfg, "led.step")
    if shp is None:
        return led_mock(cfg)
    return Part() + (led_frame(cfg) * shp)


def led_bodies(cfg: Config) -> Part:
    """
    只保留灯珠**本体**（法兰 + 穹顶），砍掉 25mm 长引脚。

    干涉判定必须用这个而不是完整模型：引脚是可以随便弯的软线，
    它穿过立板"干涉"了几立方毫米不是设计缺陷；而法兰能不能坐进座孔、
    极性切边对不对得上，才是真问题。
    """
    lg = cfg.light
    loc = led_frame(cfg)
    keep = loc * Pos(0, 0, (lg.body_h + 1.0) / 2 - 0.5) * \
        Box(3 * lg.flange_d, 3 * lg.flange_d, lg.body_h + 1.0)
    return mirror_x(Part() + (led_frame(cfg) * _led_solid(cfg))) & mirror_x(Part() + keep)


def _led_solid(cfg: Config):
    """灯珠在自身局部坐标里的形体（有 STEP 用 STEP，没有就用替身）。"""
    shp = load_step_fused(cfg, "led.step")
    if shp is not None:
        return shp
    lg = cfg.light
    return (Pos(0, 0, lg.flange_h / 2) * Cylinder(lg.flange_d / 2, lg.flange_h)
            + Pos(0, 0, lg.body_h / 2) * Cylinder(lg.body_d / 2, lg.body_h))


def led_mock(cfg: Config) -> Part:
    """按 Lighting 参数搭的灯珠替身：法兰 + 灯体 + 两根引脚。"""
    lg = cfg.light
    loc = led_frame(cfg)
    flange = loc * Pos(0, 0, lg.flange_h / 2) * Cylinder(lg.flange_d / 2, lg.flange_h)
    body = loc * Pos(0, 0, lg.body_h / 2) * Cylinder(lg.body_d / 2, lg.body_h)
    leads = Part()
    for s in (-1, 1):
        leads += (loc * Pos(s * lg.lead_pitch / 2, 0, -lg.lead_len / 2)
                  * Box(lg.lead_sq, lg.lead_sq, lg.lead_len))
    return flange + body + leads


# =============================================================================
#  反射镜（外购前表面镜）
# =============================================================================

def mirror_glass(cfg: Config, slide: float = 0.0, push_out: float = 0.0) -> Part:
    """
    反射镜实体。

    **镀膜面 = 局部 z = 0 的那一面**，也就是 ``layout.mirror_frame`` 的基准平面
    ``z = y + mirror_z``。光线追踪、镜片口径判定全都依赖这个约定，
    改它之前请先读 ``parts/mirror_holder.py`` 顶部关于局部 z 零点的说明。

    :param slide:    沿局部 −Y 滑出的距离（T 型槽的装配方向）
    :param push_out: 沿局部 +Z 向外推的距离（用来验证唇口真的兜得住）
    """
    o = cfg.optics
    z_center = -o.mirror_t / 2 + push_out
    return (mirror_frame(cfg) * Pos(0, slide, z_center)
            * Box(o.mirror_w, o.mirror_l, o.mirror_t))


def mirror_ref(cfg: Config) -> RefModel:
    return RefModel(
        name="mirror_glass",
        shape=mirror_glass(cfg),
        trust=MOCK,
        source=f"外购前表面镜 {cfg.optics.mirror_l:.0f}×{cfg.optics.mirror_w:.0f}"
               f"×{cfg.optics.mirror_t:.0f}",
    )


# =============================================================================
#  水表
# =============================================================================

def meter_mock(cfg: Config) -> RefModel:
    """
    **判定用**的水表替身，由卡尺实测数据 + 样本外形表搭出来：

    * 银圈：外径 82.1 / 内径 61.8 / 高 21.1 的圆环（**抱箍的配合对象**）
    * 底部凸台：宽 9.5 高 2.8 的一圈（夹持带必须避开）
    * 表头壳体 + 中段铸体 + 两端管接：管轴在 z = −57

    早期版本把表体做成一个 165×94×90 的**方块**。方块作为包络是保守的，
    但在装配体里它就是一坨和支架糊在一起的砖 —— 人根本看不出哪是表哪是壳，
    也就失去了"人工审图"这一环的意义。现在换成圆柱组合，看着像水表，
    而"抱箍别撞表体"那条判据（FIT-13）本来就是自己另建保守方块，不受影响。
    """
    m = cfg.meter
    # 银圈（抱箍真正咬住的地方）
    ring = cyl_z(0, 0, m.bezel_bottom_z, m.bezel_top_z, m.bezel_od)
    ring -= cyl_z(0, 0, m.bezel_bottom_z - 1, m.bezel_top_z + 1, m.bezel_id)
    # 银圈底部凸台
    boss = cyl_z(0, 0, m.bezel_bottom_z, m.boss_top_z, m.bezel_od + 2 * m.boss_w)
    boss -= cyl_z(0, 0, m.bezel_bottom_z - 1, m.boss_top_z + 1, m.bezel_od)
    # 蓝色固定环：坐在表盘玻璃面上，高 5mm。它会在表盘外缘投出一圈阴影，
    # 也是蓝盖铰链的落脚点 —— 必须建进判定用的模型里。
    ring = ring + blue_ring(cfg)
    # 表头壳体：从银圈底面接到中段铸体
    housing_bot = m.pipe_axis_z + m.body_casting_d / 2 - 8.0
    housing = cyl_z(0, 0, housing_bot, m.bezel_bottom_z, m.bezel_od)
    # 中段铸体 + 两端管接（沿 X 的圆柱，轴在 z = pipe_axis_z）
    half = m.body_casting_len / 2
    casting = cyl_x(-half, half, 0, m.pipe_axis_z, m.body_casting_d)
    stubs = cyl_x(-m.body_len / 2, m.body_len / 2, 0, m.pipe_axis_z, m.pipe_stub_d)
    return RefModel(name="meter", shape=ring + boss + housing + casting + stubs,
                    trust=MOCK, source=f"{m.model} 卡尺实测 + 样本外形表")


def blue_ring(cfg: Config) -> Part:
    """
    表盘上的**蓝色固定环**：内径 = 可视表盘直径，外径 = 内径 + 2×壁厚，
    坐在玻璃面上高 ``ring_h``。

    它有两个作用，都会影响设计：

    * **挡光**：LED 打向对侧表盘的掠射光要越过它，环会在同侧外缘投下一圈阴影
      （靠对置的另一颗灯补上，自检 LED-05 逐点验证）；
    * **铰链基座**：蓝盖绕它的外缘翻转。
    """
    m = cfg.meter
    ring = cyl_z(0, 0, 0.0, m.ring_h, m.ring_od)
    ring -= cyl_z(0, 0, -1.0, m.ring_h + 1.0, m.dial_visible_d)
    return ring


def blue_cover(cfg: Config, angle_deg: float | None = None) -> Part:
    """
    表盘上的**蓝色盖板**，绕铰链翻开 ``angle_deg``（默认取停放角度）。

    几何约定
    --------
    * 铰链轴沿 **X**，位于固定环外缘的**墙侧**：``(y, z) = (−ring_od/2, ring_h)``
    * 盖板是一块圆片，**铰链在它的边缘上**（所以闭合时正好盖住整个环）
    * ``angle_deg`` 是盖板平面与表盘面的夹角；0° = 闭合，100° = 实测的停放角

    为什么必须朝墙侧（−Y）停放
    --------------------------
    朝房间侧（+Y）翻开的话，盖板会横在相机和 45° 镜之间；
    朝左右翻开会挡住 LED。只有墙侧是空的 —— 但那一侧正是镜片托板伸过去的地方，
    所以两者必然争地盘，`FIT-14` 就是盯这件事的。

    旋转映射（按 DESIGN_NOTES §7.1 的规矩写全并验算）::

        绕 X 轴转 θ：(y, z) → (y·cosθ − z·sinθ,  y·sinθ + z·cosθ)，相对铰链
        闭合时圆心相对铰链在 (0, +cover_r, +cover_t/2)
        θ=100° 代入 → 相对 (0, −5.47−1.48, +31.02−0.26) = (0, −6.95, +30.76)
        绝对圆心 (0, −37.85, +35.76)，盖板远端约 (0, −41.8, +67.0)  ✓ 朝墙侧仰起
    """
    m = cfg.meter
    theta = m.cover_open_deg if angle_deg is None else angle_deg
    hy, hz = m.cover_hinge_y, m.cover_hinge_z
    closed = Pos(0, hy + m.cover_r, hz + m.cover_t / 2) * Cylinder(m.cover_r, m.cover_t)
    return Pos(0, hy, hz) * Rot(theta, 0, 0) * Pos(0, -hy, -hz) * closed


def blue_cover_ref(cfg: Config) -> RefModel:
    m = cfg.meter
    return RefModel(name="blue_cover", shape=blue_cover(cfg), trust=MOCK,
                    source=f"蓝色盖板 R{m.cover_r}×{m.cover_t}，停放角 {m.cover_open_deg:.0f}°"
                           f"（半径/厚度仍是照片目测）")


def meter_illustrative(cfg: Config) -> RefModel | None:
    """
    ``watermeter-dn25.step`` —— 只用于人眼检视，**任何自检都不许引用**。
    它是 DN25，实测用表是 DN15，表头尺寸对不上（银圈 Ø100.87 vs Ø82.1）。

    坐标变换映射（**必须写全并逆向验算**，DESIGN_NOTES §7.1）::

        STEP +Xs (管轴)     -> 全局 +X
        STEP +Ys (竖直向上) -> 全局 +Z      ← 关键：这个 STEP 是"Y 朝上"的
        STEP +Zs (宽度)     -> 全局 −Y

        全局 = Rot(90°, X) 之后再平移 (0, 0, −dn25_bezel_top_ys + bezel_top_z)

    逆向验算：

    * ``(Xs, Ys, Zs) = (0, 104, 0)`` 银圈顶面中心 -> ``(0, 0, 7)`` = 全局银圈顶面 ✓
    * ``Zs = 0`` -> ``Y = 0`` ✓ 表体中面落在 Y=0
    * 行列式：``det[ex→(1,0,0), ey→(0,0,1), ez→(0,−1,0)] = +1``（纯旋转）✓

    **之前这里根本没做变换**，STEP 原样丢进装配体，于是水表横躺在自己的
    坐标系里和支架穿模 —— 装配体渲染图上看起来"融为一体"。
    参考件也必须摆正，否则人工审图这一环就废了。
    """
    shp = load_step(cfg, "watermeter-dn25.step")   # 仅用于装配体展示，不参与布尔
    if shp is None:
        return None
    dz = cfg.meter.bezel_top_z - cfg.meter.dn25_bezel_top_ys
    placed = Pos(0, 0, dz) * Rot(90, 0, 0) * shp
    return RefModel(name="meter_dn25_illustrative", shape=placed, trust=ILLUSTRATIVE,
                    source="watermeter-dn25.step（DN25，银圈 Ø100.87，仅供外观参考；"
                           "它比实测用表大一圈，装配体里会明显穿过抱箍，这是预期的）")
