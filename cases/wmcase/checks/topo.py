# -*- coding: utf-8 -*-
"""拓扑自检 —— 性价比最高的一类，一行代码消灭一整个错误类别。"""

from __future__ import annotations

from . import ERROR, Result, rule


@rule("TOPO-01", "TOPO", "每个打印件都是单一连通实体",
      why="CAD 的 union 对不相接的实体一样能编译通过，没有任何警告。"
          "v0.5~v1.0 连续多版出现『零件全部悬空』，每次都靠人看渲染图才发现"
          "（DESIGN_NOTES §7.8）。这条检查在 build123d 版首次运行时立刻抓到 6 个孤立实体。")
def single_solid(design):
    for name, part in design.printed_parts.items():
        n = len(part.solids())
        yield Result("TOPO-01", "TOPO", f"{name} 是单一连通实体", n == 1,
                     f"solids={n}", single_solid._rule["why"], ERROR)


@rule("TOPO-02", "TOPO", "每个打印件拓扑有效",
      why="OCC 的布尔运算在共面/自相交时会产出『看起来对但不合法』的形体，"
          "切片器可能直接崩溃或产生错误路径。EPS 微元就是为了避免共面。")
def valid(design):
    for name, part in design.printed_parts.items():
        yield Result("TOPO-02", "TOPO", f"{name} 拓扑有效", bool(part.is_valid),
                     "", valid._rule["why"], ERROR)


@rule("TOPO-04", "TOPO", "每个打印件能网格化成合法 3MF",
      why="**STEP 合法不等于网格合法**，而切片器吃的是网格。"
          "本项目实测过一次：吊臂的 U 型走线腔骑在吊舱型腔边界上（X=17），"
          "两个减法体各切掉一半，中间留下零点几毫米的薄壁。"
          "`is_valid=True`、`solids==1`、干涉检查全过、STEP 导出正常 —— "
          "只有 lib3mf 在网格化时报 `3mf mesh is invalid`。"
          "换句话说，前面那些拓扑检查**全都拦不住它**。"
          "\n"
          "所以这条不是重复检查，它管的是另一个环节：能不能真的送进切片器。"
          "教训推广一下：**两个减法体不要只在一个平面上相切**，"
          "宁可让它们有几毫米的体积重叠。")
def meshable(design):
    from build123d import Mesher, Unit

    from . import ERROR as _E
    for name, part in design.printed_parts.items():
        try:
            mesher = Mesher(unit=Unit.MM)
            mesher.add_shape(part, linear_deflection=0.03, angular_deflection=0.15)
            ok, detail = True, f"三角面 {len(part.tessellate(0.2)[1])} 个"
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        yield Result("TOPO-04", "TOPO", f"{name} 可网格化为 3MF", ok, detail,
                     meshable._rule["why"], _E)


@rule("TOPO-03", "TOPO", "每个打印件体积为正且量级合理",
      why="体积异常（0 或暴涨）说明某次布尔把整个件吃掉了或没减掉，"
          "这种错误后续的干涉检查反而查不出来（空实体和谁都不干涉）。")
def volume_sane(design):
    expect = {"body": (60.0, 220.0), "mirror_holder": (10.0, 60.0), "slide_cover": (3.0, 25.0)}
    for name, part in design.printed_parts.items():
        v = part.volume / 1000.0
        lo, hi = expect.get(name, (0.1, 1e6))
        yield Result("TOPO-03", "TOPO", f"{name} 体积在合理区间", lo <= v <= hi,
                     f"{v:.1f} cm³（期望 {lo}~{hi}）", volume_sane._rule["why"], ERROR)
