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

from build123d import Axis, Part, Pos, Vector  # noqa: F401  (Vector 供 checks 直接用)

from .params import Config

__all__ = [
    "TraceResult", "virtual_camera", "mirror_hit_point", "trace_dial_point",
    "sample_dial_points", "ocr_critical_points", "sensor_uv",
    "protected_cone", "led_cone", "useful_led_cone",
    "led_tips", "led_emitter_points", "specular_separation_deg",
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


def led_tips(cfg: Config) -> list[Vector]:
    """两颗灯珠的顶点（左右各一）。"""
    lg = cfg.light
    return [Vector(lg.pos_r, 0.0, lg.pos_z), Vector(-lg.pos_r, 0.0, lg.pos_z)]


def led_emitter_points(cfg: Config, side: int = +1, n_ring: int = 8) -> list[Vector]:
    """
    灯珠**发光面**上的采样点：穹顶顶点 + 穹顶中部一圈。

    为什么不能只取顶点
    ------------------
    草帽灯是个 Ø5 的穹顶，不是点光源。穹顶**上半部分**发出的光线角度更平，
    它们的路径和顶点发出的完全不同。

    实测代价：支承片底边和灯珠顶点等高时，按点光源追踪 **0% 被挡**，
    按真实穹顶取 9 个发光点追踪 **46% 被挡** —— 穹顶上半边整个被遮死。
    这个差别是"检查够不够格"的问题，不是"设计对不对"的问题：
    点光源模型下，无论设计怎么错都查不出来。
    """
    from .layout import led_frame

    lg = cfg.light
    loc = led_frame(cfg)
    mirror = -1 if side < 0 else 1

    def local(x, y, z) -> Vector:
        p = (loc * Pos(x, y, z)).position
        return Vector(mirror * p.X, p.Y, p.Z)

    pts = [local(0.0, 0.0, lg.body_h)]
    r = lg.body_d / 2 - 0.6
    for k in range(n_ring):
        a = 2 * math.pi * k / n_ring
        pts.append(local(r * math.cos(a), r * math.sin(a), lg.body_h - 1.6))
    return pts


def useful_led_cone(cfg: Config) -> "Part":
    """
    LED 的**有用光束**：从灯珠发光面到可视表盘圆盘之间的斜锥。

    比"绕灯轴的正圆锥"准确得多：真正要保护的不是某个角度范围，
    而是"能打到表盘上的那一束光"。任何结构件进入它 = 挡掉了本该照到表盘的光。

    锥的小端取在**穹顶最宽处**（垂直于灯轴的那个圆），不是灯珠顶点。
    取顶点的话，锥体整个落在顶点高度以下，就再也看不见"穹顶上半边被挡"
    这种情况了 —— 实测过：同一个设计，小端取顶点时体积法报 0，
    取穹顶最宽处才报得出来。
    """
    from build123d import Circle, Plane, Sphere, loft

    from .geometry import mirror_x
    from .layout import led_frame

    lg = cfg.light
    loc = led_frame(cfg)
    dial = Plane.XY * Circle(cfg.meter.dial_r)
    # 穹顶最宽处：LED 局部坐标 z = body_h − 1.6，圆面垂直于灯轴
    dome = Plane(loc * Pos(0, 0, lg.body_h - 1.6)) * Circle(lg.body_d / 2)
    cone = loft([dial, dome], ruled=True)
    # 挖掉灯珠自身占的那点体积，免得灯座根部被误判成"遮挡"。
    # ★ 半径只能刚好包住灯珠（body_d/2 + 0.5），不能按灯座外径挖 ——
    #   按 boss_d/2+1 = Ø14 挖的时候，正好把"支承片挡住穹顶上半边"的
    #   那块证据一起挖没了，这条检查于是永远为真。
    #   **排除区域开得太大，等于把检查关掉。**
    cone -= Pos(lg.pos_r, 0, lg.pos_z) * Sphere(lg.body_d / 2 + 0.5)
    return mirror_x(cone)


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
    # 字轮窗口（位置来自 params.Meter.digit_window，不在这里写死）
    x0, x1, y0, y1 = cfg.meter.digit_window
    for i in range(5):
        pts.append((x0 + (x1 - x0) * i / 4, (y0 + y1) / 2, "字轮窗"))
    # 四个指针盘
    for i, (dx, dy) in enumerate(cfg.meter.pointer_positions):
        pts.append((dx, dy, f"指针{i + 1}"))
    return pts


def ocr_critical_points(cfg: Config) -> list[tuple[float, float, str]]:
    """
    **OCR 真正要读的那几处**：字轮窗 + 四个指针盘。

    眩光判据只看这里 —— 表盘最外缘（蓝圈、刻度）有没有反光不影响读数，
    把它算进去只会得到一个吓人但没意义的数字。
    """
    x0, x1, y0, y1 = cfg.meter.digit_window
    out = []
    for i in range(5):
        for j in range(2):
            out.append((x0 + (x1 - x0) * i / 4, y0 + (y1 - y0) * j, "字轮窗"))
    for i, (dx, dy) in enumerate(cfg.meter.pointer_positions):
        out.append((dx, dy, f"指针{i + 1}"))
    return out


def specular_separation_deg(cfg: Config, point: Vector, tip: Vector) -> float:
    """
    某个表盘点上，LED 的**镜面反射方向**与**采集方向**的夹角。

    判据式子（写出来接受检查）::

        d = normalize(P − T)              入射方向
        n = (0, 0, 1)                     表盘法线
        R = d − 2(d·n)n                   镜面反射方向
        c = normalize(V − P)              该点指向虚拟相机的方向
        分离角 = ∠(R, c)

    夹角越小，反射瓣越可能直接打进镜头 → 字轮上出现高光。

    ⚠ 这里把表盘玻璃当成**平面**。实际是弧面 + 液封介质，
    反射瓣会展宽，所以真实的风险比这个数字算出来的更大一些。
    结论要留余量，不要卡着阈值用。
    """
    n = Vector(0, 0, 1)
    d = (point - tip).normalized()
    refl = d - n * (2 * d.dot(n))
    cam = (virtual_camera(cfg) - point).normalized()
    return math.degrees(math.acos(max(-1.0, min(1.0, refl.dot(cam)))))


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
