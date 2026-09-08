# -*- coding: utf-8 -*-
"""
导出 —— STEP（可再编辑）+ 3MF（可直接切片）+ 装配体。

为什么两种格式都要
------------------
* **STEP**：给下一个人/AI 用 CAD 打开、量尺寸、做局部改动的载体；
* **3MF**：水密网格，Bambu Studio 里拖进去就能切，不用再转一道。

``dfam_rules.md §6.4`` 要求"每个脚本都以 export_3mf 结尾"，这里照办。
"""

from __future__ import annotations

import os

from build123d import Mesher, Part, Unit, export_step

from .model import Design

#: 网格化精度。0.03/0.15 打出来看不出多边形，文件也不大。
LINEAR_DEFLECTION = 0.03
ANGULAR_DEFLECTION = 0.15


def export_part(part: Part, outdir: str, name: str) -> dict[str, str]:
    os.makedirs(outdir, exist_ok=True)
    step_path = os.path.join(outdir, f"{name}.step")
    mesh_path = os.path.join(outdir, f"{name}.3mf")
    export_step(part, step_path)
    mesher = Mesher(unit=Unit.MM)
    mesher.add_shape(part, linear_deflection=LINEAR_DEFLECTION,
                     angular_deflection=ANGULAR_DEFLECTION)
    mesher.write(mesh_path)
    return {"step": step_path, "3mf": mesh_path}


def export_all(design: Design, outdir: str, assembly: bool = True,
               illustrative: bool = False) -> list[str]:
    """导出三个打印件（STEP + 3MF），可选装配体 STEP。返回文件清单。"""
    written: list[str] = []
    for name, part in design.printed_parts.items():
        paths = export_part(part, outdir, name)
        written.extend(paths.values())
        print(f"  · {name:<14} STEP {os.path.getsize(paths['step']) // 1024:>5} KB   "
              f"3MF {os.path.getsize(paths['3mf']) // 1024:>5} KB   "
              f"体积 {part.volume / 1000:.1f} cm³")

    if assembly:
        os.makedirs(outdir, exist_ok=True)
        path = os.path.join(outdir, "assembly.step")
        export_step(design.assembly(include_illustrative=illustrative), path)
        written.append(path)
        print(f"  · {'assembly':<14} STEP {os.path.getsize(path) // 1024:>5} KB"
              + ("（含 DN25 外观参考件）" if illustrative else ""))
    return written
