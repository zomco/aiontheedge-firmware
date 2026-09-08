# -*- coding: utf-8 -*-
"""
文档生成 —— ``ASSEMBLY.md`` 从 :mod:`wmcase.assembly` 直接生成。

为什么要生成而不是手写
----------------------
装配说明书和模型很容易各说各话：模型改了顺序，文档还写着老顺序，
而**文档正是现场唯一会被照着做的东西**。

把顺序写成数据（`assembly.Step`），文档和自检 (`checks/sequence.py`)
用的就是同一份来源，不可能不一致。
"""

from __future__ import annotations

import os
from datetime import datetime

from .assembly import Step, install_sequence, service_sequence, teardown_sequence
from .params import Config


def _table(steps: list[Step], title: str, intro: str) -> list[str]:
    lines = [f"## {title}", "", intro, ""]
    for st in steps:
        lines.append(f"### {st.index}. {st.name}")
        lines.append("")
        lines.append(f"- **工具**：{st.tool}")
        if st.note:
            lines.append(f"- **要点**：{st.note}")
        if st.pokayoke:
            lines.append(f"- **防呆**：{st.pokayoke}")
        if st.check_path and st.part != "-" and len(st.path) > 1:
            path = " → ".join(f"({dx:g}, {dy:g}, {dz:g})" for dx, dy, dz in st.path)
            lines.append(f"- **运动路径**（相对最终位置的偏移，mm）：{path}")
            lines.append("  ．这条路径**已经过碰撞仿真**（自检 SEQ 分类），"
                         "沿途和全程净空都验过。")
        lines.append("")
    return lines


def build_assembly_doc(cfg: Config) -> str:
    """生成 ASSEMBLY.md 的全文。"""
    c = cfg.case
    lift = c.collar_z1 - c.collar_z0 + 2.0
    lines = [
        "# 装配与维护说明",
        "",
        "> ⚠ **本文件由 `python build.py doc` 从 `wmcase/assembly.py` 自动生成，"
        "不要手改。**",
        "> 改装配顺序请改 `assembly.py`，那里的顺序同时也是自检 `SEQ` 分类的输入，"
        "文档和模型不会各说各话。",
        "",
        f"生成时间：{datetime.now():%Y-%m-%d %H:%M}",
        "",
        "---",
        "",
        "## 开始之前",
        "",
        "**需要准备的外购件**",
        "",
        "| 件 | 规格 | 数量 |",
        "|---|---|---|",
        "| ESP32-S3-CAM | 40×27，IPEX 座 | 1 |",
        f"| 前表面反射镜 | {cfg.optics.mirror_l:.0f}×{cfg.optics.mirror_w:.0f}"
        f"×{cfg.optics.mirror_t:.0f}，铝+SiO₂ | 1（**建议备 2 片**） |",
        "| 5mm 草帽白光 LED | 120° 全角 | 2 |",
        "| M4 蝶形螺丝 | | 2 |",
        f"| EVA 泡棉 | {c.cover_foam_t:.0f}mm 厚，约 27×40 | 1 |",
        "| LED 驱动板 | AO3400 + 100Ω×2 + 100kΩ，15×20 洞洞板 | 1 |",
        "| FPC 天线 | 65×15，IPEX 尾线 50mm | 1 |",
        "",
        "**三个打印件**：`body` / `mirror_holder` / `slide_cover`",
        "",
        "**注意事项**",
        "",
        "1. **反射镜的镀膜面不可擦拭**，只能气吹；划伤即报废。全程戴手套。",
        "2. 识别镀膜面：**用笔尖轻触镜面，笔尖和倒影没有间隙的那一面就是镀膜面。**",
        f"3. 表盘上方净空只有 {cfg.meter.headroom:.0f}mm，"
        f"整机拆装需要 {lift:.1f}mm 的垂直行程，动作要留出空间。",
        "",
        "---",
        "",
    ]
    lines += _table(install_sequence(cfg), "整机装配",
                    "顺序**不是随便排的**：抱箍必须最先固定（后面所有对位以它为基准）；"
                    "板卡必须在滑盖之前（滑盖封住的正是板卡的插入口）；"
                    "镜片托板必须最后（它是每月要拆、也最脆的件）。")
    lines += ["---", ""]
    lines += _table(service_sequence(cfg), "每月人工抄表",
                    "**只动镜片托板。** 相机、镜头、抱箍全程不动，"
                    "所以放回去以后 ROI 不需要重新标定。")
    lines += ["---", ""]
    lines += _table(teardown_sequence(cfg), "整机拆下",
                    "换表、维修时用。")
    lines += [
        "---",
        "",
        "## 装完之后的自查",
        "",
        "- [ ] 用手转整机，抱箍不打滑",
        "- [ ] 镜片托板放上去不晃、四根销都进孔",
        "- [ ] 滑盖推到底有落座感，左右不晃",
        "- [ ] 从 +Y 方向看，镜头孔里能看见反射的表盘",
        "- [ ] 上电后两颗 LED 都亮，表盘上没有明显的高光斑",
        "- [ ] 拍一张图，对照 `out/sensor_view.svg`：字轮窗在画面里、字够大",
        "- [ ] **记住画面是左右镜像的**（光路含 1 次反射），按镜像后的画面框 ROI",
        "",
    ]
    return "\n".join(lines)


def write_assembly_doc(cfg: Config, path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(build_assembly_doc(cfg))
    return path
