from __future__ import annotations

import json
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "output" / "pdf" / "CIL类增量学习完整课程讲义.pdf"
OUT = ROOT / "tmp" / "pdfs" / "full_course"
PAGES = OUT / "pages"
CONTACTS = OUT / "contacts"


def render_pages() -> int:
    PAGES.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument(str(PDF))
    for i, page in enumerate(doc):
        bitmap = page.render(scale=1.35)
        image = bitmap.to_pil().convert("RGB")
        image.save(PAGES / f"page_{i + 1:03d}.png", quality=92)
    return len(doc)


def contact_sheets(page_count: int, per_sheet: int = 16) -> list[str]:
    CONTACTS.mkdir(parents=True, exist_ok=True)
    font_path = Path(r"C:\Windows\Fonts\arial.ttf")
    font = ImageFont.truetype(str(font_path), 18)
    page_paths = [PAGES / f"page_{i:03d}.png" for i in range(1, page_count + 1)]
    outputs = []
    for start in range(0, page_count, per_sheet):
        batch = page_paths[start : start + per_sheet]
        thumb_w, thumb_h = 270, 382
        label_h, gap = 28, 12
        cols, rows = 4, 4
        sheet = Image.new("RGB", (cols * (thumb_w + gap) + gap, rows * (thumb_h + label_h + gap) + gap), "#d9dde1")
        draw = ImageDraw.Draw(sheet)
        for j, path in enumerate(batch):
            page = Image.open(path).convert("RGB")
            page.thumbnail((thumb_w, thumb_h), Image.Resampling.LANCZOS)
            x = gap + (j % cols) * (thumb_w + gap)
            y = gap + (j // cols) * (thumb_h + label_h + gap)
            sheet.paste(page, (x + (thumb_w - page.width)//2, y))
            label = f"Page {start + j + 1}"
            draw.text((x + 4, y + thumb_h + 3), label, fill="#1f2933", font=font)
        out = CONTACTS / f"contact_{start + 1:03d}_{start + len(batch):03d}.png"
        sheet.save(out)
        outputs.append(str(out))
    return outputs


def text_audit() -> dict:
    reader = PdfReader(str(PDF))
    texts = [(page.extract_text() or "") for page in reader.pages]
    joined = "\n".join(texts)
    missing_lessons = [i for i in range(1, 46) if f"第 {i} 课" not in joined]
    short_pages = [i + 1 for i, text in enumerate(texts) if len(text.strip()) < 20]
    checks = {
        "pages": len(texts),
        "file_bytes": PDF.stat().st_size,
        "missing_lessons": missing_lessons,
        "short_text_pages": short_pages,
        "replacement_char_count": joined.count("�"),
        "contains_d0": "D0 当前实现" in joined,
        "contains_b50_5s": "B50-5S" in joined,
        "contains_appendix_f": "附录 F" in joined,
        "min_text_chars": min(len(t.strip()) for t in texts),
        "max_text_chars": max(len(t.strip()) for t in texts),
    }
    (OUT / "qa_report.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")
    return checks


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    count = render_pages()
    contacts = contact_sheets(count)
    report = text_audit()
    print(json.dumps({"report": report, "contacts": contacts}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
