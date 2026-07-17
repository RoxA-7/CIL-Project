from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import re


@dataclass(frozen=True)
class AuditFinding:
    item: str
    legacy: str
    standard: str
    impact: str
    verified: bool
    evidence: str


def audit_legacy(legacy_root: str | Path) -> list[dict[str, object]]:
    root = Path(legacy_root)
    texts = {p.name: p.read_text(encoding="utf-8", errors="replace") for p in root.glob("train_CIL*.py")}
    findings = [
        AuditFinding("10→11 分类器初始化", "排除 classifier.6 后整层 Xavier 初始化", "复制全部旧类行，仅初始化新类行", "旧类决策边界被直接删除", "classifier.6" in texts.get("train_CIL.py", ""), str(root / "train_CIL.py")),
        AuditFinding("11→12 预热更新范围", "冻结非 classifier 参数，整个输出层仍更新", "冻结旧输出行或使用重放/偏差校正", "新类 CE 共同压低旧类", "if not name.startswith('classifier.6')" in texts.get("train_CIL12.py", ""), str(root / "train_CIL12.py")),
        AuditFinding("KD 归一化范围", "仅旧类内部 softmax", "同时诊断 old/new 尺度并做校准", "对旧 logits 共同平移不敏感", "student_outputs[:, :11]" in texts.get("train_CIL12.py", ""), str(root / "train_CIL12.py")),
        AuditFinding("双教师调用", "损失签名与调用参数数量不一致", "启动前单测签名并保证损失对学生有梯度", "代码不可运行或教师项无学生梯度", "teacher_outputs10" in texts.get("train_CIL12_10p11.py", ""), str(root / "train_CIL12_10p11.py")),
        AuditFinding("checkpoint 选择", "每 epoch 测试并按测试准确率保存 best", "固定 epoch；测试集只做最终评价", "测试泄漏与乐观偏差", bool(re.search(r"best_(old_)?acc", texts.get("train_CIL12.py", ""))), str(root / "train_CIL12.py")),
    ]
    return [asdict(x) for x in findings]
