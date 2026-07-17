# CIL Restart

这是与旧 `VGG16_CIL` 隔离的类增量学习重启工程。旧目录只作为故障证据，不作为正式结果来源。

## 科学边界

- 正式协议：CIFAR-100、ResNet-32、B50-5S、20 exemplars/class、seeds 1993/1994/1995。
- 正式结果只能来自 `results/raw/*.json`，生成表格后禁止手改数值。
- 测试集仅用于固定训练流程结束后的评价，不用于挑选 checkpoint。
- 诊断实验使用旧 11 类 checkpoint 和旧 JPEG 数据，仅解释故障机制，不进入正式主排名。
- D4 是适用于单新类诊断的 old/new group-separated softmax；官方 B50-5S 仍使用 CLearning 的 SS-IL。

## 一键入口

```powershell
# 单元测试与数学验收
D:\Python\python.exe -m pytest

# 类别替换诊断（先抽取一次 VGG 特征，再运行 D0-D4）
D:\Python\python.exe scripts\run_legacy_diagnostics.py --variants D0 D1 D2 D3 D4 --epochs 6

# 汇总真实日志并生成 CSV、三线表、图片和摘要
D:\Python\python.exe scripts\build_results.py

# 检查官方 CLearning 环境和配置，不启动长时训练
D:\Python\python.exe scripts\check_official.py

# 运行一项正式实验；默认固定 epoch，不以测试集选 best
D:\Python\python.exe scripts\run_official.py --method podnet --seed 1993
```

## 目录

- `configs/`：诊断和正式协议配置。
- `src/cil_restart/`：指标、日志协议、诊断、表格和绘图实现。
- `results/raw/`：不可编辑原始 JSON。
- `results/tidy/`：清洗后的可分析 CSV。
- `results/tables/`：中英文 Markdown/LaTeX/DOCX/XLSX 三线表。
- `results/figures/`：300 DPI PNG 与 SVG/PDF。
- `results/summary/`：自动结论、完整性与一致性检查。
- `lessons/`、`reference/`：教学材料。
- `third_party/CLearning/`：作者官方源码，固定提交见 `THIRD_PARTY_LOCK.md`。

