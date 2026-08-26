# CIL-Project

类增量学习（Class-Incremental Learning, CIL）交接项目的整理版仓库。

本仓库包含两条边界不同、不能混写结果的研究路线：

1. `cil_restart/`：旧实验故障复盘、表图流程、教学材料，以及标准 CIFAR-100 CIL 复现实验的工程骨架；其中正式 B50-5S 多方法主结果尚未完成。
2. `b2_fixed_order/`：固定类别顺序下的解析递归 Ridge B2 研究；已完成类别 12 的 train-only 五折 OOF 三随机种子确认，但尚未完成冻结后的独立 validation 和 official test。

两条路线使用不同的数据边界、评价协议和研究目标，仓库中的数字必须在各自目录内解释，不能直接用于相互排名。

## 固定顺序 B2 研究

`b2_fixed_order/`针对“学习类别 11 后类别 10 接近失效，并在继续学习类别 12 时保持已见类别”的问题。方法冻结特征提取网络，用可加的充分统计量递归更新 centered Ridge 分类头。

三随机种子 train-only OOF 均值为：类别 10 为 62.60%，类别 11 为 68.40%，类别 12 为 79.27%，类别 0—9 宏平均为 96.48%，总体为 90.39%。类别 11 相对原生头下降，因此这是伴随真实权衡的平衡改善，不是无代价解决。

完整实验因果过程、复现边界和最小代码见 [`b2_fixed_order/README.md`](b2_fixed_order/README.md)。

## 1. 项目在研究什么

这个项目研究的是图像分类模型在“新类别不断加入”时，如何避免旧类别被遗忘或被最新类别替换。

普通图像分类通常一次性看到全部类别：

```text
100 类训练数据 -> 训练模型 -> 测试 100 类
```

类增量学习不是这样。它分阶段学习：

```text
先学 50 类 -> 再学 10 类 -> 再学 10 类 -> ... -> 最后仍要识别所有已学类别
```

难点是：模型学习新类别时，旧类别的准确率可能突然下降。例如旧实验里观察到过：

```text
bus 被 train 替换
train 又被 wolf 替换
```

本轮项目的目标不是立刻提出新算法，而是先把旧结果为什么不可信、类别替换为什么发生、标准协议该怎么复现、结果该如何用三线表和图表汇报讲清楚。

## 2. 当前结论

已经完成的是旧 VGG/JPEG 诊断实验，不是正式 CIFAR-100 B50-5S 主结果。

诊断结论：

- 当前旧实现 D0 能复现类别替换：`bus=0.00%`，`train=100.00%`，`old=0.00%`。
- 只修旧权重继承 D1 后，`old=0.18%`，仍然几乎失败。
- 冻结旧分类器行 D2 后，`old=1.36%`，仍挡不住新类 logit 优势。
- 加入每类 20 个旧样本 replay 的 D3 后，`old=58.73%`，类别替换被明显缓解。
- D4 replay + separated softmax 后，`old=58.91%`，与 D3 接近，当前不能夸大 separated softmax 的额外收益。
- 数值验证显示旧类内部 KD 对共同 logit 平移基本不敏感，误差约 `1.19e-7`。

简化解释：

```text
新类 CE 会抬高新类 logit、压低旧类 logit；
旧类内部 KD 看不到所有旧类 logits 一起下移；
所以旧类可能被最新类别吸走。
```

## 3. 尚未完成的正式结果

标准主实验仍未完成，README 中不填虚构数字。

计划协议：

- Dataset: CIFAR-100
- Backbone: ResNet-32
- Scenario: B50-5S
- Memory: 20 exemplars/class
- Seeds: 1993, 1994, 1995
- Methods: FineTune, LwF, Replay, PODNet, MTD-PODNet, SS-IL, MTD-SSIL

当前阻塞：

- 官方 CLearning 依赖 `continuum` 尚未在当前 Python 3.12 环境打通。
- `results/tables/表2_标准方法主结果.md` 中所有正式方法仍标记为待运行。

因此本仓库目前可以支持组会说明“为什么要重启、旧问题在哪里、下一步怎么跑标准复现”，但不能宣称 PODNet/MTD/SS-IL 的正式性能结论。

## 4. 仓库结构

```text
.
├── README.md
├── b2_fixed_order/
│   ├── README.md
│   ├── src/
│   ├── tools/
│   ├── tests/
│   ├── configs/
│   └── docs/
├── docs/
│   ├── BACKUP_MANIFEST.md
│   ├── PROJECT_RECORD.md
│   └── REPRODUCIBILITY.md
├── deliverables/
│   ├── pdf/
│   │   └── CIL类增量学习完整课程讲义.pdf
│   ├── tables/
│   │   └── CIL三线表与实验结果.xlsx

│   └── 组会成果包.md
└── cil_restart/
    ├── README.md
    ├── MISSION.md
    ├── RESOURCES.md
    ├── THIRD_PARTY_LOCK.md
    ├── src/
    ├── scripts/
    ├── tests/
    ├── configs/
    ├── results/
    │   ├── raw/
    │   ├── tidy/
    │   ├── tables/
    │   ├── figures/
    │   └── summary/
    ├── lessons/
    ├── reference/
    └── output/pdf/
```

