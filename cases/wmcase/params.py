# -*- coding: utf-8 -*-
"""
==============================================================================
 参数中心 —— 全项目**唯一**允许出现尺寸数字的地方
==============================================================================

规矩（改模型前请先读）
----------------------
1. **建模函数里不许写魔法数字。** 需要新尺寸就在这里加字段，写清单位、来源、
   影响面。这样人可以只看这一个文件就完成微调，AI 也能安全地做参数搜索。
2. 每个字段的注释必须回答三件事：**是什么 / 哪来的 / 改了会连锁影响谁**。
3. 字段分四种可信度，用前缀标记：

   ==========  ==============================================================
   ``[实测]``  卡尺量过的实物尺寸。改动 = 换了一块表 / 换了一块板。
   ``[采购]``  外购件规格书。改动 = 换了供应商。
   ``[设计]``  我们自己定的，可以调。这是参数搜索的主要空间。
   ``[估算]``  还没验证的假设。**每一条都在 DESIGN.md §未验证假设 里有条目。**
   ==========  ==============================================================

坐标系（贯穿全项目，任何时候不要改，理由见 DESIGN.md §2）
----------------------------------------------------------
::

    原点 O = 水表表盘玻璃面的中心
    +X     = 沿水表体轴线（左右），整机左右对称
    +Y     = 离墙方向（房间一侧）；吊舱、滑盖、整机拆卸都在这一侧
    +Z     = 垂直向上；上方净空 70mm 是全项目最紧的约束

单位一律 mm、度。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace  # noqa: F401  (replace 供外部调参用)


# =============================================================================
#  1. 水表 —— 宁波埃美柯 LXSY-15E2（DN15 旋翼式液封冷水表）
# =============================================================================

@dataclass(frozen=True)
class Meter:
    """
    被测水表。换表型时**只改这一段**，其余尺寸链会自动跟随（并被自检拦一遍）。

    样本文档：``amico-lxsy.pdf`` p.009-010（外形尺寸表）、``amico.pdf`` p.1。
    样机实测：40 台中的典型件，游标卡尺。
    """

    # ---- 铭牌 / 样本尺寸（amico-lxsy.pdf 外形尺寸与重量表，LXSY-15E2 行）----
    model: str = "LXSY-15E2"
    dn: int = 15                     # [采购] 公称口径 DN15
    body_len: float = 165.0          # [采购] 表体长度 L（不含活接）
    body_width: float = 94.0         # [采购] 表体最大宽度 B（含表头蓝盖）
    body_height: float = 111.0       # [采购] 表体总高 H（含蓝盖，闭合状态）
    thread: str = "G3/4B"            # [采购] 连接螺纹 D

    # ---- 表头实测（**这几条是抱箍与光学的全部基准**）----
    bezel_od: float = 82.1           # [实测] 银圈外径。抱箍内孔/内棱的唯一基准。
    bezel_id: float = 61.8           # [实测] 银圈内径
    bezel_h: float = 21.1            # [实测] 银圈总高
    dial_visible_d: float = 56.5     # [实测] 可视表盘直径（蓝圈内径）= 光学 ROI 基准
    glass_depth: float = 7.0         # [估算] 银圈顶面 → 表盘玻璃面 的深度。
    #                                  ★ 影响**全部 Z 基准**，优先实测（深度尺插到玻璃面）。
    boss_h: float = 2.8              # [实测] 银圈底部凸台高度（宽 9.5），夹持带必须避开
    boss_w: float = 9.5              # [实测] 银圈底部凸台宽度

    # ---- 蓝色固定环 + 蓝色盖板（**真实存在的活动件，必须建模**）----
    #  光学读表要求蓝盖**常开**。它绕表盘中心的铰链翻转，为了不挡 LED 和相机，
    #  只能朝**墙侧**（−Y）停放；最大打开角约 100°（盖板与表盘面的夹角）。
    ring_h: float = 5.0              # [实测] 蓝色固定环高出表盘玻璃面
    ring_t: float = 2.65             # [实测] 蓝色固定环壁厚
    #  环的内径就是可视表盘直径（56.5），外径 = 56.5 + 2×2.65 = 61.8
    #  —— 正好等于实测的银圈内径，两个独立测量互相印证。
    cover_r: float = 31.5            # [估算] 盖板半径（铰链在盖板边缘上）
    cover_t: float = 3.0             # [估算] 盖板厚度
    cover_open_deg: float = 100.0    # [实测] 停放时盖板与表盘面的夹角（= 最大打开角）
    #  ★ 判定不能只用一个角度：盖板靠重力/摩擦停住，逐台会有差异。
    #    下限 90° 是设计承诺 —— 装配时必须把盖板向墙侧翻到底并确认它不回弹。
    cover_park_range_deg: tuple[float, float] = (90.0, 105.0)   # [设计] 判定用的停放角区间
    #  ★ 这三个数决定"托板会不会被蓝盖卡住"，是当前最关键的一组尺寸。
    #    cover_r / cover_t 仍是照片目测，**建议卡尺补测**。

    @property
    def ring_od(self) -> float:
        return self.dial_visible_d + 2 * self.ring_t          # 61.8

    @property
    def cover_hinge_y(self) -> float:
        """铰链轴的 Y（在固定环外缘的墙侧）。"""
        return -self.ring_od / 2                              # −30.9

    @property
    def cover_hinge_z(self) -> float:
        """铰链轴的 Z（固定环顶面）。"""
        return self.ring_h                                    # +5

    # ---- 表体（只用于装配体检视和"抱箍别撞表体"的判据，不是精确外形）----
    pipe_axis_z: float = -57.0       # [实测] 管轴中心 → 表盘玻璃面 57mm
    body_casting_d: float = 70.0     # [估算] 中段铸体外径
    body_casting_len: float = 90.0   # [估算] 中段铸体沿轴长度
    pipe_stub_d: float = 30.0        # [估算] 两端管接外径（G3/4B 约 Ø26 + 活接）

    # ---- watermeter-dn25.step 的摆放（**仅供外观参考，不参与任何判定**）----
    #  STEP 自身坐标系：X = 管轴，**Y = 竖直向上**，Z = 宽度方向。
    #  表头（Ø100.87 的银圈段）在 Ys 80~104，轴心落在 Xs=0 / Zs=0。
    dn25_bezel_top_ys: float = 104.0  # [实测:STEP] 银圈顶面所在的 Ys

    # ---- 表盘上的 OCR 关键区（**眩光判据只看这几处**，外缘有反光不影响读数）----
    #  ⚠ 全是照片目测，需要对着实表核对一次。
    digit_window: tuple[float, float, float, float] = (-12.0, 12.0, 5.0, 11.0)  # [估算]
    pointer_positions: tuple[tuple[float, float], ...] = (                       # [估算]
        (-14.0, -8.0), (14.0, -8.0), (-14.0, -18.0), (14.0, -18.0),
    )

    # ---- 现场约束 ----
    headroom: float = 70.0           # [实测] 银圈顶面 → 上方最近障碍（40 台取**最小**值）
    #  （蓝盖的占位空间不再用两个手填的包络数字，改由 refs.blue_cover() 按
    #    铰链位置 + 打开角度真实建模，自检 FIT-14 直接和实体求交。）

    # ---- 派生（不要手改）----
    @property
    def bezel_top_z(self) -> float:
        """银圈顶面 Z。"""
        return self.glass_depth                      # +7.0

    @property
    def bezel_bottom_z(self) -> float:
        return self.bezel_top_z - self.bezel_h       # -14.1

    @property
    def boss_top_z(self) -> float:
        """银圈底部凸台顶面 Z —— 夹持带下沿必须高于它。"""
        return self.bezel_bottom_z + self.boss_h     # -11.3

    @property
    def ceiling_z(self) -> float:
        """天花板（上方障碍物）在全局坐标里的 Z。**全项目最硬的约束。**"""
        return self.bezel_top_z + self.headroom      # +77.0

    @property
    def dial_r(self) -> float:
        return self.dial_visible_d / 2               # 28.25


# =============================================================================
#  2. 开发板 —— ESP32-S3-CAM（第一版适配 esp32s3cam-2.step）
# =============================================================================

@dataclass(frozen=True)
class BoardSpec:
    """
    开发板的**几何契约**。

    这里的数字全部是从 STEP 模型里量出来的（``python build.py inspect <file.step>``），
    用 STEP 自己的局部坐标系表达。``wmcase.refs.board_location()`` 负责把它
    变换到全局坐标；``checks/fit.py`` 会拿真实 STEP 反过来核对这张表，
    **换板子时如果只改了 step 路径没改这张表，自检会立刻报错。**

    STEP 局部坐标（esp32s3cam-2.step）::

        Xs : 0 → 40    PCB 长边（装到全局 -Z，即 Xs 增大 = 向下）
        Ys : 0 → 1.0   PCB 板厚方向，摄像头在 +Ys 一侧（装到全局 -Y）
        Zs : 0 → 27    PCB 短边（装到全局 -X）
    """

    name: str = "esp32s3cam-2"
    step_file: str = "esp32s3cam-2.step"

    # ---- PCB 本体 [实测:STEP] ----
    pcb_x: tuple[float, float] = (0.0, 40.0)     # PCB 在 Xs 上的范围（长 40）
    pcb_y: tuple[float, float] = (0.0, 1.0)      # 模型板厚 1.0（实物 1.6，见 pcb_t_real）
    pcb_z: tuple[float, float] = (0.0, 27.0)     # PCB 在 Zs 上的范围（宽 27）
    pcb_t_real: float = 1.6                      # [实测] 实物板厚，做间隙时用这个

    # ---- 光轴位置 [实测:STEP] ----
    axis_xs: float = 8.91        # 光轴到 Xs=0 短边的距离 → 这一侧朝上
    axis_zs: float = 13.51       # 光轴到 Zs=0 长边的距离（≈27/2，天然居中）

    # ---- 摄像头模组 [实测:STEP] ----
    lens_face_ys: float = 9.07   # 镜头前端面（镜筒端面）的 Ys → 光学基准面
    holder_sq: float = 8.50      # 模组方形本体边长（8.5×8.5）
    holder_front_ys: float = 7.14  # 方形本体前端面 Ys（比镜筒端面靠后 1.93）
    holder_back_ys: float = 3.04   # 方形本体后端面 Ys
    barrel_d: float = 5.90       # 镜筒外径

    # ---- 前侧（+Ys）让位包络 [实测:STEP] ----
    #  前腔让位槽做成**两级**，因为前侧元件也是两级的：
    #    深级 = SD 卡座 + 摄像头排线（伸出 PCB 约 2.2mm，集中在中间）
    #    浅级 = 一圈贴片元件和引脚焊尾（只伸出 1.54mm，但一直铺到 X±12.81）
    #  两级分开做，才能在 PCB 下缘（Z<18.8，前侧完全干净）留出真正的止挡台阶。
    #  ⚠ 早期只做了深级一档，结果十几处贴片元件顶在台阶上，
    #    干涉体积每处不到 0.5mm³ —— 小到很容易被当成布尔噪声忽略掉。
    front_deep_ys: float = 3.38      # 深级最靠前的 Ys（摄像头排线背面）
    front_deep_xs: tuple[float, float] = (-0.50, 28.65)   # SD 卡外伸 0.5 / 排线尾端
    front_deep_zs: tuple[float, float] = (5.77, 21.77)    # SD 卡座宽度
    front_smd_ys: float = 2.54       # 浅级最靠前的 Ys（= 伸出 PCB 面 1.54mm）
    front_smd_xs: tuple[float, float] = (-0.50, 31.55)    # 浅级元件的 Xs 范围
    front_smd_zs: tuple[float, float] = (0.70, 26.32)     # 浅级元件的 Zs 范围

    # ---- 后侧（-Ys）：模块 + 排针 [实测:STEP] ----
    back_depth: float = 9.02     # 板背面最高元件（排针）伸出量
    module_depth: float = 3.55   # WROOM 模块伸出量
    header_zs: tuple[float, float] = (0.93, 26.47)  # 两排排针的 Zs 外缘

    # ---- 整体包围盒 [实测:STEP]，仅供自检核对 STEP 是否换了 ----
    bbox_min: tuple[float, float, float] = (-0.50, -9.01, 0.00)
    bbox_max: tuple[float, float, float] = (40.00, 9.07, 27.00)
    bbox_tol: float = 0.30       # 核对容差

    # ---- 派生 ----
    @property
    def pcb_w(self) -> float:
        """PCB 短边宽（→ 全局 X 方向）。"""
        return self.pcb_z[1] - self.pcb_z[0]

    @property
    def pcb_l(self) -> float:
        """PCB 长边（→ 全局 Z 方向）。"""
        return self.pcb_x[1] - self.pcb_x[0]

    @property
    def lens_to_pcb_face(self) -> float:
        """镜头前端面 → PCB 前表面 的距离（8.07）。吊舱前腔深度由它决定。"""
        return self.lens_face_ys - self.pcb_y[1]

    @property
    def axis_to_top(self) -> float:
        """光轴 → 板"上"边缘（Xs=0 那侧）。"""
        return self.axis_xs - self.pcb_x[0]

    @property
    def axis_to_bottom(self) -> float:
        """光轴 → 板"下"边缘。"""
        return self.pcb_x[1] - self.axis_xs


#: 已知开发板清单。第一版只适配 ``esp32s3cam-2``；
#: 适配 1 / 3 时在这里加一条 BoardSpec（数字用 ``python build.py inspect`` 量），
#: 然后跑 ``python build.py check --board esp32s3cam-1``。
BOARDS: dict[str, BoardSpec] = {
    "esp32s3cam-2": BoardSpec(),
}


# =============================================================================
#  3. 光学 —— 45° 前表面反射镜折叠光路
# =============================================================================

@dataclass(frozen=True)
class Optics:
    """
    光路::

        表盘中心 ──垂直上行 mirror_z──> 45°镜 ──水平前行 lens_face_y──> 镜头

    等价模型（自检和成像分析都用它，推导见 DESIGN.md §4.2）：
    把镜头对 45° 镜面做镜像，得到一个悬在表盘正上方
    ``z = mirror_z + lens_face_y`` 处、垂直向下看的**虚拟相机**。
    于是"某个表盘点能不能被看到"就退化成一条从该点连到虚拟相机的直线。
    """

    roi_r: float = 29.0          # [设计] 需要成像的半径。表盘 Ø56.5 → 28.25，取 29 留余量。
    mirror_z: float = 42.0       # [设计] 镜面中心高度 = 镜头光轴高度。
    #                              ↑ 抬高 → 光程变长、字变小；降低 → 银圈挡光。
    lens_face_y: float = 80.0    # [设计] 镜头前端面 Y。
    #                              ↑ 加大 → 景深更好但整机更长、字更小。

    # ---- 反射镜（外购件）----
    mirror_l: float = 62.0       # [采购] 前表面镜 长（沿 45° 斜面方向）
    #  ★ 70 → 62 是被**蓝色盖板**逼下来的，不是光学需要：
    #    盖板朝墙侧停放时会卡住托板的后下角。实测扫描（镜长 × 停放角）：
    #        镜长 70 → 需停放 ≥105° 才不碰      镜长 66 → 需 ≥100°
    #        镜长 64 → 需 ≥ 95°                镜长 62 → 需 ≥ 90°  ← 现在这个
    #        镜长 60 → 需 ≥ 88°
    #    62 是"光学余量仍有 5mm（需 57.0）"和"容忍盖板只翻到 90°"的交点。
    #    采购 60~66 都能用，但要按上表对应地要求现场把盖板翻到位。
    mirror_w: float = 50.0       # [采购] 前表面镜 宽（沿 X）
    mirror_t: float = 2.0        # [采购] 前表面镜 厚
    mirror_len_margin: float = 5.0   # [设计] 镜长相对光学最小需求要留的余量
    #   ↑ 当前正好卡在这个值上（62.0 − 57.0 = 5.0），因为镜长的上限是被
    #     **蓝色盖板**卡住的，不是光学。想要更多余量只能提高蓝盖的停放角要求。

    # ---- 相机（OV2640）----
    hfov_deg: float = 66.0       # [采购] 水平视场角
    sensor_px_h: int = 1600      # [采购] 水平像素（UXGA）
    sensor_px_v: int = 1200      # [采购] 垂直像素
    digit_w_mm: float = 4.4      # [实测] 表盘上单个字轮数字的宽度
    min_digit_px: float = 20.0   # [设计] AI-on-the-edge 可靠识别的下限

    # ---- 景深 ----
    f_number: float = 2.4        # [采购] 光圈
    coc_um: float = 4.4          # [设计] 容许弥散圆（≈2 像素）

    # ---- 派生 ----
    @property
    def path(self) -> float:
        """总光程 = 表盘 → 镜面 → 镜头前端面。"""
        return self.mirror_z + self.lens_face_y      # 122

    @property
    def virtual_cam(self) -> tuple[float, float, float]:
        """虚拟相机位置（镜头关于 45° 镜面的镜像）。见 DESIGN.md §4.2 的推导。"""
        return (0.0, 0.0, self.path)

    @property
    def cone_slope(self) -> float:
        """光锥半锥角的正切：从虚拟相机看，半径 roi_r 对应距离 path。"""
        return self.roi_r / self.path

    @property
    def beam_r_at_mirror(self) -> float:
        """光锥在镜面中心高度 (z=mirror_z) 处的半径。"""
        return self.roi_r * (1 - self.mirror_z / self.path)   # 19.02

    @property
    def ellipse_y(self) -> tuple[float, float]:
        """
        45° 镜面 (z = y + mirror_z) 与光锥相交所得椭圆的 Y 向前后端。
        推导：锥面 r(z) = roi_r·(1 − z/path)，在 y-z 剖面里令 z = y + mirror_z。
        """
        b = self.beam_r_at_mirror
        k = self.cone_slope
        return (-b / (1 - k), b / (1 + k))           # (-24.95, +15.36)

    @property
    def mirror_center_y(self) -> float:
        """镜面有效区中心的 Y —— 托板就以它为中心排布。"""
        y0, y1 = self.ellipse_y
        return (y0 + y1) / 2                         # -4.79

    @property
    def need_mirror_len(self) -> float:
        """光学上必需的镜片长度（沿 45° 斜面）。"""
        y0, y1 = self.ellipse_y
        return (y1 - y0) * math.sqrt(2)              # 57.0

    @property
    def need_mirror_width(self) -> float:
        """光学上必需的镜片宽度（沿 X）。"""
        return 2 * self.beam_r_at_mirror             # 38.0

    @property
    def digit_px(self) -> float:
        """单个字轮数字的成像宽度（像素）。< min_digit_px 就别指望 OCR。"""
        fov_w = 2 * self.path * math.tan(math.radians(self.hfov_deg / 2))
        return self.digit_w_mm * self.sensor_px_h / fov_w

    @property
    def focal_mm(self) -> float:
        """由 HFOV 和 1/4" 传感器（宽 3.6mm）反推的等效焦距 f。"""
        sensor_w = 3.6
        return sensor_w / (2 * math.tan(math.radians(self.hfov_deg / 2)))

    @property
    def dof_half_mm(self) -> float:
        """
        景深半宽（±值）。判据式子写在这里，接受检查（DESIGN_NOTES §7.7 的教训）::

            DoF_half ≈ N · c · s² / f²
            N = f_number, c = 容许弥散圆, s = 物距(=path), f = 焦距

        表盘是个 glass_depth 深的井，本值必须明显大于 glass_depth。
        """
        f = self.focal_mm
        c = self.coc_um / 1000.0
        return self.f_number * c * self.path ** 2 / (f * f)


