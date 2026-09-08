# -*- coding: utf-8 -*-
"""
报告 —— 把自检结果和光路仿真变成**人和 AI 都能直接用**的东西。

产出三样：

* **终端表格**：跑一次立刻能看
* ``report.md`` / ``report.json``：进 git，做版本间 diff；AI 协作时直接贴给对方
* ``sensor_view.svg``：**模拟相机画面**——把表盘上的采样点经 45° 镜投影到
  传感器画幅上画出来。这是"验证 ESP32-S3-CAM 能读到表盘"这件事唯一
  能给人看的东西；被挡住的点会画成红色，一眼就知道哪块读不到。
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime

from build123d import Vector

from . import optics as ox
from .checks import CATEGORIES, ERROR, INFO, WARN, RunReport
from .model import Design


# =============================================================================
#  终端
# =============================================================================

def print_report(report: RunReport) -> None:
    width = 66
    print("\n" + "=" * (width + 26))
    print("  自检结果")
    print("=" * (width + 26))
    current = None
    for r in report.results:
        if r.category != current:
            current = r.category
            print(f"\n  ── {r.category}  {CATEGORIES.get(r.category, '')} " + "─" * 40)
        flag = "PASS" if r.passed else ("FAIL" if r.severity == ERROR else
                                        "WARN" if r.severity == WARN else "INFO")
        title = r.title if len(r.title) <= width else r.title[:width - 1] + "…"
        print(f"  [{flag}] {r.id:<11} {title.ljust(width)}  {r.detail}")
    print("\n" + "=" * (width + 26))
    n_warn = sum(1 for r in report.results if not r.passed and r.severity == WARN)
    print(f"  合计 {len(report.results)} 项 · 阻断性失败 {report.n_block} · 警告 {n_warn}")
    print("=" * (width + 26) + "\n")


# =============================================================================
#  Markdown / JSON
# =============================================================================

def write_markdown(design: Design, report: RunReport, path: str) -> str:
    cfg = design.cfg
    o = cfg.optics
    lines = [
        "# 自检报告",
        "",
        f"生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}",
        f"开发板：`{design.board_ref.source}`（可信度 {design.board_ref.trust}）",
        f"水表：{cfg.meter.model}　DN{cfg.meter.dn}　银圈 Ø{cfg.meter.bezel_od}",
        "",
        "## 结论",
        "",
        f"- 共 **{len(report.results)}** 项检查",
        f"- 阻断性失败 **{report.n_block}** 项"
        + ("（**不允许导出/打印**）" if report.n_block else "（可以导出）"),
        f"- 警告 **{sum(1 for r in report.results if not r.passed and r.severity == WARN)}** 项",
        "",
        "## 关键数值",
        "",
        "| 量 | 值 |",
        "|---|---|",
        f"| 总光程 | {o.path:.0f} mm |",
        f"| 虚拟相机位置 | {o.virtual_cam} |",
        f"| 单字符成像 | {o.digit_px:.1f} px |",
        f"| 景深半宽 | ±{o.dof_half_mm:.1f} mm |",
        f"| 镜片光学需求 | {o.need_mirror_len:.1f} × {o.need_mirror_width:.1f} mm |",
        f"| 镜片采购规格 | {o.mirror_l:.0f} × {o.mirror_w:.0f} × {o.mirror_t:.0f} mm |",
        f"| 抱箍单边过盈 | {cfg.case.collar_rib_interf:.2f} mm |",
        f"| 打印件体积 | "
        + "，".join(f"{n} {p.volume / 1000:.1f} cm³"
                    for n, p in design.printed_parts.items()) + " |",
        "",
    ]
    for cat, cname in CATEGORIES.items():
        rows = [r for r in report.results if r.category == cat]
        if not rows:
            continue
        lines += [f"## {cat} · {cname}", "", "| | 编号 | 检查项 | 数值 |", "|---|---|---|---|"]
        for r in rows:
            flag = "✅" if r.passed else ("❌" if r.severity == ERROR else
                                          "⚠️" if r.severity == WARN else "ℹ️")
            lines.append(f"| {flag} | `{r.id}` | {r.title} | {r.detail} |")
        lines.append("")
        # 失败项把"为什么有这条规则"也带上，方便下一个人/AI 判断严重性
        for r in rows:
            if not r.passed and r.why:
                lines += [f"> **{r.id} 失败** —— 这条规则存在的理由：{r.why}", ""]

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return path


def write_json(design: Design, report: RunReport, path: str) -> str:
    data = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "board": {"source": design.board_ref.source, "trust": design.board_ref.trust},
        "summary": {
            "total": len(report.results),
            "blocking": report.n_block,
            "warnings": sum(1 for r in report.results
                            if not r.passed and r.severity == WARN),
            "passed": report.passed,
        },
        "volumes_cm3": {n: round(p.volume / 1000, 2)
                        for n, p in design.printed_parts.items()},
        "results": [
            {"id": r.id, "category": r.category, "title": r.title,
             "passed": r.passed, "severity": r.severity, "detail": r.detail}
            for r in report.results
        ],
        "timings_s": {k: round(v, 2) for k, v in report.timings.items()},
    }
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    return path


# =============================================================================
#  模拟传感器画面
# =============================================================================

#: 爆炸图配色：按装配顺序渐变，水表用灰色
_PART_COLORS = {
    "00_meter_mock": "#9aa0a6",
    "01_body": "#5b8ff9",
    "03_leds": "#f6bd16",
    "07_esp32s3cam": "#5ad8a6",
    "08_eva_foam": "#d3d3d3",
    "09_slide_cover": "#945fb9",
    "11_mirror_glass": "#7cd6f9",
    "12_mirror_holder": "#e8684a",
    "99_assembly_guides": "#333333",
}


def write_assembly_views(design: Design, path: str, exploded: bool = True,
                         tess_tol: float = 4.0) -> str:
    """
    爆炸图的**正交投影**（正视 + 侧视），直接出 SVG。

    为什么要有它：装配体是 STEP，看它需要 CAD 或网格查看器。
    而"这个件到底装在哪、朝哪个方向装进去"这种问题，评审时问得最多，
    却最不值得为它开一次 CAD。所以顺手出一张能贴进 PR、贴进文档的图。

    做法很土：把每个件粗三角化（默认 1.5mm 容差），把三角形正交投影到
    XZ 面（正视，沿 +Y 看）和 YZ 面（侧视，沿 −X 看），按件上色填充。
    不做消隐、不做光照 —— 它的用途是**看位置关系**，不是渲染效果图。

    三角化容差刻意取得很粗（4mm）：1.5mm 时这张图有 4.5MB，
    而它要回答的问题（哪个件在哪、朝哪装）在 4mm 下一点没损失。
    坐标也取整到整数像素，同样是为了压体积。
    """
    parts = list((design.exploded() if exploded else design.assembly()).children)

    # 先把所有件三角化，同时统计投影范围
    meshes = []
    for ch in parts:
        try:
            verts, tris = ch.tessellate(tess_tol)
        except Exception:  # noqa: BLE001
            continue
        meshes.append((ch.label, verts, tris))

    if not meshes:
        raise RuntimeError("装配体三角化失败，出不了投影图")

    def bounds(idx_a, idx_b):
        lo_a = lo_b = 1e9
        hi_a = hi_b = -1e9
        for _lbl, verts, _tris in meshes:
            for v in verts:
                a, b = (v.X, v.Y, v.Z)[idx_a], (v.X, v.Y, v.Z)[idx_b]
                lo_a, hi_a = min(lo_a, a), max(hi_a, a)
                lo_b, hi_b = min(lo_b, b), max(hi_b, b)
        return lo_a, hi_a, lo_b, hi_b

    #  正视：横轴 = X，纵轴 = Z（沿 +Y 看进去）
    #  侧视：横轴 = Y，纵轴 = Z（沿 −X 看进去）—— 这一张最能说明装配方向
    views = [("正视图（沿 +Y 看）", 0, 2), ("侧视图（沿 −X 看）", 1, 2)]
    scale = 1.35
    pad = 26
    panels = []
    total_w = 0.0
    max_h = 0.0
    for title, ia, ib in views:
        lo_a, hi_a, lo_b, hi_b = bounds(ia, ib)
        w = (hi_a - lo_a) * scale + 2 * pad
        h = (hi_b - lo_b) * scale + 2 * pad
        panels.append((title, ia, ib, lo_a, hi_a, lo_b, hi_b, w, h))
        total_w += w
        max_h = max(max_h, h)

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w:.0f}" '
           f'height="{max_h + 96:.0f}" font-family="sans-serif">',
           f'<rect width="{total_w:.0f}" height="{max_h + 96:.0f}" fill="#fbfbfc"/>']

    x_origin = 0.0
    for title, ia, ib, lo_a, hi_a, lo_b, hi_b, w, h in panels:
        out.append(f'<text x="{x_origin + pad:.0f}" y="20" font-size="14" '
                   f'fill="#24292f">{title}</text>')

        def px(v, _ia=ia, _ib=ib, _lo_a=lo_a, _hi_b=hi_b, _x=x_origin):
            comp = (v.X, v.Y, v.Z)
            # 纵轴翻转：SVG 的 y 向下，而 Z 向上
            return (_x + pad + (comp[_ia] - _lo_a) * scale,
                    28 + pad + (_hi_b - comp[_ib]) * scale)

        for label, verts, tris in meshes:
            color = _PART_COLORS.get(label, "#888888")
            opacity = 0.95 if label.startswith("99_") else 0.55
            polys = []
            seen = set()
            for ia_, ib_, ic_ in tris:
                p0, p1, p2 = px(verts[ia_]), px(verts[ib_]), px(verts[ic_])
                key = (round(p0[0]), round(p0[1]), round(p1[0]), round(p1[1]),
                       round(p2[0]), round(p2[1]))
                if key in seen:          # 正背面投影完全重合，只画一次
                    continue
                seen.add(key)
                polys.append(f"M{key[0]} {key[1]}L{key[2]} {key[3]}"
                             f"L{key[4]} {key[5]}Z")
            out.append(f'<path d="{"".join(polys)}" fill="{color}" '
                       f'fill-opacity="{opacity}" stroke="none"/>')
        x_origin += w

    # 图例：装配顺序 + 配色
    from .assembly import install_sequence
    steps = {st.part: st for st in install_sequence(design.cfg)}
    key_map = {"01_body": "body", "03_leds": "leds", "07_esp32s3cam": "board",
               "09_slide_cover": "slide_cover", "11_mirror_glass": "mirror_glass",
               "12_mirror_holder": "mirror_holder"}
    y = max_h + 46
    x = pad
    for label in sorted(_PART_COLORS):
        color = _PART_COLORS[label]
        step = steps.get(key_map.get(label, ""))
        text = label[3:] if len(label) > 3 else label
        if step is not None:
            text = f"{label[:2]} {text}"
        out.append(f'<rect x="{x:.0f}" y="{y - 10:.0f}" width="12" height="12" '
                   f'fill="{color}"/>')
        out.append(f'<text x="{x + 17:.0f}" y="{y:.0f}" font-size="12" '
                   f'fill="#24292f">{text}</text>')
        x += 150
        if x > total_w - 150:
            x = pad
            y += 20
    out.append(f'<text x="{pad}" y="{max_h + 88:.0f}" font-size="12" fill="#57606a">'
               f'子件编号 = 装配顺序（见 ASSEMBLY.md）；深色细杆 = 引导杆，'
               f'指向各件的安装位置，杆的方向就是装入方向</text>')
    out.append("</svg>")

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))
    return path


def write_sensor_view(design: Design, path: str, n_rim: int = 48) -> str:
    """
    画出"相机会看到什么"。

    做法：对表盘上的采样点做完整光线追踪（表盘 → 45°镜 → 镜头），
    通过的点按虚拟相机的针孔投影落到画幅上，被挡住的点画成红色。

    画面里额外标了两件事：

    * **画幅是镜像的** —— 一次反射会左右翻转，固件侧标 ROI 时必须知道；
    * 表盘可视圆和字轮窗的位置，方便直接判断"字够不够大、在不在画面里"。
    """
    cfg = design.cfg
    o = cfg.optics
    blockers = {"body": design.body, "mirror_holder": design.mirror_holder}

    pts = ox.sample_dial_points(cfg, n_rim=n_rim, n_ring=3)
    traced = [(tag, x, y, ox.trace_dial_point(cfg, blockers, design.mirror_glass, x, y))
              for x, y, tag in pts]

    W, H = o.sensor_px_h, o.sensor_px_v
    scale = 0.5                                   # SVG 里 1px 传感器 = 0.5 单位
    sw, sh = W * scale, H * scale
    margin = 40

    def to_svg(x: float, y: float) -> tuple[float, float]:
        u, v = ox.sensor_uv(cfg, Vector(x, y, 0))
        # 一次反射 → 画面左右镜像，这里如实画出来
        return (margin + sw / 2 * (1 - u), margin + sh / 2 * (1 - v))

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{sw + 2 * margin:.0f}" '
        f'height="{sh + 2 * margin + 90:.0f}" font-family="sans-serif">',
        f'<rect x="0" y="0" width="{sw + 2 * margin:.0f}" '
        f'height="{sh + 2 * margin + 90:.0f}" fill="#f7f7f8"/>',
        f'<rect x="{margin}" y="{margin}" width="{sw:.0f}" height="{sh:.0f}" '
        f'fill="#111318" stroke="#444" stroke-width="1"/>',
    ]

    # 表盘可视圆
    ring = [to_svg(cfg.meter.dial_r * math.cos(2 * math.pi * i / 180),
                   cfg.meter.dial_r * math.sin(2 * math.pi * i / 180))
            for i in range(180)]
    parts.append('<polygon points="'
                 + " ".join(f"{a:.1f},{b:.1f}" for a, b in ring)
                 + '" fill="none" stroke="#3fb950" stroke-width="2"/>')

    # ROI 圆（设计留的余量）
    ring2 = [to_svg(o.roi_r * math.cos(2 * math.pi * i / 180),
                    o.roi_r * math.sin(2 * math.pi * i / 180))
             for i in range(180)]
    parts.append('<polygon points="'
                 + " ".join(f"{a:.1f},{b:.1f}" for a, b in ring2)
                 + '" fill="none" stroke="#58a6ff" stroke-width="1" '
                   'stroke-dasharray="6 4"/>')

    # 字轮窗（5 位字轮，宽 5×digit_w）
    dw = o.digit_w_mm
    win = [(-2.5 * dw, 5.0), (2.5 * dw, 5.0), (2.5 * dw, 11.0), (-2.5 * dw, 11.0)]
    parts.append('<polygon points="'
                 + " ".join("%.1f,%.1f" % to_svg(x, y) for x, y in win)
                 + '" fill="none" stroke="#f0883e" stroke-width="2"/>')

    # 采样点
    n_ok = 0
    for _tag, x, y, res in traced:
        sx, sy = to_svg(x, y)
        if res.ok:
            n_ok += 1
            parts.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="2.2" fill="#3fb950"/>')
        else:
            parts.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="3.2" fill="#f85149"/>')

    # 图例
    dy = margin + sh + 24
    digit_px_svg = o.digit_px * scale
    legend = [
        f"模拟画幅 {W}×{H}　总光程 {o.path:.0f}mm　单字符 {o.digit_px:.1f}px",
        f"光线追踪 {n_ok}/{len(traced)} 通过　"
        f"绿=可见　红=被挡　绿圈=可视表盘 Ø{cfg.meter.dial_visible_d}　"
        f"蓝虚线=设计 ROI R{o.roi_r:.0f}　橙框=字轮窗",
        "⚠ 画面左右镜像（光路含 1 次反射）—— 固件标 ROI 时必须按这个方向",
    ]
    for i, text in enumerate(legend):
        parts.append(f'<text x="{margin}" y="{dy + i * 20:.0f}" font-size="13" '
                     f'fill="#24292f">{text}</text>')
    # 单字符尺度条
    parts.append(f'<rect x="{margin}" y="{margin + sh - 24:.0f}" '
                 f'width="{digit_px_svg:.1f}" height="6" fill="#f0883e"/>')
    parts.append(f'<text x="{margin + digit_px_svg + 6:.0f}" y="{margin + sh - 17:.0f}" '
                 f'font-size="12" fill="#f0883e">1 个数字 ≈ {o.digit_px:.0f}px</text>')
    parts.append("</svg>")

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(parts))
    return path
