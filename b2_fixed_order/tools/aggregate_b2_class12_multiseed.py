from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import uuid
from typing import Any, Mapping

from lwf_revision.b2_class12_multiseed import (
    aggregate_multiseed_confirmation,
    b2_confirmation_checks,
    old_class_risk_flags,
)


BUSINESS_FILES = (
    "seed2026_recomputed_for_multiseed.json",
    "multiseed_summary.json",
    "input_sha256.json",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("aggregate input JSON root must be an object")
    return payload


def _write_json(path: Path, payload: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _verify_tree(root: Path) -> str:
    root = Path(root)
    if not root.is_dir():
        raise ValueError("aggregate signed input tree is missing")
    manifest = _read_json(root / "artifact_sha256.json")
    if {path.name for path in root.iterdir()} != set(manifest) | {
        "artifact_sha256.json",
        "COMPLETE.json",
    }:
        raise ValueError("aggregate signed input tree contents mismatch")
    for name, digest in manifest.items():
        if _sha256(root / name) != digest:
            raise ValueError("aggregate signed input tree SHA256 mismatch")
    complete = _read_json(root / "COMPLETE.json")
    manifest_sha = _sha256(root / "artifact_sha256.json")
    if (
        complete.get("status") != "complete"
        or complete.get("artifact_manifest_sha256") != manifest_sha
    ):
        raise ValueError("aggregate signed input tree COMPLETE mismatch")
    return manifest_sha


def _normalize_roots(roots: Mapping[int, Path], *, label: str) -> dict[int, Path]:
    if not isinstance(roots, Mapping) or set(roots) != {2026, 2027, 2028}:
        raise ValueError(f"{label} must bind exactly seeds 2026, 2027, and 2028")
    return {seed: Path(roots[seed]) for seed in (2026, 2027, 2028)}


def _seed_evidence(
    *, seed: int, result_root: Path, audit_root: Path
) -> tuple[dict[str, Any], dict[str, str]]:
    result_manifest = _verify_tree(result_root)
    audit_manifest = _verify_tree(audit_root)
    metrics = _read_json(result_root / "fold_metrics.json")
    folds = metrics.get("folds")
    aggregate = metrics.get("aggregate")
    if (
        not isinstance(folds, list)
        or len(folds) != 5
        or not isinstance(aggregate, dict)
        or not {"b0", "b2"}.issubset(aggregate)
        or (seed != 2026 and set(aggregate) != {"b0", "b2"})
    ):
        raise ValueError("aggregate seed metrics are invalid")
    deltas = []
    for fold, row in enumerate(folds):
        if (
            not isinstance(row, dict)
            or row.get("fold") != fold
            or not {"b0", "b2"}.issubset(row)
            or (seed != 2026 and set(row) != {"fold", "b0", "b2"})
        ):
            raise ValueError("aggregate seed fold metrics are invalid")
        deltas.append(
            float(row["b2"]["triple_harmonic_accuracy"])
            - float(row["b0"]["triple_harmonic_accuracy"])
        )
    audit = _read_json(audit_root / "audit_report.json")
    truth = audit.get("all_pass") is True and audit.get("access_flags_pass") is True
    equivalence = audit.get("b1_b2_equivalence_passed") is True
    checks = b2_confirmation_checks(
        b0=aggregate["b0"],
        b2=aggregate["b2"],
        triple_h_fold_deltas=deltas,
        truth_passed=truth,
        equivalence_passed=equivalence,
        audit_passed=audit.get("all_pass") is True,
    )
    risk = old_class_risk_flags(b0=aggregate["b0"], b2=aggregate["b2"])
    return (
        {
            "seed": seed,
            "passed": checks["passed"],
            "b0": aggregate["b0"],
            "b2": aggregate["b2"],
            "checks": checks,
            "fold_triple_h_deltas": deltas,
            "old_class_risk": risk,
        },
        {"result_manifest": result_manifest, "audit_manifest": audit_manifest},
    )


def verify_seed2026_reuse(
    *,
    result_root: Path,
    audit_root: Path,
    expected_result_manifest_sha256: str,
    expected_audit_manifest_sha256: str,
    output_root: Path,
) -> dict[str, Any]:
    output_root = Path(output_root)
    if output_root.exists() or any(output_root.parent.glob(output_root.name + ".tmp.*")):
        raise FileExistsError("seed2026 reuse verification output conflict")
    evidence, bindings = _seed_evidence(
        seed=2026, result_root=Path(result_root), audit_root=Path(audit_root)
    )
    if (
        bindings["result_manifest"] != expected_result_manifest_sha256.lower()
        or bindings["audit_manifest"] != expected_audit_manifest_sha256.lower()
    ):
        raise ValueError("seed2026 frozen evidence SHA256 mismatch")
    report = {
        "schema": "b2_class12_seed2026_read_only_import_v1",
        "all_pass": True,
        "seed": 2026,
        "source_result_manifest_sha256": bindings["result_manifest"],
        "source_audit_manifest_sha256": bindings["audit_manifest"],
        "training_rerun": False,
        "capture_rerun": False,
        "diagnostic_369_rerun": False,
        "checks": evidence["checks"],
    }
    temporary = output_root.with_name(output_root.name + ".tmp." + uuid.uuid4().hex)
    output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary.mkdir()
    try:
        _write_json(temporary / "reuse_verification.json", report)
        _write_json(
            temporary / "artifact_sha256.json",
            {"reuse_verification.json": _sha256(temporary / "reuse_verification.json")},
        )
        _write_json(
            temporary / "COMPLETE.json",
            {
                "schema": "b2_class12_seed2026_read_only_import_complete_v1",
                "status": "complete",
                "artifact_manifest_sha256": _sha256(temporary / "artifact_sha256.json"),
            },
        )
        os.replace(temporary, output_root)
    except Exception:
        if temporary.exists():
            for path in temporary.iterdir():
                path.unlink()
            temporary.rmdir()
        raise
    return report


def aggregate_b2_class12_evidence(
    *,
    result_roots: Mapping[int, Path],
    audit_roots: Mapping[int, Path],
    seed2026_expected_result_manifest_sha256: str,
    seed2026_expected_audit_manifest_sha256: str,
    output_root: Path,
    mode: str = "formal",
) -> None:
    result_paths = _normalize_roots(result_roots, label="result roots")
    audit_paths = _normalize_roots(audit_roots, label="audit roots")
    output_root = Path(output_root)
    if output_root.exists() or any(output_root.parent.glob(output_root.name + ".tmp.*")):
        raise FileExistsError("aggregate output conflict")
    if mode not in {"formal", "contract-test"}:
        raise ValueError("aggregate mode is invalid")
    evidence = []
    bindings = {}
    for seed in (2026, 2027, 2028):
        row, hashes = _seed_evidence(
            seed=seed,
            result_root=result_paths[seed],
            audit_root=audit_paths[seed],
        )
        evidence.append(row)
        bindings[str(seed)] = hashes
    if (
        bindings["2026"]["result_manifest"]
        != seed2026_expected_result_manifest_sha256.lower()
        or bindings["2026"]["audit_manifest"]
        != seed2026_expected_audit_manifest_sha256.lower()
    ):
        raise ValueError("seed2026 frozen evidence SHA256 mismatch")
    summary = aggregate_multiseed_confirmation(evidence)
    seed2026 = evidence[0]
    reused = {
        "schema": "b2_class12_seed2026_recomputed_v1",
        "seed": 2026,
        "source_result_manifest_sha256": bindings["2026"]["result_manifest"],
        "source_audit_manifest_sha256": bindings["2026"]["audit_manifest"],
        "training_rerun": False,
        "capture_rerun": False,
        "diagnostic_369_rerun": False,
        "checks": seed2026["checks"],
        "old_class_risk": seed2026["old_class_risk"],
        "b2": seed2026["b2"],
    }
    temporary = output_root.with_name(output_root.name + ".tmp." + uuid.uuid4().hex)
    output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary.mkdir()
    try:
        _write_json(temporary / BUSINESS_FILES[0], reused)
        _write_json(temporary / BUSINESS_FILES[1], summary)
        _write_json(
            temporary / BUSINESS_FILES[2],
            {
                "schema": "b2_class12_multiseed_input_sha256_v1",
                "mode": mode,
                "seed_bindings": bindings,
            },
        )
        _write_json(
            temporary / "artifact_sha256.json",
            {name: _sha256(temporary / name) for name in BUSINESS_FILES},
        )
        _write_json(
            temporary / "COMPLETE.json",
            {
                "schema": "b2_class12_multiseed_complete_v1",
                "status": "complete",
                "artifact_manifest_sha256": _sha256(
                    temporary / "artifact_sha256.json"
                ),
            },
        )
        os.replace(temporary, output_root)
    except Exception:
        if temporary.exists():
            for path in temporary.iterdir():
                path.unlink()
            temporary.rmdir()
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    for seed in (2026, 2027, 2028):
        parser.add_argument(
            f"--seed{seed}-result-root", type=Path, required=(seed == 2026)
        )
        parser.add_argument(
            f"--seed{seed}-audit-root", type=Path, required=(seed == 2026)
        )
    parser.add_argument("--seed2026-result-manifest-sha256", required=True)
    parser.add_argument("--seed2026-audit-manifest-sha256", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--verify-seed2026-only", action="store_true")
    args = parser.parse_args()
    if args.verify_seed2026_only:
        verify_seed2026_reuse(
            result_root=args.seed2026_result_root,
            audit_root=args.seed2026_audit_root,
            expected_result_manifest_sha256=args.seed2026_result_manifest_sha256,
            expected_audit_manifest_sha256=args.seed2026_audit_manifest_sha256,
            output_root=args.output_root,
        )
        print("B2_CLASS12_SEED2026_READ_ONLY_IMPORT_OK")
        return 0
    if any(
        getattr(args, f"seed{seed}_{kind}_root") is None
        for seed in (2027, 2028)
        for kind in ("result", "audit")
    ):
        parser.error("seed2027 and seed2028 roots are required for aggregate mode")
    aggregate_b2_class12_evidence(
        result_roots={
            seed: getattr(args, f"seed{seed}_result_root")
            for seed in (2026, 2027, 2028)
        },
        audit_roots={
            seed: getattr(args, f"seed{seed}_audit_root")
            for seed in (2026, 2027, 2028)
        },
        seed2026_expected_result_manifest_sha256=args.seed2026_result_manifest_sha256,
        seed2026_expected_audit_manifest_sha256=args.seed2026_audit_manifest_sha256,
        output_root=args.output_root,
    )
    print("B2_CLASS12_MULTISEED_AGGREGATE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