# =============================================================================
#  4. 照明 —— 两颗 5mm 草帽白光 LED（离轴，抑制镜面高光）
# =============================================================================

@dataclass(frozen=True)
class Lighting:
    """
    为什么必须是**离轴 + 对置两颗**，见 DESIGN.md §4.4。
    一句话：同轴照明必然在液封玻璃上打出高光（几何问题，调亮度无效）；
    单颗离轴会在井壁投出约 12mm 阴影带，正好压住最外圈指针。
    """

    # ---- 灯珠（led.step 实测）----
    flange_d: float = 5.80       # [实测] 草帽灯法兰外径
    flange_flat: float = 2.40    # [实测] 法兰上的极性切边到轴心的距离（**防呆基准**）
    flange_h: float = 1.00       # [估算] 法兰厚度
    body_d: float = 5.00         # [实测] 灯体（穹顶）外径
    body_h: float = 4.80         # [实测] 灯体总高（法兰底面 → 穹顶最高点）
    lead_len: float = 25.0       # [实测] 引脚长度
    lead_pitch: float = 2.72     # [实测] 引脚中心距
    lead_sq: float = 0.48        # [实测] 引脚截面边长
    half_angle_deg: float = 60.0  # [采购] 发光半角（120° 全角草帽灯）

    # ---- 安装位置 ----
    pos_r: float = 38.0          # [设计] 灯珠顶点所在半径（±38, 0, z）
    pos_z: float = 20.0          # [设计] 灯珠顶点高度
    #                              ↑ 这两个值决定入射角。改动务必看自检里的
    #                                「LED 越过银圈内缘的高度」和「最小入射角」。
    #                              ↑ 30 → 20 是被**可拆性**逼下来的：灯座凸台会伸到
    #                                X≈37 处，托板支承片平推出来时正好从那里经过。
    #                                灯珠降到 z=20，凸台落到 z<27，支承片抬 8mm 后
    #                                （底面 z=28）刚好从它上面掠过。
    #                                光学上更好：入射角从 51.7° 增到 62.2°，
    #                                镜面反射瓣偏得更远；掠射高度 14.9mm 仍远大于井深。
    #  覆盖整个表盘所需的半角**不是参数，是派生量** —— 它由灯珠位置和表盘半径
    #  唯一确定。早先把它写成手填的 21°，后来 LED 从 z=30 降到 20，
    #  这个数没跟着变，于是"必需光锥"整整小了一半，任何遮挡都查不出来。
    #  **凡是能由几何唯一确定的量，都不许出现在参数表里。**
    #  见 Lighting.required_half_angle_deg。

    @property
    def axis_len(self) -> float:
        """灯珠顶点到表盘中心的距离。"""
        return math.hypot(self.pos_r, self.pos_z)

    def required_half_angle_deg(self, dial_r: float) -> float:
        """
        覆盖整个可视表盘所需的**最小半锥角**（派生量，不是参数）。

        判据式子：灯珠顶点 T=(pos_r, 0, pos_z)，灯轴指向表盘中心，
        对表盘边缘上的每一点 P 求 ``∠(P−T, O−T)``，取最大值。
        最远的那个点不在正对面，而在侧后方 —— 所以不能只算轴向剖面。
        """
        tip = (self.pos_r, 0.0, self.pos_z)
        axis = (-tip[0], 0.0, -tip[2])
        an = math.hypot(axis[0], axis[2])
        worst = 0.0
        for i in range(72):
            a = 2 * math.pi * i / 72
            v = (dial_r * math.cos(a) - tip[0], dial_r * math.sin(a), -tip[2])
            vn = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
            cos = (v[0] * axis[0] + v[2] * axis[2]) / (vn * an)
            worst = max(worst, math.degrees(math.acos(max(-1.0, min(1.0, cos)))))
        return worst

    # ---- 灯座 ----
    boss_d: float = 12.0         # [设计] 灯座外径
    boss_l: float = 6.0          # [设计] 灯座长度（沿灯轴）
    #                              ↑ 太长会从立板**外**表面戳出来（自检 WIRE-04）
    bore_clr: float = 0.10       # [设计] 法兰与孔的单边间隙
    #                              ↑ 它同时决定极性防呆的阻挡量：
    #                                装反时阻挡 = flange_d/2 − (flange_flat + bore_clr)
    #                                = 2.90 − 2.50 = 0.40mm，自检 POKA-03 要求 ≥0.30
    lead_bore_d: float = 3.20    # [设计] 引线过孔直径


