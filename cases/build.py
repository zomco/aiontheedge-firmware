#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
水表光学抄表装置 · 外壳生成与自检
=================================

这是 ``cases/`` 目录唯一的入口。所有日常动作都从这里走::

    python build.py check                    # 只跑自检（不导出），约 3~4 分钟
    python build.py check --only OPT,SEQ     # 只跑某几类，改光学时用
    python build.py check --skip DFAM,SEQ    # 跳过慢的，快速迭代时用
    python build.py build                    # 自检 + 导出 STEP/3MF/装配体
    python build.py build --force            # 自检没过也导出（**只用于看渲染排错**）
    python build.py sim                      # 只跑光路仿真，出 sensor_view.svg
    python build.py params                   # 打印当前参数与派生量
    python build.py inspect <file.step>      # 量一个 STEP 的包络（换开发板时用）

设计意图
--------
**自检不过就不导出。** 这不是洁癖：本项目十三个版本里，凡是"先打出来再说"
的那几次，代价都是三天等待 + 一堆废料（DESIGN_NOTES §8）。
机器几分钟能查完的事，不要用打印机去查。
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wmcase  # noqa: E402  (必须先 import 它来打环境补丁)
from wmcase import checks, report as rpt  # noqa: E402
from wmcase.export import export_all  # noqa: E402
from wmcase.model import build as build_design  # noqa: E402
from wmcase.params import BOARDS, CFG, Config, replace  # noqa: E402

DEFAULT_OUT = "out"


# =============================================================================
#  公共
# =============================================================================

def _config(args) -> Config:
    cfg = CFG
    if getattr(args, "board", None):
        if args.board not in BOARDS:
            sys.exit(f"未知开发板 '{args.board}'。已知：{', '.join(BOARDS)}\n"
                     f"新增办法：用 `python build.py inspect <file.step>` 量出包络，"
                     f"在 params.BOARDS 里加一条 BoardSpec。")
        cfg = replace(cfg, board=BOARDS[args.board])
    return cfg


def _banner(design) -> None:
    c = design.cfg
    o = c.optics
    print("=" * 78)
    print(f"  水表光学抄表装置 · 外壳 v{wmcase.__version__}")
    print("=" * 78)
    print(f"  水表      {c.meter.model}  DN{c.meter.dn}  "
          f"银圈 Ø{c.meter.bezel_od}  净空 {c.meter.headroom}mm")
    print(f"  开发板    {design.board_ref.source}  [{design.board_ref.trust}]")
    print(f"  光路      {o.mirror_z:.0f} ↑ + {o.lens_face_y:.0f} → = 光程 {o.path:.0f}mm，"
          f"单字符 {o.digit_px:.0f}px，景深 ±{o.dof_half_mm:.0f}mm")
    print(f"  镜片      需 {o.need_mirror_len:.0f}×{o.need_mirror_width:.0f}，"
          f"采购 {o.mirror_l:.0f}×{o.mirror_w:.0f}×{o.mirror_t:.0f} 前表面镜")
    print(f"  抱箍      光孔 Ø{2 * (c.meter.bezel_od / 2 + c.case.collar_bore_gap):.1f}，"
          f"内棱 Ø{2 * (c.meter.bezel_od / 2 - c.case.collar_rib_interf):.1f}，"
          f"单边过盈 {c.case.collar_rib_interf:.2f}mm")
    print()


def _run_checks(design, args):
    only = [s.strip().upper() for s in args.only.split(",")] if args.only else None
    skip = [s.strip().upper() for s in args.skip.split(",")] if args.skip else None
    print("  建模 + 自检中 …（首次会解析 STEP，稍慢）")
    t0 = time.time()
    report = checks.run_all(design, only=only, skip=skip)
    rpt.print_report(report)
    print(f"  自检耗时 {time.time() - t0:.1f}s")
    return report


def _write_reports(design, report, outdir):
    os.makedirs(outdir, exist_ok=True)
    md = rpt.write_markdown(design, report, os.path.join(outdir, "report.md"))
    js = rpt.write_json(design, report, os.path.join(outdir, "report.json"))
    print(f"  · 报告  {md}\n  ·        {js}")
    return md, js


# =============================================================================
#  子命令
# =============================================================================

def cmd_check(args) -> int:
    design = build_design(_config(args))
    _banner(design)
    report = _run_checks(design, args)
    if not args.no_report:
        _write_reports(design, report, args.out)
    return 0 if report.passed else 1


def cmd_build(args) -> int:
    design = build_design(_config(args))
    _banner(design)
    report = _run_checks(design, args)
    _write_reports(design, report, args.out)

    if not report.passed and not args.force:
        print("  ✗ 有阻断性失败，**不导出**。")
        print("    要看渲染排错可以加 --force，但导出的文件不许拿去打印。")
        return 1

    print("  导出中 …")
    export_all(design, args.out, assembly=True, illustrative=args.illustrative)
    print("  仿真画面 …")
    svg = rpt.write_sensor_view(design, os.path.join(args.out, "sensor_view.svg"))
    print(f"  · {svg}")
    return 0 if report.passed else 1


