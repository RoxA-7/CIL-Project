from pathlib import Path
import pypdfium2 as pdfium
from PIL import Image

root = Path(__file__).resolve().parents[1]
pdf_path = root / "outputs" / "019f6909-f4fb-7c22-a796-01dc514831c1" / "qa_docx" / "CIL项目重启_组会成果包_final2.pdf"
out = root / "tmp" / "pdfs" / "group_report"
out.mkdir(parents=True, exist_ok=True)
pdf = pdfium.PdfDocument(pdf_path)
for i, page in enumerate(pdf):
    bitmap = page.render(scale=1.8, fill_color=(255, 255, 255, 255), maybe_alpha=True)
    image = bitmap.to_pil()
    if image.mode == "RGBA":
        white = Image.new("RGB", image.size, "white")
        white.paste(image, mask=image.getchannel("A"))
        image = white
    else:
        image = image.convert("RGB")
    image.save(out / f"page-{i + 1:02d}.png")
print(f"pages={len(pdf)}")
print(out)