# =============================================================================
#  5. 制造 —— DfAM（对齐 dfam_rules.md，Bambu A1/P1S + PETG 0.4 喷嘴）
# =============================================================================

@dataclass(frozen=True)
class Mfg:
    """打印与配合。改这一段等于换材料/换机器，全部自检项都会受影响。"""

    # ---- 壁厚（dfam_rules.md §2）----
    wall: float = 2.5            # [设计] 标准壁厚。规范要求 2.0~3.0，取 2.5（≈6 圈走线）
    min_wall: float = 0.8        # [设计] 自检允许的最薄处（= 0.4 喷嘴两圈走线）
    #                              本设计里最薄的**有意**特征就是 T 型槽唇口 0.8。
    plate_t_extra: float = 0.8   # [设计] 镜片 T 型槽唇口以外的余料

    # ---- 圆角（dfam_rules.md §2 内圆角防翘曲）----
    fillet_out: float = 3.0      # [设计] 外轮廓统一圆角
    fillet_in: float = 1.2       # [设计] 内部过渡圆角（规范下限 1.0）

    # ---- 配合间隙（dfam_rules.md §5，Bambu 高精度机型调校值）----
    fit_static: float = 0.20     # [设计] 静态插接（定位销、舌槽）
    fit_slide: float = 0.25      # [设计] 需要反复滑动的配合（滑盖）
    fit_pcb: float = 0.30        # [设计] PCB 周边空气间隙（规范 0.2，这里留大一点）

    # ---- 打印工艺 ----
    max_overhang_deg: float = 45.0   # [设计] 最大悬垂角（自 Z 轴量）
    max_bridge: float = 15.0         # [设计] 最大水平桥接跨度
    layer_h: float = 0.20            # [设计] 层高，用于换算"至少 N 层"
    min_floor_layers: int = 4        # [设计] 沉孔底部最少层数 → 0.8mm

    # ---- 数值 ----
    eps: float = 0.01            # [设计] 布尔微元：所有减法体都要伸出这么多，杜绝共面
    vol_tol: float = 2.0         # [设计] 干涉判定的体积容差 mm³（布尔噪声）


