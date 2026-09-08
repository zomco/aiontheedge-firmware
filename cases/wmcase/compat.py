# -*- coding: utf-8 -*-
"""
环境兼容层 —— 必须在 ``import build123d`` **之前** 导入。

为什么需要这个文件
------------------
build123d 在 ``import`` 阶段就会扫描系统字体目录（``build123d/text.py`` 里的
``available_fonts = FontManager()...``）。只要系统里有 **一个** 损坏的字体文件，
``fontTools`` 抛异常，整个 build123d 就 import 不进来。

在本项目的开发机（Windows 11）上就有一个：``C:\\Windows\\Fonts\\mstmc.ttf``
（``TTLibError: Not a TrueType or OpenType font``）。它是系统自带字体，不应该动。

所以这里做一个**只影响本进程**的防御性补丁：把 ``fontTools.ttLib.TTFont``
换成一个宽容版本，读不动的字体文件返回一个"空字体"占位对象，
让 build123d 跳过它继续启动。正常字体完全不受影响。

用法
----
``wmcase/__init__.py`` 已经在最前面调用了 :func:`apply`，
所以只要 ``import wmcase`` 就自动生效，业务代码不用关心。

如果哪天 build123d 自己修了这个 bug，本文件可以整个删掉。
"""

from __future__ import annotations

_APPLIED = False


class _FakeNameRecord:
    """伪造一条 name 表记录，让 build123d 的 _get_font_faces 能正常跑完。"""

    def __init__(self, name_id: int, value: str) -> None:
        self.nameID = name_id
        self._value = value

    def toUnicode(self) -> str:  # noqa: N802  (fontTools 的接口就是驼峰)
        return self._value


class _FakeNameTable:
    def __init__(self, path: str) -> None:
        # nameID 1 = Font Family。给一个不会和真字体撞名的名字。
        self.names = [_FakeNameRecord(1, f"b123d-unreadable-{path.rsplit(chr(92), 1)[-1]}")]


class _FakeFont:
    """最小可用的 TTFont 替身：只支持 ``font['name']`` 和 ``'fvar' in font``。"""

    def __init__(self, path: str) -> None:
        self._name_table = _FakeNameTable(path)

    def __getitem__(self, key: str):
        if key == "name":
            return self._name_table
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        return False


def apply() -> None:
    """安装字体读取兜底补丁。重复调用无副作用。"""
    global _APPLIED
    if _APPLIED:
        return
    _APPLIED = True

    try:
        import fontTools.ttLib as ttlib
    except ImportError:  # 没装 fontTools 就没这个问题
        return

    real_ttfont = ttlib.TTFont

    def tolerant_ttfont(path, *args, **kwargs):
        try:
            return real_ttfont(path, *args, **kwargs)
        except Exception:  # noqa: BLE001 —— 任何读取失败都降级，不能让 import 挂掉
            return _FakeFont(str(path))

    ttlib.TTFont = tolerant_ttfont
    # build123d.text 用 `from fontTools.ttLib import TTFont`，
    # 但 fontTools.ttLib.ttFont 子模块里也有一份引用，一并替换更保险。
    if hasattr(ttlib, "ttFont"):
        ttlib.ttFont.TTFont = tolerant_ttfont
