# -*- coding: utf-8 -*-
"""
水表光学抄表装置 · 外壳参数化模型
=================================

``import wmcase`` 会先打上环境兼容补丁再加载 build123d，
所以业务代码永远不用关心字体扫描之类的事（见 :mod:`wmcase.compat`）。

模块分层（**从上往下依赖，不许反向**）::

    params.py     纯数字：实测 / 采购 / 设计 / 估算
        ↓
    layout.py     尺寸链：把参数换算成位置和基准面
        ↓
    geometry.py   建模原语：按起止坐标建体、镜像、水滴孔…
        ↓
    parts/*.py    三个打印件
    refs.py       参考件（开发板 / LED / 镜片 / 水表）
        ↓
    model.py      一次装配的全部实体（带缓存）
        ↓
    checks/*.py   自检规则
    optics.py     光路仿真（虚拟相机 + 光线追踪）
    export.py     STEP / 3MF 导出
    report.py     自检报告 + 传感器画面预览
"""

from . import compat as _compat

_compat.apply()

__version__ = "3.0.0"

from .params import CFG, BOARDS, Config  # noqa: E402

__all__ = ["CFG", "BOARDS", "Config", "__version__"]
