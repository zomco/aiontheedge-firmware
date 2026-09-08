# -*- coding: utf-8 -*-
"""
光路仿真 —— 把"相机到底看不看得见字轮"从空间想象题变成可计算判据。

两个层次
--------
**层次一：受保护光锥（体积布尔）**
    把光路做成一个实体，任何结构件与它相交 = 遮挡。快，但保守，
    而且说不清"到底是被谁、在哪一点挡住的"。

**层次二：真·光线追踪（本模块的重点）**
    在表盘上撒点，逐条追踪 ``表盘点 → 45°镜 → 镜头``，
    用 OCC 的射线求交找出**第一个**挡住它的实体。
    它能回答体积法回答不了的问题：

    * 镜片实际可用的口径够不够（唇口会吃掉两侧各 2.2mm）
    * 镜头孔 Ø13 会不会渐晕
    * 托板的耳、脚、提手有没有伸进光路
    * 表盘边缘的点在传感器上落在哪 → **整个表盘装不装得下**

虚拟相机
--------
把镜头对 45° 镜面做镜像，得到::

    L  = (0, lens_face_y, mirror_z)
    镜面: z − y = mirror_z,  法线 n = (0, 1, −1)/√2
    L' = (0, 0, mirror_z + lens_face_y)   ← 正悬在表盘中心上方 122mm，垂直向下看

于是"表盘点 P 能否被看到"= "线段 P→L' 与镜面的交点是否落在镜片上，
且 P→交点、交点→L 两段都不被挡"。这个等价关系是本模块全部计算的基础，
它把一个三维折叠问题降成了两段直线求交。

**一次反射会让画面左右镜像。** 固件侧必须知道这件事（AI-on-the-edge
的 ROI 是在镜像后的画面上框的），DESIGN.md §4.6 有说明。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from build123d import Axis, Part, Vector

from .params import Config

__all__ = [
    "TraceResult", "virtual_camera", "mirror_hit_point", "trace_dial_point",
    "sample_dial_points", "sensor_uv", "protected_cone", "led_cone",
    "roi_half_angle_deg", "vfov_deg",
]


# =============================================================================
#  基本量
# =============================================================================

def virtual_camera(cfg: Config) -> Vector:
    """虚拟相机（镜头关于 45° 镜面的镜像）。"""
    return Vector(*cfg.optics.virtual_cam)


def lens_point(cfg: Config) -> Vector:
    """真实镜头入瞳（近似取镜头前端面中心）。"""
    return Vector(0.0, cfg.optics.lens_face_y, cfg.optics.mirror_z)


def vfov_deg(cfg: Config) -> float:
    """垂直视场角。传感器 4:3，判据取**较小**的那个方向，结论才保守。"""
    o = cfg.optics
    return 2 * math.degrees(math.atan(
        math.tan(math.radians(o.hfov_deg / 2)) * o.sensor_px_v / o.sensor_px_h))


def roi_half_angle_deg(cfg: Config) -> float:
    """整个 ROI 从相机看过去的半张角。必须 ≤ min(HFOV, VFOV)/2。"""
    o = cfg.optics
    return math.degrees(math.atan(o.roi_r / o.path))


def mirror_hit_point(cfg: Config, p: Vector) -> Vector:
    """
    表盘点 ``p`` 的光线打在 45° 镜面上的位置。

    直线 P→L' 与平面 ``z − y = mirror_z`` 求交::

        P + t(L' − P) 满足 (Pz + t·ΔZ) − (Py + t·ΔY) = mirror_z
        t = (mirror_z − Pz + Py) / (ΔZ − ΔY)
    """
    v = virtual_camera(cfg)
    d = v - p
    denom = d.Z - d.Y
    t = (cfg.optics.mirror_z - p.Z + p.Y) / denom
    return p + d * t


def sensor_uv(cfg: Config, p: Vector) -> tuple[float, float]:
    """
    表盘点在传感器上的归一化坐标（−1..+1 为画幅半宽/半高）。

    虚拟相机在 ``(0,0,path)`` 垂直向下看，所以::

        u = (x / path) / tan(HFOV/2)
        v = (y / path) / tan(VFOV/2)

    注意 **u 的符号在实拍画面里是反的**（一次反射导致左右镜像），
    这里保留几何符号，镜像的事在文档里交代，不在这里偷偷翻。
    """
    o = cfg.optics
    tan_h = math.tan(math.radians(o.hfov_deg / 2))
    tan_v = math.tan(math.radians(vfov_deg(cfg) / 2))
    dist = o.path - p.Z
    return ((p.X / dist) / tan_h, (p.Y / dist) / tan_v)


# =============================================================================
#  射线追踪
# =============================================================================

@dataclass
class TraceResult:
    """一条光线的完整追踪结果。"""

    dial: Vector                 # 表盘上的出发点
    mirror_point: Vector | None  # 打在镜面上的位置
    ok: bool                     # 全程畅通且落在镜片有效口径内
    blocker: str = ""            # 第一个挡住它的实体名
    block_point: Vector | None = None
    stage: str = ""              # "up"（表盘→镜） / "fold"（没打到镜片） / "out"（镜→镜头）

    @property
    def label(self) -> str:
        if self.ok:
            return "OK"
        if self.stage == "fold":
            return "未落在镜片有效口径内"
        return f"{self.stage} 段被 {self.blocker} 挡住"


def _first_hit(shape: Part, origin: Vector, direction: Vector,
               t_max: float, t_min: float = 0.05) -> tuple[float, Vector] | None:
    """
    射线与实体的第一个交点。

    ``find_intersection_points`` 给的是**整条直线**的交点（包含反向），
    所以必须自己按参数 t 过滤——这一步漏掉的话，相机后方的结构件
    会被误判成遮挡物。
    """
    try:
        hits = shape.find_intersection_points(Axis(tuple(origin), tuple(direction)))
    except Exception:  # noqa: BLE001
        return None
    best = None
    for pt, _normal in hits:
        t = (Vector(pt) - origin).dot(direction)
        if t_min <= t <= t_max and (best is None or t < best[0]):
            best = (t, Vector(pt))
    return best


def trace_dial_point(cfg: Config, blockers: dict[str, Part], mirror: Part,
                     x: float, y: float) -> TraceResult:
    """
    追踪表盘上一点 ``(x, y, 0)`` 到相机的完整光路。

    :param blockers: ``{名字: 实体}``，会挡光的结构件
    :param mirror:   镜片实体（**不是**挡光物，是光路的一部分）
    """
    p = Vector(x, y, 0.0)
    m = mirror_hit_point(cfg, p)

    # ---- 第一段：表盘 → 镜面 ----
    d1 = m - p
    len1 = d1.length
    u1 = d1.normalized()
    for name, shape in blockers.items():
        hit = _first_hit(shape, p, u1, len1 - 0.2)
        if hit:
            return TraceResult(p, m, False, name, hit[1], "up")

    # ---- 折转：这条线是不是真的打在镜片的反射面上 ----
    #   用镜片实体本身来判定，唇口挡住的部分自然就落选了。
    if _first_hit(mirror, p, u1, len1 + 0.5) is None:
        return TraceResult(p, m, False, "mirror_aperture", m, "fold")

    # ---- 第二段：镜面 → 镜头 ----
    lens = lens_point(cfg)
    d2 = lens - m
    len2 = d2.length
    u2 = d2.normalized()
    for name, shape in blockers.items():
        hit = _first_hit(shape, m, u2, len2 - 0.2, t_min=0.2)
        if hit:
            return TraceResult(p, m, False, name, hit[1], "out")

    return TraceResult(p, m, True)


def sample_dial_points(cfg: Config, n_rim: int = 24, n_ring: int = 2
                       ) -> list[tuple[float, float, str]]:
    """
    表盘采样点。刻意不做均匀网格，而是挑**最容易出问题的位置**：

    * 中心（字轮所在）
    * 可视表盘外缘整圈（最外圈指针在这里，也是最容易被井壁/结构挡住的地方）
    * 中间环
    * 四个指针盘的大致位置（LXSY-15E2 表盘布局）

    每个点带一个标签，报告里能直接说"是哪一处被挡了"。
    """
    r = cfg.meter.dial_r
    pts: list[tuple[float, float, str]] = [(0.0, 0.0, "中心")]
    for k in range(n_ring):
        rr = r * (k + 1) / n_ring
        tag = "外缘" if k == n_ring - 1 else f"中环{k + 1}"
        for i in range(n_rim):
            a = 2 * math.pi * i / n_rim
            pts.append((rr * math.cos(a), rr * math.sin(a), tag))
    # 字轮窗口（表盘中上部的一条横带）
    for dx in (-12, -6, 0, 6, 12):
        pts.append((dx, 8.0, "字轮窗"))
    # 四个指针盘（×0.1 / ×0.01 / ×0.001 / ×0.0001），按常见布局取四角
    for dx, dy, nm in ((-14, -8, "指针×0.1"), (14, -8, "指针×0.01"),
                       (-14, -18, "指针×0.001"), (14, -18, "指针×0.0001")):
        pts.append((dx, dy, nm))
    return pts


# =============================================================================
#  受保护光锥（体积法，快速粗筛）
# =============================================================================

def protected_cone(cfg: Config, shrink: float = 1.5) -> Part:
    """
    受保护的光锥实体：任何结构件进入它 = 遮挡。

    ``shrink`` 让锥体略微收缩，避开与"合法终止面"（镜片、镜头孔壁）
    的假阳性。它是**粗筛**，真正定位问题靠 :func:`trace_dial_point`。
    """
    from build123d import Align, Cone, Pos, Rot

    o = cfg.optics
    vert = Pos(0, 0, shrink) * Cone(
        o.roi_r - shrink, o.beam_r_at_mirror - shrink, o.mirror_z - 2 * shrink - 2,
        align=(Align.CENTER, Align.CENTER, Align.MIN))
    horiz = Pos(0, shrink, o.mirror_z) * Rot(-90, 0, 0) * Cone(
        o.beam_r_at_mirror - shrink, 1.0, o.lens_face_y - 2 * shrink,
        align=(Align.CENTER, Align.CENTER, Align.MIN))
    return vert + horiz


def led_cone(cfg: Config) -> Part:
    """
    LED **必需**的出射锥（不是全部 120°，只是覆盖表盘所需的那一份）。

    判据：从灯珠顶点到表盘中心的连线为轴，半角 ``need_half_angle_deg``
    的圆锥不得被结构件挡住。取"必需"而不是"全部"，是因为 120° 的光
    必然打到立板上——那不是缺陷。
    """
    from build123d import Align, Cone, Pos

    from .geometry import mirror_x
    from .layout import led_frame

    lg = cfg.light
    axis_len = math.hypot(lg.pos_r, lg.pos_z)
    r_end = (axis_len - 3) * math.tan(math.radians(lg.need_half_angle_deg))
    cone = (led_frame(cfg) * Pos(0, 0, lg.body_h + 3)
            * Cone(1.0, r_end, axis_len - 4, align=(Align.CENTER, Align.CENTER, Align.MIN)))
    return mirror_x(cone)
