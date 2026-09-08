# -*- coding: utf-8 -*-
"""
防呆自检 —— "装反了必须装不进去"。

防呆有三个层次，本设计里三种都有，但**只有第一种能被机器验证**：

1. **几何防呆**：装反就是装不进去。可验证 —— 把零件按可能的错误姿态摆一遍，
   干涉体积**必须**大于阈值。本模块干的就是这件事。
2. **导向防呆**：装错会明显别扭（导轨、倒角、落座感）。只能人工体会。
3. **标识防呆**：刻字、颜色。最弱的一层，但有时是唯一可行的
   （比如一块两面一样的矩形镜片）。

每条规则都是**反向判据**：``干涉 > 阈值`` 才算通过。
"""

from __future__ import annotations

from build123d import Pos, Rot

from .. import refs
from ..layout import led_frame
from . import ERROR, INFO, WARN, Result, fmt, inter_vol, rule

#: 判定"确实装不进去"的干涉体积下限。太小的值可能只是圆角擦边。
BLOCK_TOL = 20.0


@rule("POKA-01", "POKA", "镜片托板前后调头装不到位",
      why="两处形状同时挡着：前后销**直径不同**（后 Ø4 / 前 Ø5），"
          "而且两个销的 Y 位置也不对称（−16 / +14）。调头后销对不上孔，"
          "会顶在支承片的实体上，托板落不下去。"
          "\n"
          "★ 这条判据改过一次，值得记：托台改成等高之后，"
          "原来的『调头会悬空』判据失效了（等高托台照样托得住调头的托板），"
          "必须改回『调头会干涉』。**同一个防呆意图，在不同的结构下"
          "对应完全相反的判据** —— 改结构时一定要回来重新想一遍判据方向，"
          "否则会留下一条永远为真（或永远为假）的假检查。")
def holder_reversed(design):
    c = design.cfg.case
    flipped = Rot(0, 0, 180) * design.mirror_holder
    v = inter_vol(design.body, flipped)
    return v > BLOCK_TOL, (
        f"调头后在标称位置就干涉 {fmt(v)}（阈值 {BLOCK_TOL}）；"
        f"销径 后 Ø{c.pin_d_rear} / 前 Ø{c.pin_d_front}，"
        f"销位 y={sum(c.pad_rear_y) / 2:.0f} / {sum(c.pad_front_y) / 2:.0f}（不对称）")


@rule("POKA-02", "POKA", "滑盖上下颠倒 / 前后调头都装不进去",
      why="+X 滑槽里有一条定位筋（cover_key_*），盖板 +X 舌片在对应高度以上"
          "收窄。装反时收窄段跑到 −X 侧，筋就会顶住满宽的舌片。")
def cover_flipped(design):
    c = design.cfg.case
    zc = (c.cav_z0 + 0.5 + c.pod_z1) / 2
    yc = (c.cover_y0 + c.cover_y1) / 2
    out = []
    variants = {
        "上下颠倒": Pos(0, 0, zc) * Rot(0, 180, 0) * Pos(0, 0, -zc),
        "前后调头": Pos(0, yc, 0) * Rot(0, 0, 180) * Pos(0, -yc, 0),
    }
    for nm, loc in variants.items():
        v = inter_vol(design.body, loc * design.slide_cover)
        out.append(Result("POKA-02", "POKA", f"滑盖{nm}装不进去", v > BLOCK_TOL,
                          fmt(v), cover_flipped._rule["why"], ERROR))
    return out


@rule("POKA-03", "POKA", "草帽 LED 极性装反压不进去",
      why="灯珠法兰上有一条切边标记阴极（led.step 实测：距轴心 2.4mm），"
          "座孔做了同样的切边。绕自身轴转 180° 后切边对不上，压不进去。"
          "这是本设计里最硬的一处防呆 —— 不靠标识、不靠说明书，靠形状。")
def led_polarity(design):
    cfg = design.cfg
    lg = cfg.light
    # 主判据是**线性阻挡量**，不是体积：法兰只有 1mm 厚，转 180° 后
    # 被挡住的那一小块干涉体积不到 1mm³，和布尔噪声（阈值 2mm³）分不开。
    # 线性量就没有这个问题：灯珠半径 − 座孔切边距轴心 = 实打实的过盈。
    block = lg.flange_d / 2 - (lg.flange_flat + lg.bore_clr)
    loc = led_frame(cfg)
    v = inter_vol(design.body, (loc * Rot(0, 0, 180) * loc.inverse())
                  * refs.led_bodies(cfg))
    return block >= 0.30, (
        f"装反时法兰被挡 {block:.2f}mm "
        f"= 灯珠半径 {lg.flange_d / 2:.2f} − 座孔切边 "
        f"{lg.flange_flat + lg.bore_clr:.2f}（要求 ≥0.30）；"
        f"对应干涉体积仅 {fmt(v)}，所以不用体积做判据")


@rule("POKA-04", "POKA", "开发板绕光轴转 180° 装不进去",
      why="前腔在 Z 方向是**不对称**的（SD 卡座偏上、排线尾端偏下）。"
          "板子上下颠倒时，SD 卡座那一侧会顶到台阶。"
          "如果哪天让位槽被改成上下对称，这条会立刻报错 —— 那正是它的用处。")
def board_upside_down(design):
    cfg = design.cfg
    zc = cfg.optics.mirror_z
    flipped = Pos(0, 0, zc) * Rot(0, 180, 0) * Pos(0, 0, -zc) * design.board
    v = inter_vol(design.body, flipped)
    return v > BLOCK_TOL, fmt(v)


@rule("POKA-05", "POKA", "开发板前后装反时摄像头方腔是空的（装错一眼看得出）",
      why="前后调头的失败模式不是『撞上』而是『定不住』：板子在腔里前后晃，"
          "镜头对着滑盖。判据必须跟着改成『方腔里没有东西』——"
          "写成『应当干涉』的话这条检查永远为假。"
          "（同类教训见 POKA-01：反向判据的方向写反了，比没有检查更糟。）")
def board_backwards(design):
    from ..geometry import bx

    p = design.pod
    yc = (p.pcb_face_y + p.board_back_y) / 2
    flipped = Pos(0, yc, 0) * Rot(0, 0, 180) * Pos(0, -yc, 0) * design.board
    pocket = bx(-p.cam_half_x, p.cam_half_x, p.wall_inner_y, p.cam_pocket_y1,
                p.cam_z0, p.cam_z1)
    occupancy = inter_vol(flipped, pocket)
    correct = inter_vol(design.board, pocket)
    return occupancy < 1.0 and correct > 50.0, (
        f"反装时方腔占用 {fmt(occupancy)}（正装 {fmt(correct)}）—— "
        f"镜头没有归位，板卡在腔里前后自由晃动")


@rule("POKA-06", "POKA", "镜片朝向只能靠刻字提醒", severity=INFO,
      why="前表面镜必须镀膜面朝下。装反会变成普通背镀镜，玻璃前后两次反射"
          "产生双像鬼影，字轮重影，OCR 直接失效。"
          "但它是一块两面一样的矩形玻璃，**做不成几何防呆**——"
          "诚实地把这一条标成 INFO，比假装它被解决了要好。")
def mirror_face(design):
    return True, ("托板横梁上刻有 COATED SIDE DOWN；ASSEMBLY.md 第 11 步有对应检查动作。"
                  "识别方法：用笔尖轻触镜面，笔尖和倒影**没有间隙**的那面才是镀膜面。")