## 5. 重要文件

| 文件 | 用途 |
|---|---|
| `b2_fixed_order/README.md` | 固定顺序解析递归Ridge B2的代码、方法、实验过程与证据边界。 |
| `docs/LOCAL_PATH_RISK_AUDIT.md` | 现有历史结果中本机路径的风险清单与未来公开处理建议。 |
| `deliverables/pdf/CIL类增量学习完整课程讲义.pdf` | 84 页零基础教学讲义，解释神经网络、CE、KD、CIL、D0-D4、图表和答辩。 |
| `deliverables/组会成果包.md` | 当前可以用于组会的简版结论。 |
| `cil_restart/results/tables/表1_交接问题复盘.md` | D0-D4 诊断三线表。 |
| `cil_restart/results/tables/表2_标准方法主结果.md` | 标准方法主结果表，目前仍为待运行。 |
| `cil_restart/results/figures/` | 已生成的诊断图和混淆矩阵。 |
| `cil_restart/results/raw/` | 原始 JSON 日志，是所有表图的事实源。 |
| `cil_restart/results/tidy/` | 从 raw 清洗出的 CSV。 |
| `cil_restart/RESOURCES.md` | 论文、交接文档、官方代码、证据边界与缺口。 |
| `cil_restart/THIRD_PARTY_LOCK.md` | 官方 CLearning 固定 commit 记录。 |

## 6. 快速复现和检查

进入工程目录：

```powershell
cd cil_restart
```

运行单元测试：

```powershell
python -m pytest
```

重新从 raw 日志生成 tidy CSV、表格、图片和摘要：

```powershell
python scripts/build_results.py
```

检查官方 CLearning 环境：

```powershell
python scripts/check_official.py
```

整理版仓库没有直接提交官方 CLearning 源码。若要运行正式方法，请先按 `THIRD_PARTY_LOCK.md` 克隆官方实现到：

```text
cil_restart/third_party/CLearning
```

并切换到固定 commit：

```text
ce0789a40bda9e566a1e0432d3ac320937ca48f0
```

正式实验入口示例：

```powershell
python scripts/run_official.py --method podnet --seed 1993
```

注意：正式实验目前依赖环境尚未完全打通，不能把待运行表格当作已完成结果。

## 7. 结果生成原则

本项目的核心原则是：所有表格和图片必须由原始日志自动生成，不能手工抄数字。

证据链如下：

```text
results/raw/*.json
    -> results/tidy/*.csv
    -> results/tables/*
    -> results/figures/*
    -> results/summary/*
```

必须遵守：

- 不用测试集挑选 checkpoint。
- 不从单随机种子结果得出正式结论。
- 不把旧 VGG/JPEG 诊断结果放进标准方法排名。
- 不把官方已有 MTD-SSIL 包装成创新。
- 缺 seed 时不能输出 `mean ± std`。
- 正式复现未完成时，不填任何主结果数字。

## 8. 没有纳入仓库的内容

为了保持仓库可维护并避免版权/体积问题，整理版没有纳入：

- 第三方论文 PDF 原文。
- 官方 CLearning 源码整包。
- 旧 VGG 原始代码整包。
- 临时渲染 PNG、QA 中间文件、缓存特征 `.pt`。
- Python cache、pytest cache、node_modules。

对应信息已通过 `RESOURCES.md`、`THIRD_PARTY_LOCK.md` 和结果日志记录。

## 9. 下一步

推荐顺序：

1. 解决 `continuum` 与当前 Python 3.12 环境的兼容问题，或切换到兼容环境。
2. 完成官方 CLearning 的 1 epoch / 2 task 冒烟实验。
3. 跑 FineTune、LwF、Replay sanity baseline。
4. 跑 PODNet、MTD-PODNet 单种子，并与论文结果核对；误差超过 2 个百分点则先排查。
5. 复现通过后，再跑 PODNet、MTD-PODNet、SS-IL、MTD-SSIL 三种子。
6. 自动生成表 2-5 和图 4-8。
7. 根据 MTD 是否稳定超过标准差决定下一阶段研究方向。

## 10. 当前状态一句话

当前仓库已完成旧实验故障机制诊断和固定顺序 B2 的 train-only 三随机种子确认；标准 CIFAR-100 B50-5S 多方法正式结果、B2 独立 validation 与 official test 均仍待完成。
