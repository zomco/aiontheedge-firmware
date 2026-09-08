# -*- coding: utf-8 -*-
"""
装配顺序 —— 把"怎么装"写成**数据**，让机器能验证它。

为什么要把装配顺序写进代码
--------------------------
"每个零件都装得进去"和"按某个顺序能把整机装起来"是两件事。
一个典型反例：板卡装得进型腔、滑盖也装得上，但如果先装滑盖再装板卡，
板卡就进不去了。这种问题在静态干涉检查里完全看不见。

所以这里把每一步写成一条 :class:`Step`：谁在动、沿什么路径动、
动的时候现场已经有哪些零件。:mod:`checks.sequence` 会沿路径逐点做布尔，
任何一步撞上，自检就报是哪一步、在路径的第几毫米撞的。

顺带的好处：``ASSEMBLY.md`` 里的装配说明书是从这张表生成的，
文档和模型不会各说各话。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from build123d import Part, Pos, Rot

from .params import Config


@dataclass
class Step:
    """装配（或拆卸）的一步。"""

    index: int
    name: str                      # 这一步在做什么
    part: str                      # 动的是哪个件（Design 上的属性名，或外购件名）
    #: 运动路径：一串 (dx, dy, dz)，从"起始位置"到"最终位置"（最后一项恒为 0,0,0）
    path: tuple[tuple[float, float, float], ...] = ((0.0, 0.0, 0.0),)
    #: 这一步之前已经在现场的零件（Design 属性名）
    present: tuple[str, ...] = ()
    #: 碰撞判定时要忽略的零件。目前只有一种情况：抱箍套银圈时，
    #: 内棱本来就是**过盈**咬上去的，一路都有干涉——那是设计意图，不是碰撞。
    ignore: tuple[str, ...] = ()
    tool: str = "徒手"
    note: str = ""
    pokayoke: str = ""             # 这一步靠什么防呆
    check_path: bool = True        # 是否需要沿路径做碰撞仿真


def install_sequence(cfg: Config) -> list[Step]:
    """
    整机装配顺序（现场 + 台面）。

    **顺序不是随便排的**，三条硬理由：

    1. 抱箍必须最先固定 —— 后面所有对位都以它为基准；
    2. 板卡必须在滑盖之前 —— 滑盖封住的正是板卡的插入口；
    3. 镜片托板必须最后 —— 它是每月要拆的件，也是最脆的件。
    """
    c = cfg.case
    lift = c.collar_z1 - c.collar_z0 + 2.0
    return [
        Step(1, "主体套上银圈，压到夹持带下沿到位", "body",
             path=((0, 0, lift), (0, 0, lift / 2), (0, 0, 0)),
             present=("meter",), ignore=("meter",),
             note=f"整机沿 −Z 落下 {lift:.1f}mm。16 条内棱单边过盈 "
                  f"{cfg.meter.bezel_od / 2 - (cfg.meter.bezel_od / 2 - c.collar_rib_interf):.2f}mm，"
                  f"需要稍用力；套不进去先检查银圈上有没有漆瘤。",
             pokayoke="剖分缝和夹紧耳都在 +Y 侧（面向房间），装反了螺栓够不着。"),
        Step(2, "拧紧两颗 M4 蝶形螺栓", "-", tool="徒手（蝶形螺丝）",
             present=("meter", "body"), check_path=False,
             note="上下两颗交替拧，各拧 2~3 圈轮换，避免夹持带张成 V 形。"
                  "拧到用手转不动整机为止。",
             pokayoke="两颗螺栓规格相同，装不错。"),
        Step(3, "压入两颗草帽 LED", "leds",
             present=("meter", "body"), check_path=False, tool="徒手",
             note="引脚先穿过座孔底部的 Ø3.2 过孔，再把法兰压进座孔。",
             pokayoke="★ 座孔有极性切边，灯珠只能按唯一姿态压进去（自检 POKA-03）。"),
        Step(4, "走 LED 引线：立板竖槽 → 横槽 → 吊臂 U 型腔 → 吊舱", "-",
             present=("meter", "body"), check_path=False, tool="镊子",
             note="吊臂是**下开口**的 U 型槽，线从下方塞进去即可，不用穿。"),
        Step(5, "装 LED 驱动板（AO3400 + 电阻，15×20 洞洞板）到吊舱下部电子舱", "-",
             present=("meter", "body"), check_path=False, tool="热熔胶",
             note="放在板卡下方的空腔里，远离光学部分，散热和电子件都不靠近镜头。"),
        Step(6, "把 FPC 天线贴进 +X 内壁的定位框，馈线接 IPEX 座", "-",
             present=("meter", "body"), check_path=False,
             note="馈点朝上，尾线沿内壁走到板卡位置。"),
        Step(7, "从吊舱后方推入 ESP32-S3-CAM", "board",
             path=((0, 26, 0), (0, 14, 0), (0, 6, 0), (0, 2, 0), (0, 0, 0)),
             present=("meter", "body"),
             tool="徒手",
             note="板下缘先落在承台上，两侧沿导轨往前推；最后 6mm 时"
                  "摄像头模组会自己被方腔的导向倒角引进去。"
                  "★ SD 卡（如果还用）必须**在这一步之前**插好，装上以后够不着。",
             pokayoke="★ 前腔在 Z 方向不对称（SD 卡座偏上），板子上下颠倒或"
                      "前后调头都进不去（自检 POKA-04/05）。"),
        Step(8, "把 EVA 泡棉贴在滑盖内侧", "-", present=("meter", "body", "board"),
             check_path=False, tool="双面胶",
             note=f"泡棉厚 {c.cover_foam_t:.0f}mm，装上滑盖后把板卡顶向前止挡面。"),
        Step(9, "滑盖从吊舱顶部插入，竖直下滑到底", "slide_cover",
             path=((0, 0, 78), (0, 0, 40), (0, 0, 12), (0, 0, 3), (0, 0, 0)),
             present=("meter", "body", "board"),
             note="对准顶部开口往下推，到底会有明显的落座感。",
             pokayoke="★ +X 滑槽里有一条定位筋，盖板装反（上下颠倒或前后调头）"
                      "都会被筋顶住（自检 POKA-02）。"),
        Step(10, "接 5V 电源线（底部水滴孔进线）", "-",
             present=("meter", "body", "board", "slide_cover"), check_path=False,
             note="进线孔朝下，防止楼道结露沿线倒灌。本地并 470~1000µF + 100nF。"),
        Step(11, "【台面】把前表面镜从 T 型槽端口滑入托板", "mirror_glass",
             path=((0, 0, 0),), present=("mirror_holder",), check_path=False,
             tool="徒手 + 手套",
             note="镀膜面不可擦拭，只能气吹；划伤即报废，建议多备 2 片。",
             pokayoke="镜片是矩形玻璃，两面都能装 —— **这一处做不成几何防呆**。"
                      "托板横梁上刻了 COATED SIDE DOWN，装之前对一眼。"),
        Step(12, "把镜片托板垂直落到四根定位销上", "mirror_holder",
             path=((0, 30, 8), (0, 20, 8), (0, 10, 8), (0, 0, 8), (0, 0, 3), (0, 0, 0)),
             present=("meter", "body", "board", "slide_cover"),
             note="先从 +Y 方向平移进来，再垂直落下。四根销进孔后托板自然坐平。",
             pokayoke="★ 前后销直径不同（后 Ø4 / 前 Ø5），前后调头装不上"
                      "（自检 POKA-01）。"),
    ]


def service_sequence(cfg: Config) -> list[Step]:
    """
    每月人工抄表的动作（**只动镜片托板**）。

    这是整个设计里唯一的日常操作，必须在没有工具、光线不好、
    人站在楼梯上的条件下可靠完成。
    """
    return [
        Step(1, "握住托板横梁，垂直上提 8mm 脱离定位销", "mirror_holder",
             path=((0, 0, 0), (0, 0, 3), (0, 0, 8)),
             present=("meter", "body", "board", "slide_cover"),
             note="横梁在 y=28~34，越过了立板前缘（y=22），手伸得进去。抬 8mm 后销全部脱开，支承片底面（z=28）也越过了灯座凸台（顶 z≈27）。"),
        Step(2, "提起后沿 +Y 平移取出", "mirror_holder",
             path=((0, 0, 8), (0, 10, 8), (0, 20, 8), (0, 30, 8)),
             present=("meter", "body", "board", "slide_cover"),
             note="平移到 +Y 30mm 就已经完全脱开立板和吊臂；再往前就会碰到吊舱"
                  "（吊舱前表面在 y=76.5，提手横梁在 y=28~34），所以到这里就该"
                  "把托板端出来，而不是继续平推。"),
        Step(3, "人工读数 / 拍照", "-", check_path=False, note="相机此时视野被完全打开。"),
        Step(4, "原路放回，确认四根销都进孔、托板不晃", "mirror_holder",
             path=((0, 30, 8), (0, 20, 8), (0, 10, 8), (0, 0, 8), (0, 0, 0)),
             present=("meter", "body", "board", "slide_cover"),
             note="★ 放回后 ROI 不需要重新标定 —— 相机、镜头、抱箍全程没动。"),
    ]


def teardown_sequence(cfg: Config) -> list[Step]:
    """整机拆下（换表、维修时）。"""
    c = cfg.case
    lift = c.collar_z1 - c.collar_z0 + 2.0
    return [
        Step(1, "取下镜片托板（同抄表流程）", "mirror_holder",
             path=((0, 0, 0), (0, 0, 8), (0, 15, 8), (0, 30, 8)),
             present=("meter", "body", "board", "slide_cover")),
        Step(2, "松开两颗 M4", "-", check_path=False, tool="徒手"),
        Step(3, f"整机垂直上提 {lift:.1f}mm 脱离银圈", "body",
             path=((0, 0, 0), (0, 0, lift / 2), (0, 0, lift)),
             present=("meter",), ignore=("meter",),
             note="上方净空只有 70mm，这一步的行程必须提前核算（自检 SEQ-04）。"),
    ]
