from pathlib import Path

FORBIDDEN = (
    "mirror_order", "recent_affine", "selective_recent", "local_pair",
    "controlled_pair", "shared_recent", "hierarchical_group", "b3_affine",
)


def test_public_tree_contains_only_b2_method_family():
    root = Path(__file__).resolve().parents[1]
    code_files = list((root / "src").rglob("*.py")) + list((root / "tools").rglob("*.py")) + list((root / "tests").rglob("*.py"))
    for path in code_files:
        if path.resolve() == Path(__file__).resolve():
            continue
        relative = path.relative_to(root).as_posix().lower()
        content = path.read_text(encoding="utf-8-sig").lower()
        assert not any(token in relative or token in content for token in FORBIDDEN)