def cmd_sim(args) -> int:
    design = build_design(_config(args))
    _banner(design)
    report = checks.run_all(design, only=["OPT", "LED"])
    rpt.print_report(report)
    svg = rpt.write_sensor_view(design, os.path.join(args.out, "sensor_view.svg"))
    print(f"  · 模拟传感器画面 → {svg}")
    return 0 if report.passed else 1


def cmd_params(args) -> int:
    from dataclasses import fields, is_dataclass

    cfg = _config(args)
    for group in fields(cfg):
        val = getattr(cfg, group.name)
        if not is_dataclass(val):
            continue
        print(f"\n── {group.name}  ({type(val).__name__}) " + "─" * 40)
        for f in fields(val):
            print(f"    {f.name:<24} = {getattr(val, f.name)}")
        # 派生量
        derived = [n for n in dir(type(val))
                   if isinstance(getattr(type(val), n, None), property)]
        for n in sorted(derived):
            try:
                print(f"    {'· ' + n:<24} → {getattr(val, n)}")
            except Exception:  # noqa: BLE001
                pass
    from wmcase.layout import pod_layout
    print("\n── 吊舱尺寸链（layout.pod_layout 推导）" + "─" * 30)
    for k, v in pod_layout(cfg).__dict__.items():
        print(f"    {k:<24} = {v:.3f}" if isinstance(v, float) else f"    {k:<24} = {v}")
    return 0


def cmd_doc(args) -> int:
    """从 assembly.py 重新生成 ASSEMBLY.md。"""
    from wmcase.docs import write_assembly_doc

    here = os.path.dirname(os.path.abspath(__file__))
    path = write_assembly_doc(_config(args), os.path.join(here, "ASSEMBLY.md"))
    print(f"  · {path}")
    return 0


def cmd_inspect(args) -> int:
    """量一个 STEP 的包络与零件清单 —— 换开发板时的第一步。"""
    from build123d import import_step

    path = args.step
    if not os.path.isfile(path):
        sys.exit(f"找不到 {path}")
    t0 = time.time()
    shape = import_step(path)
    bb = shape.bounding_box()
    print(f"{path}  载入 {time.time() - t0:.1f}s")
    print(f"  包围盒  X[{bb.min.X:.2f},{bb.max.X:.2f}] "
          f"Y[{bb.min.Y:.2f},{bb.max.Y:.2f}] Z[{bb.min.Z:.2f},{bb.max.Z:.2f}]")
    print(f"  尺寸    {bb.size.X:.2f} × {bb.size.Y:.2f} × {bb.size.Z:.2f}")
    print(f"  实体数  {len(shape.solids())}")
    children = list(getattr(shape, "children", []))
    if children:
        print(f"  子件 {len(children)} 个（按体积排序，前 40）：")
        rows = []
        for ch in children:
            cb = ch.bounding_box()
            rows.append((ch.volume if hasattr(ch, "volume") else 0.0,
                         getattr(ch, "label", ""), cb))
        rows.sort(reverse=True, key=lambda r: r[0])
        for vol, label, cb in rows[:40]:
            print(f"    {label[:38]:<38} 尺寸 {cb.size.X:6.2f} {cb.size.Y:6.2f} "
                  f"{cb.size.Z:6.2f}  范围 X[{cb.min.X:7.2f},{cb.max.X:7.2f}] "
                  f"Y[{cb.min.Y:6.2f},{cb.max.Y:6.2f}] Z[{cb.min.Z:7.2f},{cb.max.Z:7.2f}]")
    print("\n  把这些数字填进 params.BoardSpec，然后 `python build.py check --board <名字>`。")
    print("  FIT-05 会反过来核对你抄得对不对。")
    return 0


# =============================================================================
#  入口
# =============================================================================

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="水表抄表装置外壳生成器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd")

    def common(p, with_checks=True):
        p.add_argument("--board", default=None,
                       help=f"开发板型号，已知：{', '.join(BOARDS)}")
        p.add_argument("--out", default=DEFAULT_OUT, help="输出目录（默认 out/）")
        if with_checks:
            p.add_argument("--only", default=None,
                           help="只跑这些分类，逗号分隔（TOPO,FIT,CONS,SEQ,OPT,LED,DIM,DFAM,POKA,WIRE）")
            p.add_argument("--skip", default=None, help="跳过这些分类")

    p = sub.add_parser("check", help="只跑自检")
    common(p)
    p.add_argument("--no-report", action="store_true", help="不写 report.md/json")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("build", help="自检 + 导出")
    common(p)
    p.add_argument("--force", action="store_true", help="自检没过也导出（仅用于排错）")
    p.add_argument("--illustrative", action="store_true",
                   help="装配体里带上 DN25 外观参考件（仅供看，不参与判定）")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("sim", help="只跑光路仿真，出 sensor_view.svg")
    common(p, with_checks=False)
    p.set_defaults(func=cmd_sim, only=None, skip=None)

    p = sub.add_parser("params", help="打印当前参数与派生量")
    common(p, with_checks=False)
    p.set_defaults(func=cmd_params)

    p = sub.add_parser("doc", help="从 assembly.py 重新生成 ASSEMBLY.md")
    common(p, with_checks=False)
    p.set_defaults(func=cmd_doc)

    p = sub.add_parser("inspect", help="量一个 STEP 的包络（换开发板时用）")
    p.add_argument("step")
    p.set_defaults(func=cmd_inspect)

    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        ap.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
