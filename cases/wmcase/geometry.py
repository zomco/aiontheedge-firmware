# -*- coding: utf-8 -*-
"""
建模辅助 —— 用「起止坐标」而不是「中心 + 对齐」表达实体。

为什么不直接用 build123d 的 ``Box(w, h, d)``
--------------------------------------------
``Box`` 默认以中心对齐，写起来要先算中心再算尺寸，两次算术都可能错，而且
错了之后**看不出来**（形状是对的，只是位置偏了）。本项目历史上多次踩这个坑
（DESIGN_NOTES §7.2：``cube`` 单向生长 + ``s*X`` 乘号导致左右不对称）。

这里的约定：**所有实体都用它在各轴上的起止坐标定义**。
``bx(-10, 10, 0, 5, 2, 8)`` 一眼就能读出它占据哪块空间，也方便和参数表对照。

镜像同理：不要用 ``for s in (-1, 1)`` 手写符号，用 :func:`mirror_x`，
让「左右对称」在语法上成为不可能出错的事。
"""

from __future__ import annotations

import math

from build123d import (
    Align,
    Axis,
    Box,
    Circle,
    Cone,
    Cylinder,
    Location,
    Part,
    Plane,
    Polyline,
    Pos,
    Rot,
    RotationLike,
    extrude,
    fillet,
    make_face,
    make_hull,
    mirror,
)

__all__ = [
    "bx", "cyl_x", "cyl_y", "cyl_z", "cone_along",
    "yz_plate", "mirror_x", "teardrop_z", "flatted_cylinder",
    "wedge_yz", "safe_fillet",
]


# =============================================================================
#  基本体：按起止坐标定义
# =============================================================================

def bx(x0: float, x1: float, y0: float, y1: float, z0: float, z1: float) -> Part:
    """
    由两个对角点定义的长方体。

    参数顺序刻意写成 ``x0,x1, y0,y1, z0,z1``，和「这块料占据 X∈[x0,x1] …」
    的说法一一对应。允许 x0>x1（自动取绝对值），但不建议这么写。
    """
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Box(
        abs(x1 - x0), abs(y1 - y0), abs(z1 - z0)
    )


def cyl_z(x: float, y: float, z0: float, z1: float, d: float) -> Part:
    """轴平行于 +Z 的圆柱，从 z0 长到 z1。"""
    return Pos(x, y, (z0 + z1) / 2) * Cylinder(d / 2, abs(z1 - z0))


def cyl_y(x: float, y0: float, y1: float, z: float, d: float) -> Part:
    """轴平行于 +Y 的圆柱。"""
    return Pos(x, (y0 + y1) / 2, z) * Rot(-90, 0, 0) * Cylinder(d / 2, abs(y1 - y0))


def cyl_x(x0: float, x1: float, y: float, z: float, d: float) -> Part:
    """轴平行于 +X 的圆柱。"""
    return Pos((x0 + x1) / 2, y, z) * Rot(0, 90, 0) * Cylinder(d / 2, abs(x1 - x0))


def cone_along(loc: Location, r0: float, r1: float, length: float) -> Part:
    """
    以 ``loc`` 的局部 +Z 为轴、从局部原点长出去的圆台。
    光锥、LED 出射锥都用它，保证「锥的方向」由一个 Location 说清楚，
    不再靠人脑做旋转复合（DESIGN_NOTES §7.1 的教训）。
    """
    return loc * Cone(r0, r1, length, align=(Align.CENTER, Align.CENTER, Align.MIN))


# =============================================================================
#  截面挤出
# =============================================================================

