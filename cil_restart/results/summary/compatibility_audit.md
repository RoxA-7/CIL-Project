# CLearning 兼容性审计

- 官方固定提交：`ce0789a40bda9e566a1e0432d3ac320937ca48f0`。
- 官方声明环境：Python 3.9、PyTorch 1.11、continuum 1.2.4。
- 当前环境：Python 3.12.2、PyTorch 2.5.1+cu121、RTX 4060 Laptop GPU。
- 2026-07-16：首次安装 `continuum==1.2.4` 在 120 秒内无输出并超时，尚未修改官方算法源码。
- 正式训练必须在 `scripts/check_official.py` 返回 `ready=true` 后启动。
- 仅有 AccMatrix 的导入结果标记为 `partial`，不会进入正式主表；完整状态还需 per-class、混淆矩阵、logit 和分类器统计的评估插桩。

