# cases/ —— 外壳设计工作目录

水表光学抄表装置的外壳设计全部在这个目录里：参数化模型、自检套件、
参考模型、设计文档、生成物。**改外壳只需要动这一个目录。**

---

## 30 秒上手

```bash
cd cases
pip install -r requirements.txt      # build123d 0.11.1（含 OCP，约 400MB）
python build.py check                # 跑一遍自检（有进度条）
python build.py build                # 自检通过后导出 STEP / 3MF / 装配体 / 仿真画面
```

其它子命令：

```bash
python build.py check --skip SEQ     # 跳过最慢的路径仿真，快速迭代
python build.py check --only OPT,LED # 只跑光学，改光路时用
python build.py sim                  # 只出模拟相机画面
python build.py params               # 打印全部参数与派生量
python build.py doc                  # 从 assembly.py 重新生成 ASSEMBLY.md
python build.py inspect x.step       # 量一个 STEP 的包络（换开发板时用）
```

`cases/` 有任何变动，CI（`.github/workflows/case-check.yaml`）都会自动跑一遍
`check`，报告和模拟画面作为 artifact 传上来。

导出物在 `out/`：

| 文件 | 用途 |
|---|---|
| `body.step` / `.3mf` | 主体（抱箍 + 立板 + LED 座 + 镜托台 + 吊臂 + 吊舱） |
| `mirror_holder.step` / `.3mf` | 镜片托板（每月抄表时整块提起） |
| `slide_cover.step` / `.3mf` | 滑盖（竖直下滑，无螺丝） |
| `assembly.step` | 装配体，含开发板 / 镜片 / LED / 水表替身，供整体检视 |
| `assembly_exploded.step` | **爆炸图**，子件按装配顺序编号 00~12，另有引导杆指回安装位置 |
| `assembly_views.svg` | 爆炸图的正交投影（正视 + 侧视），不开 CAD 也能看装配关系 |
| `sensor_view.svg` | **模拟相机画面** —— 光线追踪的结果，一眼看出表盘读不读得到 |
| `report.md` / `report.json` | 自检报告（进 git，可做版本间 diff） |

---

## 该读哪份文档

| 你想做的事 | 读这个 |
|---|---|
| 理解设计为什么长这样 | [DESIGN.md](DESIGN.md) ← **主文档** |
| 知道前人在哪里翻过车 | [DESIGN_NOTES.md](DESIGN_NOTES.md) §7 踩过的坑 |
| 参与迭代（AI 或人） | [WORKFLOW.md](WORKFLOW.md) |
| 现场装配 / 每月抄表 | [ASSEMBLY.md](ASSEMBLY.md)（由模型自动生成） |
| 微调某个尺寸 | [wmcase/params.py](wmcase/params.py) ← 全项目唯一允许出现尺寸数字的地方 |
| 打印工艺要求 | [dfam_rules.md](dfam_rules.md) |
| 版本变更 | [CHANGELOG.md](CHANGELOG.md) |

---

## 目录结构

```
cases/
├── build.py                入口（check / build / sim / params / inspect / doc）
├── wmcase/                 参数化模型包
│   ├── params.py           ★ 参数中心：实测 / 采购 / 设计 / 估算，四种可信度
│   ├── layout.py           尺寸链推导（参数 → 位置与基准面）
│   ├── geometry.py         建模原语（按起止坐标建体、镜像、水滴孔…）
│   ├── parts/              三个打印件
│   ├── refs.py             参考件（开发板 / LED / 镜片 / 水表），按可信度分级
│   ├── optics.py           光路仿真：虚拟相机 + 逐点光线追踪
│   ├── assembly.py         装配 / 抄表 / 拆卸顺序（写成数据，可被机器验证）
│   ├── checks/             自检套件，10 个分类
│   ├── export.py           STEP / 3MF 导出
│   ├── report.py           终端表格 / Markdown / JSON / 模拟画面 SVG
│   ├── docs.py             ASSEMBLY.md 生成（保证文档和模型一致）
│   └── compat.py           环境兼容（Windows 坏字体导致 build123d 无法 import）
├── 参考模型（外购件与被测物，**不是我们生产的**）
│   ├── esp32s3cam-1/2/3.step   三款主控板；第一版适配 -2
│   ├── led.step                5mm 草帽白光 LED
│   ├── watermeter-dn25.step    ⚠ DN25，只能看外观，**不许参与判定**
│   ├── amico.pdf               埃美柯样本（结构外形及安装尺寸）
│   └── amico-lxsy.pdf          LXSY 系列样本（LXSY-15E2 外形尺寸表）
└── out/                    生成物（已 gitignore）
```

---

## 分工

这套东西是按"**AI 设计 / 机器验证 / 人工确认**"三段分工搭的：

* **AI** 改参数、改结构、写新的自检规则；
* **机器**（`build.py check`）跑 110+ 条规则，拦住可计算的错误；
* **人**看渲染、看切片预览、试打，做最终确认。

为什么这么分：十三个版本的统计事实是，**可手算复核的东西 AI 很少出错，
需要空间想象的东西 AI 几乎必错**（DESIGN_NOTES §7.9）。
所以凡是"结构会不会撞、连不连通、光挡不挡得住"，
一律翻译成可计算的判据交给机器，而不是靠谁的直觉。

完整流程见 [WORKFLOW.md](WORKFLOW.md)。
