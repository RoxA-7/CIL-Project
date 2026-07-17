from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .metrics import summarize
from .schema import read_runs


METHOD_ORDER = ["FineTune", "LwF", "Replay", "PODNet", "MTD-PODNet", "SS-IL", "MTD-SSIL"]
DIAG_ORDER = ["D0", "D1", "D2", "D3", "D4"]
COLORS = {
    "FineTune": "#777777", "LwF": "#E69F00", "Replay": "#56B4E9",
    "PODNet": "#0072B2", "MTD-PODNet": "#009E73", "SS-IL": "#D55E00", "MTD-SSIL": "#CC79A7",
    "D0": "#D55E00", "D1": "#E69F00", "D2": "#0072B2", "D3": "#009E73", "D4": "#CC79A7",
}


def _latest_run_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Keep the newest immutable rerun for each method/seed/scenario."""
    if df.empty:
        return df
    keys = ["method", "seed", "scenario"]
    latest = df.groupby(keys, as_index=False).run_id.max()
    return df.merge(latest, on=[*keys, "run_id"], how="inner")


def _task_rows(run: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for task in run["tasks"]:
        rows.append({
            "run_id": run["run_id"], "source": run["_source"], "method": run["method"],
            "seed": run["seed"], "scenario": run["scenario"], "status": run["status"],
            "task_id": task["task_id"], "learned_classes": task["learned_classes"],
            "overall_accuracy": task["overall_accuracy"], "old_accuracy": task["old_accuracy"],
            "new_accuracy": task["new_accuracy"], "bus_accuracy": task.get("bus_accuracy"),
            "train_accuracy": task.get("train_accuracy"), "wolf_accuracy": task.get("wolf_accuracy"),
            "mean_old_logits": task.get("mean_old_logits"), "mean_new_logits": task.get("mean_new_logits"),
            "logit_gap": task.get("logit_gap"), "training_seconds": run.get("runtime", {}).get("training_seconds"),
            "peak_gpu_memory_mb": run.get("runtime", {}).get("peak_gpu_memory_mb"),
            "trainable_parameters": run.get("runtime", {}).get("trainable_parameters"),
        })
    return rows


def _class_rows(run: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    names = run.get("diagnostics", {}).get("class_names", [])
    for task in run["tasks"]:
        for class_id, acc in enumerate(task.get("per_class_accuracy", [])):
            rows.append({
                "run_id": run["run_id"], "method": run["method"], "seed": run["seed"],
                "scenario": run["scenario"], "task_id": task["task_id"], "class_id": class_id,
                "class_name": names[class_id] if class_id < len(names) else str(class_id), "accuracy": acc,
            })
    return rows


def _summary_row(run: dict[str, Any]) -> dict[str, Any]:
    stage_aa = [float(t["overall_accuracy"]) for t in run["tasks"]]
    histories = [t.get("per_class_accuracy", []) for t in run["tasks"]]
    width = max((len(x) for x in histories), default=0)
    matrix = [list(x) + [math.nan] * (width - len(x)) for x in histories]
    forgetting = math.nan
    if len(matrix) >= 2 and width:
        forgetting = summarize(stage_aa, matrix).forgetting
    runtime = run.get("runtime", {})
    return {
        "run_id": run["run_id"], "source": run["_source"], "method": run["method"],
        "seed": run["seed"], "scenario": run["scenario"], "status": run["status"],
        "tasks": len(run["tasks"]), "aia": float(np.mean(stage_aa)), "final_aa": stage_aa[-1],
        "forgetting": forgetting, "old_accuracy": run["tasks"][-1]["old_accuracy"],
        "new_accuracy": run["tasks"][-1]["new_accuracy"],
        "training_seconds": runtime.get("training_seconds"), "peak_gpu_memory_mb": runtime.get("peak_gpu_memory_mb"),
        "trainable_parameters": runtime.get("trainable_parameters"),
        "kd_common_shift_delta": run.get("diagnostics", {}).get("kd_common_shift_delta"),
    }


def build_tidy(raw_dir: str | Path, tidy_dir: str | Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    runs = read_runs(raw_dir)
    if not runs:
        raise ValueError(f"no raw JSON runs found in {raw_dir}")
    task = pd.DataFrame([row for run in runs for row in _task_rows(run)])
    classes = pd.DataFrame([row for run in runs for row in _class_rows(run)])
    summary = pd.DataFrame([_summary_row(run) for run in runs])
    out = Path(tidy_dir)
    out.mkdir(parents=True, exist_ok=True)
    task.to_csv(out / "task_metrics.csv", index=False, encoding="utf-8-sig")
    classes.to_csv(out / "per_class_metrics.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(out / "run_summary.csv", index=False, encoding="utf-8-sig")
    return task, classes, summary


def _fmt(x: Any, digits: int = 2) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    return f"{float(x):.{digits}f}"


def _md_table(headers: list[str], rows: list[list[Any]], aligns: list[str] | None = None) -> str:
    aligns = aligns or ["---"] * len(headers)
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(aligns) + " |"]
    lines += ["| " + " | ".join(str(x) for x in row) + " |" for row in rows]
    return "\n".join(lines) + "\n"


def _latex_table(caption: str, headers: list[str], rows: list[list[Any]], label: str) -> str:
    cols = "l" + "r" * (len(headers) - 1)
    body = [" & ".join(map(str, row)) + r" \\" for row in rows]
    return "\n".join([
        r"\begin{table}[htbp]", r"\centering", f"\\caption{{{caption}}}", f"\\label{{{label}}}",
        f"\\begin{{tabular}}{{{cols}}}", r"\toprule", " & ".join(headers) + r" \\ ", r"\midrule",
        *body, r"\bottomrule", r"\end{tabular}", r"\end{table}", "",
    ])


def build_tables(task: pd.DataFrame, summary: pd.DataFrame, tables_dir: str | Path, audit_csv: str | Path | None = None) -> dict[str, pd.DataFrame]:
    out = Path(tables_dir)
    out.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, pd.DataFrame] = {}

    diag = _latest_run_rows(task[task.scenario == "legacy_head_diagnostic"])
    diag = diag.sort_values(["method", "task_id"]).groupby(["method", "seed"], as_index=False).tail(1)
    diag = diag.sort_values("method", key=lambda s: s.map({m: i for i, m in enumerate(DIAG_ORDER)}))
    diag_table = diag[["method", "bus_accuracy", "train_accuracy", "old_accuracy", "logit_gap"]].copy()
    diag_table["category_replacement"] = (diag_table.bus_accuracy < 1.0) & (diag_table.train_accuracy > 50.0)
    outputs["table1_diagnostic"] = diag_table
    rows = [[r.method, _fmt(r.bus_accuracy), _fmt(r.train_accuracy), _fmt(r.old_accuracy), _fmt(r.logit_gap), "是" if r.category_replacement else "否"] for r in diag_table.itertuples()]
    (out / "表1_交接问题复盘.md").write_text("# 表 1 交接问题复盘\n\n" + _md_table(["方法", "bus accuracy ↑", "train accuracy ↑", "old accuracy ↑", "logit gap ↓", "类别替换"], rows, [":---", "---:", "---:", "---:", "---:", ":---:"]) + "\n注：旧 JPEG/VGG 诊断协议，单种子 1993；不进入正式方法排名。\n", encoding="utf-8")
    (out / "table1_diagnostic.tex").write_text(_latex_table("Legacy failure diagnostic", ["Method", "Bus $\\uparrow$", "Train $\\uparrow$", "Old $\\uparrow$", "Gap $\\downarrow$", "Replace"], rows, "tab:diagnostic"), encoding="utf-8")

    formal = summary[(summary.scenario == "cifar100_b50_5s") & (summary.status == "complete")].copy()
    main_rows = []
    for method in METHOD_ORDER:
        group = formal[formal.method == method]
        required = 1 if method in METHOD_ORDER[:3] else 3
        if len(group) < required:
            main_rows.append([method, f"待运行（{len(group)}/{required} seeds）", "—", "—", "—", "—"])
            continue
        vals = []
        for col in ["aia", "final_aa", "forgetting", "old_accuracy", "new_accuracy"]:
            mean = group[col].mean()
            vals.append(_fmt(mean) if len(group) == 1 else f"{mean:.2f} ± {group[col].std(ddof=1):.2f}")
        main_rows.append([method, *vals])
    main_md = "# 表 2 标准方法主结果\n\n" + _md_table(["方法", "AIA ↑", "final AA ↑", "forgetting ↓", "old acc. ↑", "new acc. ↑"], main_rows, [":---", "---:", "---:", "---:", "---:", "---:"])
    main_md += "\n注：CIFAR-100 B50-5S，20 exemplars/class；主方法必须具备 seeds 1993/1994/1995 才输出均值±标准差。\n"
    (out / "表2_标准方法主结果.md").write_text(main_md, encoding="utf-8")
    (out / "table2_main_results.tex").write_text(_latex_table("CIFAR-100 B50-5S main results", ["Method", "AIA $\\uparrow$", "Final AA $\\uparrow$", "F $\\downarrow$", "Old $\\uparrow$", "New $\\uparrow$"], main_rows, "tab:main"), encoding="utf-8")

    stage_rows = []
    formal_tasks = task[(task.scenario == "cifar100_b50_5s") & (task.status == "complete")]
    for method in METHOD_ORDER:
        g = formal_tasks[formal_tasks.method == method]
        vals = []
        for tid in range(6):
            x = g[g.task_id == tid].overall_accuracy
            vals.append("—" if x.empty else (_fmt(x.mean()) if len(x) == 1 else f"{x.mean():.2f} ± {x.std(ddof=1):.2f}"))
        s = formal[formal.method == method]
        stage_rows.append([method, *vals, "—" if s.empty else _fmt(s.aia.mean()), "—" if s.empty else _fmt(s.final_aa.mean())])
    (out / "表3_逐阶段准确率.md").write_text("# 表 3 逐阶段准确率\n\n" + _md_table(["方法", *[f"Task {i}" for i in range(6)], "AIA", "final AA"], stage_rows), encoding="utf-8")

    factor_rows = []
    means = formal.groupby("method")["aia"].mean().to_dict()
    cells = [("普通分类", "PODNet", "MTD-PODNet"), ("偏差校正", "SS-IL", "MTD-SSIL")]
    for row_name, single, multi in cells:
        gain = means.get(multi, math.nan) - means.get(single, math.nan)
        factor_rows.append([row_name, _fmt(means.get(single)), _fmt(means.get(multi)), _fmt(gain)])
    interaction = (means.get("MTD-SSIL", math.nan) - means.get("SS-IL", math.nan)) - (means.get("MTD-PODNet", math.nan) - means.get("PODNet", math.nan))
    factor_rows.append(["交互增益", "—", "—", _fmt(interaction)])
    (out / "表4_多教师与偏差校正.md").write_text("# 表 4 多教师与偏差校正二因素\n\n" + _md_table(["分类方式", "单教师 AIA", "多教师 AIA", "增益"], factor_rows), encoding="utf-8")

    efficiency_rows = []
    for method in METHOD_ORDER:
        g = formal[formal.method == method]
        if g.empty:
            efficiency_rows.append([method, "—", "—", "—", "—", "—"])
        else:
            hours = g.training_seconds.mean() / 3600.0
            efficiency_rows.append([method, _fmt(g.trainable_parameters.mean() / 1e6), _fmt(g.peak_gpu_memory_mb.mean() / 1024), _fmt(hours, 1), _fmt(g.aia.mean()), _fmt(g.aia.mean() / hours if hours else math.nan)])
    (out / "表5_效率与代价.md").write_text("# 表 5 效率与代价\n\n" + _md_table(["方法", "参数量 (M)", "峰值显存 (GB)", "总训练时间 (h)", "AIA", "AIA/训练小时"], efficiency_rows), encoding="utf-8")

    if audit_csv and Path(audit_csv).exists():
        audit = pd.read_csv(audit_csv)
        outputs["table6_audit"] = audit
        audit_rows = [[r.item, r.legacy, r.standard, r.impact, "已验证" if bool(r.verified) else "待验证"] for r in audit.itertuples()]
        (out / "表6_代码与协议审计.md").write_text("# 表 6 代码与协议审计\n\n" + _md_table(["检查项", "旧实现", "标准实现", "可能影响", "状态"], audit_rows), encoding="utf-8")
    outputs["table2_main"] = pd.DataFrame(main_rows, columns=["method", "aia", "final_aa", "forgetting", "old_accuracy", "new_accuracy"])
    return outputs


def _save_figure(fig: plt.Figure, base: Path) -> None:
    base.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(base.with_suffix(".png"), dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(base.with_suffix(".svg"), bbox_inches="tight", facecolor="white")
    fig.savefig(base.with_suffix(".pdf"), bbox_inches="tight", facecolor="white")
    plt.close(fig)


def build_figures(task: pd.DataFrame, raw_dir: str | Path, figures_dir: str | Path, summary_dir: str | Path) -> pd.DataFrame:
    out, summary_out = Path(figures_dir), Path(summary_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary_out.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({
        "axes.grid": True, "grid.alpha": 0.25, "axes.spines.top": False,
        "axes.spines.right": False, "font.size": 10, "figure.dpi": 120,
    })
    manifest: list[dict[str, str]] = []
    diag = _latest_run_rows(task[task.scenario == "legacy_head_diagnostic"])
    if not diag.empty:
        fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), sharey=True)
        for method in DIAG_ORDER:
            g = diag[diag.method == method].sort_values("task_id")
            if g.empty:
                continue
            axes[0].plot(g.task_id + 1, g.bus_accuracy, marker="o", color=COLORS[method], label=method)
            axes[1].plot(g.task_id + 1, g.train_accuracy, marker="o", color=COLORS[method], label=method)
        axes[0].set(title="bus retention", xlabel="Epoch", ylabel="Per-class accuracy (%)")
        axes[1].set(title="train acquisition", xlabel="Epoch")
        axes[1].legend(ncol=3, frameon=False)
        fig.suptitle("Class-replacement trajectory (wolf requires the subsequent 12→13 run)")
        _save_figure(fig, out / "图1_类别替换轨迹")
        manifest.append({"figure": "图1", "status": "partial", "question": "bus 的归零是否与 train 的获得同步？", "conclusion": "由真实 D0-D4 日志判读；wolf 留待 12→13 扩展。"})

        fig, ax = plt.subplots(figsize=(6.4, 4.0))
        for method in DIAG_ORDER:
            g = diag[diag.method == method].sort_values("task_id")
            if not g.empty:
                ax.plot(g.task_id + 1, g.logit_gap, marker="o", color=COLORS[method], label=method)
        ax.axhline(0, color="#333333", lw=0.8)
        ax.set(title="Old/new logit scale drift", xlabel="Epoch", ylabel="mean(new logits) − mean(old logits)")
        ax.legend(ncol=3, frameon=False)
        _save_figure(fig, out / "图2_logit_gap轨迹")
        manifest.append({"figure": "图2", "status": "complete", "question": "准确率突变是否伴随 old/new 决策尺度漂移？", "conclusion": "比较 gap 越过零点与类别准确率突变的 epoch。"})

    runs = read_runs(raw_dir)
    grad_rows = []
    latest_diag_ids = {
        max((r["run_id"] for r in runs if r["scenario"] == "legacy_head_diagnostic" and r["method"] == method), default="")
        for method in DIAG_ORDER
    }
    for run in runs:
        if run["scenario"] != "legacy_head_diagnostic":
            continue
        if run["run_id"] not in latest_diag_ids:
            continue
        for t in run["tasks"]:
            for loss_name, values in (t.get("gradient_audit") or {}).items():
                grad_rows.append({"method": run["method"], "epoch": t["task_id"] + 1, "loss": loss_name, **values})
    if grad_rows:
        gdf = pd.DataFrame(grad_rows)
        last = gdf.sort_values("epoch").groupby(["method", "loss"], as_index=False).tail(1)
        fig, ax = plt.subplots(figsize=(8, 4.2))
        x = np.arange(len(DIAG_ORDER))
        width = 0.19
        series = [
            ("CE/group old rows", "ce_or_group", "old_row_norm_mean", "#0072B2"),
            ("CE/group new row", "ce_or_group", "new_row_norm", "#56B4E9"),
            ("KD old rows", "kd", "old_row_norm_mean", "#D55E00"),
            ("KD new row", "kd", "new_row_norm", "#E69F00"),
        ]
        for j, (label, loss_name, col, color) in enumerate(series):
            vals = []
            for method in DIAG_ORDER:
                hit = last[(last.method == method) & (last.loss == loss_name)]
                vals.append(float(hit[col].iloc[0]) if not hit.empty else math.nan)
            ax.bar(x + (j - 1.5) * width, vals, width, label=label, color=color)
        ax.set_xticks(x, DIAG_ORDER)
        ax.legend(ncol=2, frameon=False)
        ax.set(title="CE/group and KD gradient magnitude", xlabel="Diagnostic variant", ylabel="Classifier-row gradient L2 norm")
        _save_figure(fig, out / "图3_CE_KD梯度方向")
        manifest.append({"figure": "图3", "status": "complete", "question": "CE 与 KD 分别作用到哪些输出行？", "conclusion": "结合 JSON 中 signed_mean 判断方向，柱高判断强度。"})

    formal = task[(task.scenario == "cifar100_b50_5s") & (task.status == "complete")]
    if not formal.empty:
        core = formal[formal.method.isin(METHOD_ORDER[3:])]
        fig, ax = plt.subplots(figsize=(7, 4.4))
        for method in METHOD_ORDER[3:]:
            g = core[core.method == method]
            if g.empty:
                continue
            stats = g.groupby("task_id").overall_accuracy.agg(["mean", "std"]).reset_index()
            ax.plot(stats.task_id, stats["mean"], marker="o", color=COLORS[method], label=method)
            if stats["std"].notna().all():
                ax.fill_between(stats.task_id, stats["mean"] - stats["std"], stats["mean"] + stats["std"], color=COLORS[method], alpha=.18)
        ax.set(title="CIFAR-100 B50-5S incremental accuracy", xlabel="Incremental task", ylabel="AA (%)")
        ax.legend(frameon=False)
        _save_figure(fig, out / "图4_标准CIL增量准确率")
        manifest.append({"figure": "图4", "status": "complete", "question": "方法是早期领先还是后期更抗遗忘？", "conclusion": "看均值曲线与标准差阴影。"})

        fig, ax = plt.subplots(figsize=(7, 4.4))
        for method in METHOD_ORDER[3:]:
            g = core[core.method == method]
            if g.empty:
                continue
            g = g.copy()
            g["forgetting_proxy"] = g.groupby("seed").old_accuracy.transform("first") - g.old_accuracy
            stats = g.groupby("task_id").forgetting_proxy.agg(["mean", "std"]).reset_index()
            ax.plot(stats.task_id, stats["mean"], marker="o", color=COLORS[method], label=method)
        ax.set(title="Old-class forgetting trajectory", xlabel="Incremental task", ylabel="Old accuracy drop (percentage points)")
        ax.legend(frameon=False)
        _save_figure(fig, out / "图5_遗忘曲线")
        manifest.append({"figure": "图5", "status": "complete", "question": "旧类保持改善是否独立于新类学习？", "conclusion": "下降越小代表稳定性更好。"})

        final = core.sort_values("task_id").groupby(["method", "seed"], as_index=False).tail(1)
        fig, ax = plt.subplots(figsize=(6.4, 4.6))
        for method in METHOD_ORDER[3:]:
            g = final[final.method == method]
            if not g.empty:
                ax.scatter(g.old_accuracy.mean(), g.new_accuracy.mean(), s=70, color=COLORS[method], label=method)
        ax.set(title="Stability–plasticity trade-off", xlabel="Old-class accuracy (%)", ylabel="New-class accuracy (%)")
        ax.legend(frameon=False)
        _save_figure(fig, out / "图6_稳定性可塑性")
        manifest.append({"figure": "图6", "status": "complete", "question": "方法是否同时保持旧类并学习新类？", "conclusion": "越靠右上越好。"})

        fig, ax = plt.subplots(figsize=(6.4, 4.6))
        efficiency = final.groupby("method").agg(old_accuracy=("old_accuracy", "mean"), training_seconds=("training_seconds", "mean"), aia=("overall_accuracy", "mean")).reset_index()
        for r in efficiency.itertuples():
            ax.scatter(r.training_seconds / 3600, r.aia, s=70, color=COLORS.get(r.method, "#777777"), label=r.method)
        ax.set(title="Performance–cost", xlabel="Training time (h)", ylabel="Final AA (%)")
        ax.legend(frameon=False)
        _save_figure(fig, out / "图8_性能成本")
        manifest.append({"figure": "图8", "status": "complete", "question": "多教师收益是否值得时间成本？", "conclusion": "比较 Pareto 前沿。"})

    # Confusion matrix from a key formal method if available, otherwise D0 diagnostic.
    candidate = next((r for r in runs if r["scenario"] == "cifar100_b50_5s" and r["method"] in {"PODNet", "MTD-PODNet", "SS-IL", "MTD-SSIL"}), None)
    candidate = candidate or max((r for r in runs if r["scenario"] == "legacy_head_diagnostic" and r["method"] == "D0"), key=lambda r: r["run_id"], default=None)
    if candidate and candidate["tasks"][-1].get("confusion_matrix"):
        cm = np.asarray(candidate["tasks"][-1]["confusion_matrix"], dtype=float)
        cm = cm / np.maximum(cm.sum(axis=1, keepdims=True), 1)
        fig, ax = plt.subplots(figsize=(7.2, 6.2))
        image = ax.imshow(cm, cmap="viridis", vmin=0, vmax=1, aspect="auto")
        fig.colorbar(image, ax=ax, label="Row-normalized proportion")
        ax.set(title=f"Final confusion matrix: {candidate['method']}", xlabel="Predicted class", ylabel="True class")
        _save_figure(fig, out / "图7_最终混淆矩阵")
        manifest.append({"figure": "图7", "status": "complete", "question": "旧类错误是否集中流向最新类别？", "conclusion": "看旧类行与最新类别列的高值区域。"})

    mdf = pd.DataFrame(manifest)
    mdf.to_csv(summary_out / "figure_manifest.csv", index=False, encoding="utf-8-sig")
    return mdf


def run_consistency_checks(task: pd.DataFrame, summary: pd.DataFrame, summary_dir: str | Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for row in summary.itertuples():
        g = task[task.run_id == row.run_id].sort_values("task_id")
        checks.append({"run_id": row.run_id, "check": "AIA arithmetic mean", "passed": bool(np.isclose(row.aia, g.overall_accuracy.mean()))})
        checks.append({"run_id": row.run_id, "check": "final AA equals curve endpoint", "passed": bool(np.isclose(row.final_aa, g.overall_accuracy.iloc[-1]))})
    formal = summary[summary.scenario == "cifar100_b50_5s"]
    seed_status = {m: sorted(formal[formal.method == m].seed.unique().tolist()) for m in METHOD_ORDER}
    checks.append({"run_id": "GLOBAL", "check": "core methods have seeds 1993/1994/1995", "passed": all(seed_status[m] == [1993, 1994, 1995] for m in METHOD_ORDER[3:]), "details": seed_status})
    report = {"all_numeric_checks_passed": all(x["passed"] for x in checks if x["check"] != "core methods have seeds 1993/1994/1995"), "checks": checks}
    out = Path(summary_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "consistency_checks.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