def yz_plate(points, radius: float, thickness: float, x0: float) -> Part:
    """
    把 (Y, Z) 二维轮廓沿 +X 挤成一块板，起点在 ``x = x0``。

    坐标变换映射（按 DESIGN_NOTES §2 的规定写全）::

        Plane.YZ 局部 (u, v) -> 全局 (x0, u, v)
        法线（挤出方向）      -> 全局 +X

    ``radius > 0`` 时对轮廓所有顶点倒圆角。
    """
    sketch = make_face(Polyline(*[(p[0], p[1]) for p in points], close=True))
    if radius > 0:
        sketch = fillet(sketch.vertices(), radius)
    return Pos(x0, 0, 0) * extrude(Plane.YZ * sketch, amount=thickness)


def wedge_yz(points, thickness: float, x0: float) -> Part:
    """不倒圆角版本的 :func:`yz_plate`，用于会被后续布尔切掉的辅助体。"""
    return yz_plate(points, 0.0, thickness, x0)


# =============================================================================
#  对称
# =============================================================================

def mirror_x(part: Part) -> Part:
    """
    关于 YZ 平面镜像并合并。

    **左右对称的零件一律用它构造**，不要手写 ``for s in (-1, 1)``。
    这样「左右不对称」在语法上就是不可能的（DESIGN_NOTES §7.2）。
    """
    return part + mirror(part, Plane.YZ)


# =============================================================================
#  DfAM 专用特征
# =============================================================================

def teardrop_z(x: float, y: float, z0: float, z1: float, d: float,
               tip_dir: tuple[float, float] = (0.0, 1.0)) -> Part:
    """
    水滴形通孔，轴沿 +Z，尖角朝 ``tip_dir``（XY 平面内的单位方向）。

    为什么要水滴形：推荐打印姿态下这个孔是**水平**的，圆孔顶部会出现
    接近 0° 的悬垂而塌陷。水滴把顶部收成 45° 尖角，零支撑（dfam_rules §1）。
    """
    r = d / 2
    ux, uy = tip_dir
    n = math.hypot(ux, uy) or 1.0
    ux, uy = ux / n, uy / n
    circle = Pos(x, y) * Circle(r)
    tip = Pos(x + ux * 0.707 * d, y + uy * 0.707 * d) * Circle(0.2)
    sketch = make_hull((circle + tip).edges())
    return Pos(0, 0, min(z0, z1)) * extrude(Plane.XY * sketch, amount=abs(z1 - z0))


def flatted_cylinder(loc: Location, d: float, length: float,
                     flat_at: float, flat_angle_deg: float = 180.0) -> Part:
    """
    带一条平边的圆柱 —— 草帽 LED 的**极性防呆孔**。

    真实灯珠的法兰上有一条切边（cathode flat）。把安装孔也做出同样的切边，
    灯珠就只能按唯一姿态压进去，插反了物理上装不下。这是本设计里最"硬"
    的一处防呆：不依赖任何标识，靠形状本身。

    :param loc:             局部坐标系；圆柱沿局部 +Z 从原点长 ``length``
    :param d:               圆柱直径
    :param flat_at:         切边平面到轴心的距离（< d/2 才切得到）
    :param flat_angle_deg:  切边法线在局部 XY 平面内的方位角（0° = 局部 +X）
    """
    body = loc * Cylinder(d / 2, length, align=(Align.CENTER, Align.CENTER, Align.MIN))
    # 半空间：把距离轴心超过 flat_at 的那一侧切掉
    cut = (loc
           * Rot(0, 0, flat_angle_deg)
           * Pos(flat_at + d / 2, 0, length / 2)
           * Box(d, 2 * d, length + 2))
    return body - cut


def safe_fillet(part: Part, edges, radius: float) -> Part:
    """
    倒圆角，失败就原样返回。

    OCC 的 ``fillet`` 在边太短 / 半径过大时会抛异常，而圆角**从来不是**
    功能特征。与其让整条建模链因为一个装饰性圆角崩掉，不如降级并让
    ``checks/dfam.py`` 去报「有尖角没倒」。
    """
    try:
        if not edges:
            return part
        return fillet(edges, radius)
    except Exception:  # noqa: BLE001
        return part