# =============================================================================
#  6. 紧固件
# =============================================================================

@dataclass(frozen=True)
class Fasteners:
    """自攻/机米螺丝孔径。数值取自 dfam_rules.md §4。"""

    m4_clearance: float = 4.40   # [设计] M4 过孔（抱箍夹紧螺栓穿过）
    m4_nut_af: float = 7.00      # [采购] M4 螺母对边
    m4_nut_thick: float = 3.20   # [采购] M4 螺母厚度
    nut_pocket_clr: float = 0.20  # [设计] 螺母沉槽的单边间隙（对边方向）
    m3_selftap: float = 2.70     # [设计] M3 自攻底孔（规范 2.65~2.75）
    m3_clearance: float = 3.25   # [设计] M3 过孔（规范 3.2~3.3）
    set_screw_d: float = 3.20    # [设计] 备用径向顶紧螺钉底孔


# =============================================================================
#  7. 外壳几何 —— 主参数表
# =============================================================================

@dataclass(frozen=True)
class Case:
    """
    外壳自身的几何。这是**参数搜索的主战场**，也是最容易改坏的地方。
    每个分组前面都写了「这一组在解决什么问题」。
    """

    # ---------------------------------------------------------------------
    #  7.1 抱箍 —— 唯一的机械接口，整机靠它固定在银圈上
    #      教训：v2.3 实物拧到底仍能转动，因为内孔比银圈大 2.4mm 而剖分缝只有
    #      2.2mm，完全闭合也只缩小 0.70mm。尺寸链根本不闭合。见 DESIGN_NOTES §7.3。
    #      现在的方案：光孔略大好套入，靠 16 条内棱**过盈**咬住。
    # ---------------------------------------------------------------------
    collar_bore_gap: float = 0.35    # [设计] 光孔相对银圈的单边**间隙**（便于套入）
    collar_rib_interf: float = 0.25  # [设计] 内棱相对银圈的单边**过盈**（咬紧）
    collar_rib_n: int = 16           # [设计] 内棱数量
    collar_rib_d: float = 1.20       # [设计] 内棱（半圆凸筋）直径
    collar_or: float = 47.60         # [设计] 抱箍外半径
    collar_z0: float = -10.0         # [设计] 夹持带下沿（必须 > 银圈底凸台顶 -11.3）
    collar_z1: float = 6.5           # [设计] 夹持带上沿（必须 < 银圈顶面 +7）
    collar_slit_w: float = 4.0       # [设计] 剖分缝宽度 = 弹性张开行程
    collar_ear_w: float = 9.0        # [设计] 夹紧耳厚度
    collar_bolt_z: tuple[float, float] = (-6.0, 2.5)   # [设计] 两颗 M4 的高度
    collar_set_ang: float = 55.0     # [设计] 备用径向顶紧孔的方位角

    # ---------------------------------------------------------------------
    #  7.2 立板（mast）—— 从抱箍长上来的两片竖板，挂 LED / 镜托 / 吊臂
    # ---------------------------------------------------------------------
    #   立板内侧面 X = 42.5，抱箍外半径 = 47.6，两者在 X 上是重叠的 ——
    #   这是**有意的**：立板下端要嵌进抱箍才能连成单一实体（自检 TOPO-01 会验）。
    #   真正的硬约束是「托板支承脚外缘 < mast_inner_x」，见 7.4。
    mast_inner_x: float = 42.5       # [设计] 立板内侧面 X
    mast_t: float = 7.0              # [设计] 立板厚度
    buttress_top_z: float = 17.0     # [设计] 撑座（抱箍→立板过渡）顶面高度
    #: [设计] 立板在 YZ 平面的外轮廓（顺时针）。改形状只需要改这一串点。
    mast_profile: tuple[tuple[float, float], ...] = (
        (-28, 10), (22, 10), (22, 50), (10, 54), (-14, 48), (-28, 34),
    )

    # ---------------------------------------------------------------------
    #  7.3 镜片托板的支承 —— 四点销定位 + 两级水平托台
    #      教训：托台顶面是水平的，托板底面是 45° 斜面，
    #      托台顶必须低于**该段斜面的最低点**，否则一端顶死一端悬空。
    #      见 DESIGN_NOTES §7.5。
    # ---------------------------------------------------------------------
    #  ★ 前后托台**必须等高**。这不是审美，是可拆性的硬约束：
    #
    #  早期版本按"托板底面是 45° 斜面"的直觉，把前托台放在 z=50、后托台放在
    #  z=20。每个零件单独看都没问题，静态干涉也全过 —— 但整块托板**根本拿不出来**：
    #  每月抄表要把它沿 +Y 抽出，抽的过程中支承结构的**后**半段会扫过**前**托台，
    #  而后半段比前托台低 30mm，需要抬升 >30mm 才能越过去，
    #  天花板只给 11mm。这是自检 SEQ-02（抄表流程）逐点仿真抓出来的，
    #  静态检查一条都报不出来 —— **"装得进去"和"拿得出来"是两回事。**
    #
    #  现在两个托台同高，托板的支承面是一条水平底边，抬 8mm 即可平推出来。
    pad_inner_x: float = 32.0        # [设计] 托台内缘 X
    #   ★ **不要**跟着支承片内缘（31）一起往里挪：托板本体是 ±32，
    #     托台伸到 31 就会顶到托板本体的下缘，抽出时刮擦（自检 SEQ-03 报 3.14mm³）。
    #     支承片可以比托台更往里伸 —— 它是活动件，只要有 7mm 承压宽度就够。
    pad_rear_y: tuple[float, float] = (-20.0, -12.0)   # [设计] 后托台 Y 范围
    pad_rear_z: float = 20.0         # [设计] 后托台顶面
    pad_front_y: tuple[float, float] = (10.0, 18.0)    # [设计] 前托台 Y 范围
    pad_front_z: float = 20.0        # [设计] 前托台顶面（**与后托台等高**）
    pad_clear: float = 2.0           # [设计] 托台顶面必须比该段托板底面低这么多
    pad_drop: float = 12.0           # [设计] 托台 loft 的垂直落差
    #                                  ↑ 决定内伸斜面的角度：(mast_inner_x − pad_inner_x)/pad_drop
    #                                    = 10.5/12 → 离竖直 41°，在 45° 免支撑范围内

    # ---- 定位销（**防呆**：前后销径不同，托板装反装不进去）----
    pin_x: float = 35.0              # [设计] 销中心 X（左右对称）
    #                                  ↑ 必须让销整个落在托台上（> pad_inner_x + 销半径），
    #                                    同时让托板支承片能整个包住它
    pin_d_rear: float = 4.0          # [设计] 后销直径
    pin_d_front: float = 5.0         # [设计] 前销直径（≠ 后销 → 防呆）
    pin_h: float = 5.0               # [设计] 销高（竖直销，零支撑打印）

    # ---------------------------------------------------------------------
    #  7.4 镜片托板本体
    # ---------------------------------------------------------------------
    holder_plate_w: float = 64.0     # [设计] 托板宽度（X 向，±32）
    holder_lip: float = 2.2          # [设计] T 型槽唇口宽度（镜面朝下靠它兜住）
    #  支承片：每侧**一片**，同时充当"三角耳"和"支承脚"。
    #  X 范围有三个硬约束，改之前先看清楚：
    #    内缘 32 —— 必须 ≤ 托板半宽，否则接不到托板上
    #    外缘 38 —— 必须 < LED 灯座凸台的最内缘（约 37.7），否则平推时会撞上灯座
    #    整片 —— 必须包住定位销（pin_x ± 销半径）
    #    ★ 宽度还要能容下定位销孔：前销 Ø5 → 孔 Ø5.2，
    #      支承片 6mm 宽时两侧只剩 0.4mm 壁（自检 DFAM-02 报最薄 0.34mm）。
    #      加到 8mm 宽，两侧各剩 1.4mm，才印得出来也扛得住定位载荷。
    holder_bracket_x: tuple[float, float] = (31.0, 39.0)
    #: [设计] 支承片在 YZ 平面的轮廓。底边是**水平**的（z=20），落在两个等高托台上；
    #:        顶边沿 45° 走，贴住托板背面（z = y + 48，比托板背面低 1.5mm）。
    #:
    #:  ★ 底边中段（y −9~+9）抬到 z=28，做成一个**让光拱**。
    #:    灯珠顶点就在 (±38, 0, 20)，和支承片底边等高；如果底边是平的，
    #:    Ø5 穹顶**上半部分**发出的光（角度更平）会被这片挡掉。
    #:    实测：按真实穹顶取 9 个发光点追踪，**46% 的光线被挡**。
    #:    把灯珠当成一个"点"是发现不了的（点光源追踪结果是 0% 被挡）。
    #:  拱的 y 范围刻意避开两个托台（−20~−12 和 +10~+18），承压面一点没少。
    holder_bracket_profile: tuple[tuple[float, float], ...] = (
        (-22, 20), (-9, 20), (-9, 28), (9, 28), (9, 20), (18, 20), (18, 66), (-22, 26),
    )
    holder_bracket_t: float = 6.0    # [设计] 支承片厚度
    holder_lift_clear: float = 8.0   # [设计] 每月抄表时，托板需要垂直提起的高度

    # ---------------------------------------------------------------------
    #  7.5 吊臂 —— 立板 → 吊舱，下开口 U 型槽（走线 + 减重 + 提高比刚度）
    # ---------------------------------------------------------------------
    arm_h: float = 16.0              # [设计] 吊臂截面高
    arm_channel_w: float = 2.6       # [设计] U 型腔宽（走两根 LED 线）
    arm_channel_h: float = 10.0      # [设计] U 型腔高
    #  ★ 吊臂走**三段**，不是一根直的斜杆。
    #    直杆会从 (46,16,42) 一路斜插到吊舱，正好横穿镜片托板抽出时扫过的空间
    #    （自检 SEQ-02 报出 1053mm³ 干涉）。现在的走法是：
    #    先贴着立板那一侧（X≈46）平着前伸，等越过托板的抽出范围（y≈48）之后
    #    再收进来、降下去。托板整个在 X≤38，和第一段完全不共面。
    arm_mast_x: float = 46.0         # [设计] 立板端 X 中心
    arm_mast_y: float = 16.0         # [设计] 立板端 Y
    arm_mast_z: float = 34.0         # [设计] 立板端截面底边 Z
    arm_mid_y: float = 50.0          # [设计] 转折点 Y（必须 > 托板抽出后的最前端）
    arm_mid_z: float = 22.0          # [设计] 转折点截面底边 Z
    arm_pod_x: float = 18.0          # [设计] 吊舱端 X 中心（贴着吊舱侧壁）
    arm_channel_pod_x: float = 19.0  # [设计] U 型腔在吊舱端的 X 中心
    #   ★ 必须让整条腔留在吊舱**侧壁**里（X 17~21.5），不能骑在型腔边界上。
    #     骑在 X=17 上时，腔和型腔各切掉一半，中间留下一片零点几毫米的薄壁——
    #     STEP 看起来完全正常（is_valid=True、单一实体），但 3MF 网格化会直接失败
    #     （lib3mf 报 "3mf mesh is invalid"）。切片器拿到的是网格，所以这是**致命**的。

    # ---------------------------------------------------------------------
    #  7.6 吊舱 —— 装开发板的盒子。**尺寸全部由 BoardSpec 推导**，见 layout.py
    # ---------------------------------------------------------------------
    pod_half_x: float = 21.5         # [设计] 吊舱外半宽
    pod_z0: float = -11.5            # [设计] 吊舱底面
    pod_z1: float = 62.0             # [设计] 吊舱顶面（必须 < 天花板 77）
    pod_front_wall: float = 3.0      # [设计] 前壁厚（开镜头孔的那面）
    pod_back_y: float = 114.0        # [设计] 吊舱后表面 Y
    cav_half_x: float = 17.0         # [设计] 主型腔半宽
    cav_z0: float = -9.0             # [设计] 主型腔底
    cav_z1: float = 57.0             # [设计] 主型腔顶
    lens_bore_d: float = 13.0        # [设计] 镜头孔直径（要容下镜筒 Ø5.9 且不遮挡视场）
    polarizer_d: float = 20.0        # [采购] 备用偏振片直径
    polarizer_depth: float = 1.2     # [设计] 偏振片沉孔深度
    #  ★ 板卡改成**从顶部竖直滑入两条 C 型槽**（不再是从后方水平推入）。
    #    横向推入时，任何"卡钩"都必须紧挨着 PCB 前表面止挡台阶（相距 1.6mm），
    #    根本留不出悬臂长度 —— 想做弹性卡扣在几何上就不成立。
    #    改成竖直滑入后，槽的前壁（台阶）和后压唇天然把 Y 向双向锁死，
    #    **不需要任何弹性件**，也不再依赖 EVA 泡棉把板顶住。
    board_rib_clear: float = 0.40    # [设计] PCB 侧边导轨的单边间隙
    board_rib_t: float = 1.60        # [设计] PCB 侧边导轨厚度
    board_lift: float = 5.0          # [设计] 板卡装配时的抬升行程
    #   ★ 装配动作：抬高 4mm 水平推入 → 落下 4mm 就位。
    #     下缘压唇只占 Z 的最下面 4mm，抬高时 PCB 整个在它之上，推得进去；
    #     落下之后压唇正好扣住 PCB 下缘后角，+Y 就锁死了。
    #     方腔和两级让位槽的上边界都要加上这 4mm 行程。
    board_slot_clr: float = 0.25     # [设计] 压唇与 PCB 后表面的间隙
    board_lip_overlap: float = 1.00  # [设计] 后压唇盖住 PCB 边缘的宽度
    #   ↑ 0.6 时反向判据只有 0.6mm³，和布尔噪声容差（2mm³）分不开 ——
    #     防呆/约束类的反向判据必须比容差高一个量级（同 POKA-03 的教训）。
    board_lip_t: float = 1.60        # [设计] 后压唇厚度（沿 Y）
    board_shelf_len: float = 4.5     # [设计] 板下缘承台沿 Y 的长度
    board_shelf_t: float = 2.0       # [设计] 承台厚度
    cam_pocket_clr: float = 0.35     # [设计] 摄像头模组方腔单边间隙（**决定光轴重复精度**）
    cam_pocket_lead_in: float = 1.2  # [设计] 方腔入口导向倒角
    front_relief_clr: float = 0.60   # [设计] 排线/SD 让位槽的单边间隙
    board_float_y: float = 0.50      # [设计] 镜头前端面相对前壁内表面的浮动余量

    # ---------------------------------------------------------------------
    #  7.7 滑盖 —— 竖直下滑，无螺丝。真正的 C 型槽（约束 X 也约束 Y）
    #      教训：v2.3 的槽只约束 X，盖板可以直接向后掉出来。见 DESIGN_NOTES §7.6。
    # ---------------------------------------------------------------------
    cover_y0: float = 109.0          # [设计] 盖板前表面
    cover_y1: float = 112.0          # [设计] 盖板后表面
    cover_groove_x: float = 19.5     # [设计] 槽底 X
    cover_tongue_x: float = 19.3     # [设计] 舌片外缘 X（差 0.2 = 滑动间隙）
    cover_lip_y: float = 112.2       # [设计] 后压边前沿（压边厚 = pod_back_y - 它 = 1.8）
    cover_finger_d: float = 16.0     # [设计] 顶部手指凹槽直径
    cover_vent_d: float = 4.0        # [设计] 散热/排料孔直径
    # **防呆**：+X 滑槽里有一条定位筋，盖板 +X 舌片在 key_z 以上相应收窄。
    #   正装 → 筋落在收窄段，无阻碍；上下颠倒或前后调头 → 筋撞满宽舌片。
    #   这是一处"错了就装不进去"的硬防呆，自检 POKA-02 用干涉体积验证。
    #   定位筋必须紧贴槽底（下沿 = cav_z0），否则盖板下滑时满宽的舌片
    #   会在半路撞上它 —— 筋放在中段会把正装也一起挡住。
    cover_key_len: float = 10.0      # [设计] 定位筋高度（自槽底往上）
    cover_key_depth: float = 1.0     # [设计] 定位筋伸进槽里的深度
    cover_foam_t: float = 12.0       # [采购] 内侧 EVA 泡棉厚度（把板顶向前止挡）
    #   泡棉压在**排针塑料座**上（板卡最后端），不是压在 PCB 上：
    #   PCB 后表面离盖板还有 19.3mm，做那么厚的泡棉压缩力不可控。
    #   压排针 + 下缘台阶止挡，构成一上一下两点夹持，板卡照样不晃。
    #                                  ↑ 必须盖住"盖板前表面 → 板卡最后端"的间隙
    #                                    并留压缩量，自检 FIT-05 核算这条尺寸链。

    # ---------------------------------------------------------------------
    #  7.8 天线 / 电源 / 驱动板
    # ---------------------------------------------------------------------
    ant_w: float = 15.0              # [采购] FPC 天线宽
    ant_l: float = 65.0              # [采购] FPC 天线长
    ant_t: float = 0.90              # [采购] FPC 天线厚
    ant_y0: float = 91.0             # [设计] 天线框前沿 Y
    driver_pcb: tuple[float, float, float] = (20.0, 2.0, 15.0)  # [采购] 洞洞板 X,Y,Z
    power_hole_d: float = 6.5        # [设计] 底部总进线孔（水滴形）

    # ---- 派生 ----
    @property
    def mast_outer_x(self) -> float:
        return self.mast_inner_x + self.mast_t       # 49.5


# =============================================================================
#  8. 顶层配置
# =============================================================================

@dataclass(frozen=True)
class Config:
    """
    一次设计的完整输入。
    做参数搜索时用 ``dataclasses.replace`` 派生，不要就地改（都是 frozen 的）::

        from dataclasses import replace
        cfg2 = replace(CFG, optics=replace(CFG.optics, mirror_z=45.0))
    """

    meter: Meter = field(default_factory=Meter)
    optics: Optics = field(default_factory=Optics)
    light: Lighting = field(default_factory=Lighting)
    mfg: Mfg = field(default_factory=Mfg)
    fast: Fasteners = field(default_factory=Fasteners)
    case: Case = field(default_factory=Case)
    board: BoardSpec = field(default_factory=BoardSpec)

    #: 参考模型所在目录（相对本文件的上一级，即 ``cases/``）
    refs_dir: str = "."


#: 全局默认配置。命令行 / 脚本都从它出发。
CFG = Config()
