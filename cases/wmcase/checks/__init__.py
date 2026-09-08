# -*- coding: utf-8 -*-
"""
自检框架 —— 让设计错误在**机器上**暴露，而不是在打印件上。

设计哲学（三条，是本项目最贵的经验换来的）
------------------------------------------

**1. 拓扑检查是性价比最高的。**
   ``len(part.solids()) == 1`` 这一行，消灭了折磨了十几个版本的整个错误类别
   （零件悬空）。CAD 的 union 对不相接的实体一样能编译通过，没有任何警告。
   任何 CAD 脚本都应该有这一条。

**2. 不只查"不干涉"，还要证明"约束成立"。**
   ``A ∩ B = 0`` 只说明装得进去，不说明装上后不会掉。所以每个约束都配一条
   **反向测试**：往被约束的方向推一点，**必须**产生干涉::

       正向：主体 ∩ 托板 = 0          反向：托板下沉 0.5mm 应当干涉
       正向：主体 ∩ 滑盖 = 0          反向：滑盖前后各推 0.6mm 应当干涉
       正向：托板 ∩ 镜片 = 0          反向：镜片外推 1.2mm 应当干涉

   v2.3"托台顶死托板"那个错误，**只有反向测试能自动抓住**。

**3. 把空间想象题变成布尔运算。**
   "会不会挡光"靠脑补是不可靠的（本项目的结构性错误 100% 是人看渲染图
   发现的）。把光路做成实体、把光线做成射线求交，判据就变成可计算的。

规则元数据
----------
每条规则都要写 ``why``——它存在的**理由**，通常指向 DESIGN_NOTES 里的某个坑。
报告会把 ``why`` 一起打出来，这样下一个接手的人（或 AI）看到 FAIL
不用去猜"这条到底在防什么"。
"""

from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field
from typing import Callable, Iterable, Iterator

ERROR = "error"      # 必须修，不修不许导出
WARN = "warn"        # 可以带着上机，但要知道自己在冒什么险
INFO = "info"        # 只是把数值报出来，不判定

#: 分类 → 中文名（报告里分组用）
CATEGORIES = {
    "TOPO": "拓扑",
    "FIT": "配合与干涉",
    "CONS": "约束有效性",
    "SEQ": "装配 / 拆卸顺序",
    "OPT": "光学",
    "LED": "照明",
    "DIM": "尺寸链与净空",
    "DFAM": "可制造性",
    "POKA": "防呆",
    "WIRE": "走线",
}


@dataclass
class Result:
    """一条自检的结论。"""

    id: str
    category: str
    title: str
    passed: bool
    detail: str = ""
    why: str = ""
    severity: str = ERROR

    @property
    def ok(self) -> bool:
        """INFO 级永远算通过；WARN 不阻断导出。"""
        return self.passed or self.severity == INFO

    @property
    def blocking(self) -> bool:
        return (not self.passed) and self.severity == ERROR


#: 全部已注册的规则函数
REGISTRY: list[Callable] = []


def rule(rid: str, category: str, title: str, why: str = "", severity: str = ERROR):
    """
    注册一条自检规则。

    被装饰的函数签名是 ``fn(design) -> bool | (bool, str) | Iterable[Result]``：

    * 返回 ``bool``            —— 用装饰器上的标题和分类生成一条 Result
    * 返回 ``(bool, detail)``  —— 同上，附带一行数值说明
    * 返回 ``Iterable[Result]`` —— 规则自己产出多条（比如逐点、逐步骤）
    """

    def deco(fn: Callable) -> Callable:
        fn._rule = dict(rid=rid, category=category, title=title, why=why, severity=severity)
        REGISTRY.append(fn)
        return fn

    return deco


def _normalise(fn, out) -> Iterator[Result]:
    meta = fn._rule
    if isinstance(out, tuple) and len(out) == 2 and isinstance(out[0], (bool, int)):
        passed, detail = out
        yield Result(meta["rid"], meta["category"], meta["title"], bool(passed),
                     str(detail), meta["why"], meta["severity"])
    elif isinstance(out, (bool, int)):
        yield Result(meta["rid"], meta["category"], meta["title"], bool(out),
                     "", meta["why"], meta["severity"])
    else:
        for r in out:
            yield r


@dataclass
class RunReport:
    results: list[Result] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)

    @property
    def n_fail(self) -> int:
        return sum(1 for r in self.results if not r.ok)

    @property
    def n_block(self) -> int:
        return sum(1 for r in self.results if r.blocking)

    @property
    def passed(self) -> bool:
        return self.n_block == 0


def run_all(design, only: Iterable[str] | None = None,
            skip: Iterable[str] | None = None, progress: bool = True) -> RunReport:
    """
    跑全部规则。

    :param only:     只跑这些分类（如 ``["OPT", "SEQ"]``）
    :param skip:     跳过这些分类（SEQ 最慢，快速迭代时先跳它）
    :param progress: 边跑边打进度。整套要好几分钟，没有进度条很像卡死。
    """
    # 触发各规则模块的注册
    from . import cons, dfam, dim, fit, led, optical, pokayoke, sequence, topo, wire  # noqa: F401

    only = set(only) if only else None
    skip = set(skip) if skip else set()

    todo = [fn for fn in REGISTRY
            if (not only or fn._rule["category"] in only)
            and fn._rule["category"] not in skip]

    report = RunReport()
    for i, fn in enumerate(todo, 1):
        if progress:
            print(f"\r    [{i:>2}/{len(todo)}] {fn._rule['rid']:<10} "
                  f"{fn._rule['title'][:38]:<38}", end="", flush=True)
        t0 = time.time()
        try:
            out = fn(design)
            report.results.extend(_normalise(fn, out))
        except Exception as exc:  # noqa: BLE001
            # 规则自己崩了也是一种失败——绝不能静默跳过
            meta = fn._rule
            report.results.append(Result(
                meta["rid"], meta["category"], meta["title"], False,
                f"规则执行异常：{type(exc).__name__}: {exc}\n"
                + traceback.format_exc(limit=3).strip().replace("\n", " | "),
                meta["why"], meta["severity"]))
        report.timings[fn._rule["rid"]] = time.time() - t0

    if progress:
        print("\r" + " " * 70 + "\r", end="", flush=True)
    report.results.sort(key=lambda r: (list(CATEGORIES).index(r.category)
                                       if r.category in CATEGORIES else 99, r.id))
    return report


# =============================================================================
#  共用工具
# =============================================================================

def volume(shape) -> float:
    try:
        return float(shape.volume)
    except Exception:  # noqa: BLE001
        return 0.0


def _bbox_disjoint(a, b) -> bool:
    """
    包围盒快筛。布尔求交在复杂形体上要好几秒，而包围盒只要几毫秒；
    路径仿真里大量的"根本挨不着"的组合可以在这里直接判掉。
    """
    try:
        ba, bb = a.bounding_box(), b.bounding_box()
    except Exception:  # noqa: BLE001
        return False
    return (ba.max.X < bb.min.X or bb.max.X < ba.min.X
            or ba.max.Y < bb.min.Y or bb.max.Y < ba.min.Y
            or ba.max.Z < bb.min.Z or bb.max.Z < ba.min.Z)


def inter_vol(a, b) -> float:
    """两实体的干涉体积（mm³）。任何异常都返回 0，由调用方的判据去兜。"""
    if _bbox_disjoint(a, b):
        return 0.0
    try:
        return volume(a & b)
    except Exception:  # noqa: BLE001
        return 0.0


def fmt(v: float, unit: str = "mm³") -> str:
    return f"{v:.2f} {unit}"
