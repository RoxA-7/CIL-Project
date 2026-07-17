# Project Record

日期：2026-07-18

## 本次整理范围

本次整理的是 `cil_restart` 重启工程的可交付成果，而不是把整个本地工作区原样推送。

已纳入：

- 诊断实验代码、配置和测试。
- D0-D4 原始日志、tidy CSV、三线表、诊断图和摘要。
- 组会成果包。
- 84 页教学 PDF。
- 教学 workspace 文件：mission、resources、lessons、reference、learning records。
- 官方 CLearning 固定 commit 记录。

未纳入：

- 论文 PDF 原文。
- 旧 VGG 代码整包。
- 官方 CLearning 源码整包。
- 临时缓存、渲染中间图、特征缓存、node_modules。

## 旧项目状态

旧项目已经观察到 `bus -> train -> wolf` 类别替换，但不能直接作为正式结果。

主要问题：

- RGB/BGR 修复、优化器切换、训练轮次增加同时发生，无法归因。
- 10->11 类时输出层重新初始化，旧权重没有正确继承。
- 11->12 和 12->13 虽复制旧权重，但预热阶段仍更新整个分类层。
- 新阶段训练数据只有新类，CE 会系统性偏向新类。
- KD 只在旧类内部 softmax，无法感知旧类 logits 共同下移。
- 历史 checkpoint 不是严格意义的 MTD 多样化教师。
- 双教师代码存在缺参数和无学生梯度损失项。
- 使用测试准确率选择最佳 epoch，造成测试泄漏。

## 已完成诊断结果

| Variant | bus ↑ | train ↑ | old ↑ | logit gap ↓ | 替换 |
|---|---:|---:|---:|---:|---|
| D0 | 0.00 | 100.00 | 0.00 | 26.99 | 是 |
| D1 | 0.00 | 100.00 | 0.18 | 19.37 | 是 |
| D2 | 0.00 | 100.00 | 1.36 | 21.60 | 是 |
| D3 | 10.00 | 94.00 | 58.73 | 13.53 | 否 |
| D4 | 10.00 | 94.00 | 58.91 | 13.78 | 否 |

诊断边界：

- 旧 VGG/JPEG 协议。
- 单种子 1993。
- 固定 6 epochs。
- 用于解释故障机制，不进入正式主排名。

## 正式实验状态

计划正式协议：

- CIFAR-100
- ResNet-32
- B50-5S
- 20 exemplars/class
- seeds 1993, 1994, 1995

当前状态：

- 官方 CLearning 固定到 `ce0789a40bda9e566a1e0432d3ac320937ca48f0`。
- 当前环境 PyTorch / CUDA 可用。
- `continuum` 未安装成功，正式训练入口尚未 ready。
- 主结果表仍为待运行。

## 教学材料状态

已生成 `deliverables/pdf/CIL类增量学习完整课程讲义.pdf`。

内容覆盖：

- 神经网络零基础。
- logits、softmax、CE、KD、梯度。
- CIL 协议和 B50-5S。
- LwF、Replay、PODNet、MTD、SS-IL。
- D0-D4 故障机制。
- AA、AIA、forgetting、mean±std。
- 三线表、图表、组会答辩。

