from __future__ import annotations

import csv
import json
import math
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.table import WD_ALIGN_VERTICAL, WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "019f6909-f4fb-7c22-a796-01dc514831c1"
DOCX = OUT / "CIL项目重启_组会成果包.docx"
MARKDOWN = ROOT / "results" / "summary" / "组会成果包.md"
FIG = ROOT / "results" / "figures"
RAW = ROOT / "results" / "raw"
TIDY = ROOT / "results" / "tidy"

BLUE = "2E74B5"
DARK_BLUE = "1F4D78"
INK = "18212B"
MUTED = "5F6B76"
HEADER_FILL = "E8EEF5"
CALLOUT_FILL = "F4F6F9"
GREEN = "1B6B50"
ORANGE = "A64B00"
RED = "9B1C1C"


def set_run_font(run, size=11, bold=None, italic=None, color=INK, latin="Calibri", east_asia="Microsoft YaHei"):
    run.font.name = latin
    run._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), latin)
    run._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), latin)
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), east_asia)
    run.font.size = Pt(size)
    run.font.color.rgb = RGBColor.from_string(color)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic


def set_spacing(p, before=0, after=6, line=1.25, keep_next=False, keep_together=False):
    pf = p.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing = line
    pf.keep_with_next = keep_next
    pf.keep_together = keep_together


def shade(element, fill):
    ppr = element.get_or_add_pPr() if element.tag.endswith("}p") else element.get_or_add_tcPr()
    shd = ppr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        ppr.append(shd)
    shd.set(qn("w:fill"), fill)


def paragraph_left_border(p, color=BLUE, size="18"):
    ppr = p._p.get_or_add_pPr()
    pbdr = ppr.find(qn("w:pBdr"))
    if pbdr is None:
        pbdr = OxmlElement("w:pBdr")
        ppr.append(pbdr)
    left = OxmlElement("w:left")
    left.set(qn("w:val"), "single")
    left.set(qn("w:sz"), size)
    left.set(qn("w:space"), "8")
    left.set(qn("w:color"), color)
    pbdr.append(left)


def paragraph_bottom_border(p, color=BLUE, size="18"):
    ppr = p._p.get_or_add_pPr()
    pbdr = ppr.find(qn("w:pBdr"))
    if pbdr is None:
        pbdr = OxmlElement("w:pBdr")
        ppr.append(pbdr)
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), size)
    bottom.set(qn("w:space"), "8")
    bottom.set(qn("w:color"), color)
    pbdr.append(bottom)


def add_field(paragraph, instruction):
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = instruction
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t")
    text.text = "1"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.extend([begin, instr, separate, text, end])
    set_run_font(run, size=9, color=MUTED)


def configure_section(section, landscape=False, margins=1.0):
    section.orientation = WD_ORIENT.LANDSCAPE if landscape else WD_ORIENT.PORTRAIT
    section.page_width = Inches(11 if landscape else 8.5)
    section.page_height = Inches(8.5 if landscape else 11)
    section.top_margin = Inches(margins)
    section.bottom_margin = Inches(margins)
    section.left_margin = Inches(margins)
    section.right_margin = Inches(margins)
    section.header_distance = Inches(0.492)
    section.footer_distance = Inches(0.492)


def set_header_footer(section):
    hp = section.header.paragraphs[0]
    hp.clear()
    hp.paragraph_format.tab_stops.add_tab_stop(Inches(6.5), WD_TAB_ALIGNMENT.RIGHT)
    r = hp.add_run("CIL Restart | 组会成果包\t2026-07-17")
    set_run_font(r, size=8.5, color=MUTED)
    set_spacing(hp, after=0, line=1.0)
    fp = section.footer.paragraphs[0]
    fp.clear()
    fp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r = fp.add_run("第 ")
    set_run_font(r, size=9, color=MUTED)
    add_field(fp, "PAGE")
    r = fp.add_run(" 页")
    set_run_font(r, size=9, color=MUTED)


def set_style(style, size, color, before, after, line=1.25, bold=False):
    style.font.name = "Calibri"
    style._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), "Calibri")
    style._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), "Calibri")
    style._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    style.font.size = Pt(size)
    style.font.color.rgb = RGBColor.from_string(color)
    style.font.bold = bold
    pf = style.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing = line


def create_numbering(doc, bullet=False):
    numbering = doc.part.numbering_part.element
    existing = [int(x.get(qn("w:abstractNumId"))) for x in numbering.findall(qn("w:abstractNum"))]
    abstract_id = max(existing, default=-1) + 1
    abstract = OxmlElement("w:abstractNum")
    abstract.set(qn("w:abstractNumId"), str(abstract_id))
    multi = OxmlElement("w:multiLevelType")
    multi.set(qn("w:val"), "singleLevel")
    abstract.append(multi)
    lvl = OxmlElement("w:lvl")
    lvl.set(qn("w:ilvl"), "0")
    start = OxmlElement("w:start")
    start.set(qn("w:val"), "1")
    num_fmt = OxmlElement("w:numFmt")
    num_fmt.set(qn("w:val"), "bullet" if bullet else "decimal")
    lvl_text = OxmlElement("w:lvlText")
    lvl_text.set(qn("w:val"), "•" if bullet else "%1.")
    lvl_jc = OxmlElement("w:lvlJc")
    lvl_jc.set(qn("w:val"), "left")
    ppr = OxmlElement("w:pPr")
    tabs = OxmlElement("w:tabs")
    tab = OxmlElement("w:tab")
    tab.set(qn("w:val"), "num")
    tab.set(qn("w:pos"), "540")
    tabs.append(tab)
    ind = OxmlElement("w:ind")
    ind.set(qn("w:left"), "540")
    ind.set(qn("w:hanging"), "271")
    spacing = OxmlElement("w:spacing")
    spacing.set(qn("w:after"), "80")
    spacing.set(qn("w:line"), "300")
    spacing.set(qn("w:lineRule"), "auto")
    ppr.extend([tabs, ind, spacing])
    lvl.extend([start, num_fmt, lvl_text, lvl_jc, ppr])
    abstract.append(lvl)
    numbering.append(abstract)
    nums = [int(x.get(qn("w:numId"))) for x in numbering.findall(qn("w:num"))]
    num_id = max(nums, default=0) + 1
    num = OxmlElement("w:num")
    num.set(qn("w:numId"), str(num_id))
    abstract_ref = OxmlElement("w:abstractNumId")
    abstract_ref.set(qn("w:val"), str(abstract_id))
    num.append(abstract_ref)
    numbering.append(num)
    return num_id


def add_list_item(doc, text, num_id):
    p = doc.add_paragraph()
    ppr = p._p.get_or_add_pPr()
    numpr = OxmlElement("w:numPr")
    ilvl = OxmlElement("w:ilvl")
    ilvl.set(qn("w:val"), "0")
    numid = OxmlElement("w:numId")
    numid.set(qn("w:val"), str(num_id))
    numpr.extend([ilvl, numid])
    ppr.append(numpr)
    r = p.add_run(text)
    set_run_font(r)
    return p


def add_plain_item(doc, text):
    p = doc.add_paragraph()
    set_spacing(p, before=0, after=5, line=1.25, keep_together=True)
    p.paragraph_format.left_indent = Inches(0.19)
    p.paragraph_format.first_line_indent = Inches(0)
    r = p.add_run(text)
    set_run_font(r)
    return p


def add_labeled_item(doc, label, text):
    p = doc.add_paragraph()
    set_spacing(p, before=0, after=5, line=1.25, keep_together=True)
    p.paragraph_format.left_indent = Inches(0.19)
    r = p.add_run(label + "：")
    set_run_font(r, bold=True, color=DARK_BLUE)
    r = p.add_run(text)
    set_run_font(r)
    return p


def set_cell_margins(cell, top=80, start=120, bottom=80, end=120):
    tcpr = cell._tc.get_or_add_tcPr()
    tc_mar = tcpr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tcpr.append(tc_mar)
    for m, v in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{m}"))
        if node is None:
            node = OxmlElement(f"w:{m}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(v))
        node.set(qn("w:type"), "dxa")


def set_cell_border(cell, edge, val="single", sz="6", color="111111"):
    tcpr = cell._tc.get_or_add_tcPr()
    borders = tcpr.find(qn("w:tcBorders"))
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tcpr.append(borders)
    node = borders.find(qn(f"w:{edge}"))
    if node is None:
        node = OxmlElement(f"w:{edge}")
        borders.append(node)
    node.set(qn("w:val"), val)
    node.set(qn("w:sz"), sz)
    node.set(qn("w:color"), color)


def set_table_geometry(table, widths_dxa, indent=120):
    total = sum(widths_dxa)
    table.autofit = False
    tblpr = table._tbl.tblPr
    tblw = tblpr.find(qn("w:tblW"))
    if tblw is None:
        tblw = OxmlElement("w:tblW")
        tblpr.append(tblw)
    tblw.set(qn("w:w"), str(total))
    tblw.set(qn("w:type"), "dxa")
    tblind = tblpr.find(qn("w:tblInd"))
    if tblind is None:
        tblind = OxmlElement("w:tblInd")
        tblpr.append(tblind)
    tblind.set(qn("w:w"), str(indent))
    tblind.set(qn("w:type"), "dxa")
    grid = table._tbl.tblGrid
    for child in list(grid):
        grid.remove(child)
    for w in widths_dxa:
        col = OxmlElement("w:gridCol")
        col.set(qn("w:w"), str(w))
        grid.append(col)
    for row in table.rows:
        for i, cell in enumerate(row.cells):
            tcpr = cell._tc.get_or_add_tcPr()
            tcw = tcpr.find(qn("w:tcW"))
            if tcw is None:
                tcw = OxmlElement("w:tcW")
                tcpr.append(tcw)
            tcw.set(qn("w:w"), str(widths_dxa[i]))
            tcw.set(qn("w:type"), "dxa")
            set_cell_margins(cell)


def make_three_line_table(doc, headers, rows, widths_dxa, font_size=9, rank_specs=None):
    table = doc.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    set_table_geometry(table, widths_dxa)
    for i, text in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = ""
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_spacing(p, after=0, line=1.0)
        r = p.add_run(str(text))
        set_run_font(r, size=font_size, bold=True)
        shade(cell._tc, HEADER_FILL)
        set_cell_border(cell, "top", sz="12")
        set_cell_border(cell, "bottom", sz="6")
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    trpr = table.rows[0]._tr.get_or_add_trPr()
    repeat = OxmlElement("w:tblHeader")
    repeat.set(qn("w:val"), "true")
    trpr.append(repeat)
    for ridx, row in enumerate(rows):
        cells = table.add_row().cells
        for cidx, value in enumerate(row):
            cells[cidx].text = ""
            p = cells[cidx].paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT if cidx == 0 else WD_ALIGN_PARAGRAPH.RIGHT
            set_spacing(p, after=0, line=1.0)
            r = p.add_run(str(value))
            set_run_font(r, size=font_size)
            if rank_specs and cidx in rank_specs:
                best_rows, second_rows = rank_specs[cidx]
                if ridx in best_rows:
                    r.bold = True
                elif ridx in second_rows:
                    r.underline = True
            cells[cidx].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            if ridx == len(rows) - 1:
                set_cell_border(cells[cidx], "bottom", sz="12")
    return table


def add_caption(doc, text):
    p = doc.add_paragraph(style="Caption")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_spacing(p, before=4, after=8, line=1.0, keep_together=True)
    r = p.add_run(text)
    set_run_font(r, size=9, italic=True, color=MUTED)
    return p


def add_figure(doc, filename, caption, width=6.2):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_spacing(p, before=4, after=0, line=1.0, keep_next=True, keep_together=True)
    shape = p.add_run().add_picture(str(FIG / filename), width=Inches(width))
    shape._inline.docPr.set("descr", caption)
    shape._inline.docPr.set("title", filename)
    add_caption(doc, caption)


def add_callout(doc, label, text, color=BLUE):
    p = doc.add_paragraph()
    set_spacing(p, before=4, after=10, line=1.25, keep_together=True)
    shade(p._p, CALLOUT_FILL)
    paragraph_left_border(p, color=color)
    r = p.add_run(label + "：")
    set_run_font(r, bold=True, color=color)
    r = p.add_run(text)
    set_run_font(r)
    return p


def latest_diag_rows():
    runs = []
    for path in RAW.glob("diag_*.json"):
        run = json.loads(path.read_text(encoding="utf-8"))
        runs.append(run)
    out = []
    for method in ["D0", "D1", "D2", "D3", "D4"]:
        candidates = [r for r in runs if r["method"] == method]
        run = max(candidates, key=lambda r: r["run_id"])
        t = run["tasks"][-1]
        out.append([method, f"{t['bus_accuracy']:.2f}", f"{t['train_accuracy']:.2f}", f"{t['old_accuracy']:.2f}", f"{t['logit_gap']:.2f}", "是" if t["bus_accuracy"] < 1 and t["train_accuracy"] > 50 else "否"])
    return out


def build_document():
    OUT.mkdir(parents=True, exist_ok=True)
    MARKDOWN.parent.mkdir(parents=True, exist_ok=True)
    doc = Document()
    section = doc.sections[0]
    configure_section(section)
    set_header_footer(section)
    styles = doc.styles
    set_style(styles["Normal"], 11, INK, 0, 6, 1.25)
    set_style(styles["Heading 1"], 16, BLUE, 18, 10, 1.0, True)
    set_style(styles["Heading 2"], 13, BLUE, 14, 7, 1.0, True)
    set_style(styles["Heading 3"], 12, DARK_BLUE, 10, 5, 1.0, True)
    set_style(styles["Caption"], 9, MUTED, 4, 8, 1.0, False)
    bullet_id = create_numbering(doc, bullet=True)
    number_id = create_numbering(doc, bullet=False)

    # memo_masthead first-page pattern; title size is a named compact-reference override.
    p = doc.add_paragraph()
    set_spacing(p, before=14, after=4, line=1.0, keep_next=True)
    r = p.add_run("研究重启成果包")
    set_run_font(r, size=10, bold=True, color=BLUE)
    p = doc.add_paragraph()
    set_spacing(p, before=0, after=5, line=1.0, keep_next=True)
    r = p.add_run("类增量学习项目重启")
    set_run_font(r, size=24, bold=True, color=DARK_BLUE)
    p = doc.add_paragraph()
    set_spacing(p, before=0, after=14, line=1.1, keep_next=True)
    r = p.add_run("故障机制、D0–D4 诊断证据、标准复现状态与组会答辩手册")
    set_run_font(r, size=13, color=MUTED)
    paragraph_bottom_border(p, color=BLUE, size="18")
    for label, value in [
        ("状态", "D0–D4 已完成；标准 B50-5S 尚未进入正式主表"),
        ("正式协议", "CIFAR-100 / ResNet-32 / B50-5S / 20 exemplars per class / 3 seeds"),
        ("证据边界", "旧 VGG/JPEG 仅用于故障诊断，不参与正式排名"),
        ("生成日期", "2026-07-17"),
    ]:
        p = doc.add_paragraph()
        set_spacing(p, after=2, line=1.1)
        r = p.add_run(label + "：")
        set_run_font(r, bold=True)
        r = p.add_run(value)
        set_run_font(r)

    add_callout(doc, "结论先行", "D0 成功复现 bus→train 替换；单独冻结旧分类器行（D2）仍不能解决 old/new 尺度竞争；加入每类 20 个旧样本重放（D3/D4）把旧类平均准确率从接近 0 提升到约 59%，但 bus 仅恢复到 10%，因此只能说“显著缓解”，不能说“已解决”。", GREEN)

    doc.add_heading("1. 为什么旧结果不可信", level=1)
    points = [
        "RGB/BGR 修复、优化器切换和训练轮次增加同时发生，准确率提升无法做单因素归因。",
        "10→11 阶段重置整个输出层，旧类分类器知识被直接删除。",
        "11→12 与 12→13 虽复制旧行，但预热仍更新整个输出层，且训练数据只有新类。",
        "旧类内部 KD 对全部旧 logits 的共同平移不敏感，无法维护 old/new 的绝对决策尺度。",
        "双教师脚本既不是同阶段多样化教师，又存在参数缺失和无学生梯度的损失项；测试集还被用于挑选 best epoch。",
    ]
    for text in points:
        add_list_item(doc, text, number_id)

    doc.add_heading("2. 类别替换的公式链", level=1)
    p = doc.add_paragraph()
    set_spacing(p, after=4)
    r = p.add_run("交叉熵梯度：")
    set_run_font(r, bold=True)
    r = p.add_run("∂L/∂zₖ = pₖ − 1[k=y]。新类是目标时，梯度下降抬高新类 logit，并压低所有旧类 logits。")
    set_run_font(r)
    p = doc.add_paragraph()
    set_spacing(p, after=8)
    r = p.add_run("KD 平移不变性：")
    set_run_font(r, bold=True)
    r = p.add_run("softmax((z+c·1)/T)=softmax(z/T)。因此只在旧类内部做 KD，看不见旧类整体下移。")
    set_run_font(r)
    add_callout(doc, "数值验收", "真实原始 JSON 中 kd_common_shift_delta = 1.19×10⁻⁷，说明给所有旧 logits 加同一常数后 KD 基本不变。", ORANGE)

    doc.add_heading("3. D0–D4 诊断结果", level=1)
    diag = latest_diag_rows()
    rank_specs = {
        1: ({3, 4}, set()),
        2: ({0, 1, 2}, {3, 4}),
        3: ({4}, {3}),
        4: ({3}, {4}),
    }
    make_three_line_table(doc, ["方法", "bus ↑", "train ↑", "old ↑", "logit gap ↓", "替换"], diag, [936, 1656, 1656, 1656, 1728, 1728], font_size=9, rank_specs=rank_specs)
    add_caption(doc, "表 1 交接问题复盘。旧 VGG/JPEG 诊断协议，seed=1993，固定 6 epochs；不进入正式方法排名。")
    p = doc.add_paragraph()
    set_spacing(p, after=8)
    r = p.add_run("解释：")
    set_run_font(r, bold=True)
    r = p.add_run("D2 冻结旧行后 old accuracy 仍只有 1.36%，说明问题不只是旧权重漂移，新类 logit 抬高也会跨过旧类决策边界。D3/D4 的改善证明样本不平衡与尺度偏差是关键因素。")
    set_run_font(r)

    add_figure(doc, "图1_类别替换轨迹.png", "图 1 bus/train 类别替换轨迹。wolf 需在后续 12→13 扩展中补齐，当前不伪造历史数值。")
    add_figure(doc, "图2_logit_gap轨迹.png", "图 2 old/new logit gap 轨迹。应与图 1 按 epoch 对齐解读。")
    add_figure(doc, "图3_CE_KD梯度方向.png", "图 3 CE/group 与 KD 对旧行、新行的梯度强度。梯度方向的 signed mean 保存在原始 JSON。")
    add_figure(doc, "图7_最终混淆矩阵.png", "图 7 D0 最终混淆矩阵。正式方法完成后将替换为 PODNet/MTD/SS-IL 关键方法矩阵。")

    doc.add_heading("4. 标准 CIFAR-100 主结果状态", level=1)
    pending = [[m, "待运行（0/1 seed）" if m in {"FineTune", "LwF", "Replay"} else "待运行（0/3 seeds）", "—", "—", "—", "—"] for m in ["FineTune", "LwF", "Replay", "PODNet", "MTD-PODNet", "SS-IL", "MTD-SSIL"]]
    make_three_line_table(doc, ["方法", "AIA ↑", "final AA ↑", "forgetting ↓", "old ↑", "new ↑"], pending, [1540, 1990, 1450, 1580, 1400, 1400], font_size=8.5)
    add_caption(doc, "表 2 标准主结果占位。只有完整 per-class、混淆矩阵、logit 与分类器统计且满足种子要求的运行才能进入本表。")
    add_callout(doc, "当前阻点", "作者 CLearning 固定在 Python 3.9 / PyTorch 1.11 / continuum 1.2.4；当前 Python 3.12 / PyTorch 2.5.1 环境安装 continuum 首次超时。官方源码与配置已接入，但正式训练尚未启动，避免产生不可比较的半成品数字。", RED)

    doc.add_heading("5. 标准实验执行顺序", level=1)
    exec_steps = [
        "先让 scripts/check_official.py 返回 ready=true，并完成 1 epoch / 2 task 冒烟；验证数据、模型、日志和评估插桩。",
        "运行 FineTune、LwF、Replay 的 seed 1993，确认遗忘与重放的 sanity 关系。",
        "运行 PODNet 与 MTD-PODNet 单种子；若 AIA 与论文差超过 2 个百分点，停止扩展，只排查环境和协议。",
        "通过后完成 PODNet、MTD-PODNet、SS-IL、MTD-SSIL 三种子；仅在提升超过标准差时表述为稳定增益。",
        "由 raw JSON 一键重建表 2–5 与图 4–8，检查 AIA、曲线终点和成本数据一致。",
    ]
    for label, text in zip(["步骤一", "步骤二", "步骤三", "步骤四", "步骤五"], exec_steps):
        add_labeled_item(doc, label, text)

    # Named layout override: the code audit needs a 9-inch fixed-width table.
    landscape = doc.add_section(WD_SECTION.NEW_PAGE)
    configure_section(landscape, landscape=True, margins=1.0)
    set_header_footer(landscape)
    doc.add_heading("6. 代码与协议审计", level=1)
    with (TIDY / "legacy_code_audit.csv").open(encoding="utf-8-sig", newline="") as f:
        audit = list(csv.DictReader(f))
    audit_rows = [[r["item"], r["legacy"], r["standard"], r["impact"], "已验证" if r["verified"].lower() == "true" else "待验证"] for r in audit]
    make_three_line_table(doc, ["检查项", "旧实现", "标准实现", "可能影响", "状态"], audit_rows, [1500, 2250, 2250, 2250, 750], font_size=8)
    add_caption(doc, "表 6 代码与协议审计。横向页面是名为 audit_landscape 的唯一版式覆盖。")

    portrait = doc.add_section(WD_SECTION.NEW_PAGE)
    configure_section(portrait)
    set_header_footer(portrait)
    doc.add_heading("7. 组会叙事与答辩", level=1)
    for text in [
        "旧结果为什么不可信：多个变量同时改变、分类器继承错误、测试泄漏。",
        "类别替换的根因：新类 CE 改变 old/new 尺度，而旧类内部 KD 对共同平移失明。",
        "诊断证据：D0 复现；D2 说明冻结旧行不够；D3/D4 说明重放与尺度校准有效但未彻底解决。",
        "正式比较还缺什么：作者协议复现、三种子、完整日志插桩和成本统计。",
        "下一阶段如何决策：若 MTD 无稳定增益则停止；若只在 PODNet 有效则研究偏差关系；两者都有效才研究教师质量与自适应聚合。",
    ]:
        add_plain_item(doc, text)
    add_callout(doc, "一句话结论", "本轮已经把“看起来像新方法的结果”降级为可解释的故障案例，并建立了不会手抄数字、不会混协议、不会用单种子夸结论的正式复现管线。", GREEN)

    doc.add_heading("8. 学习验收", level=1)
    p = doc.add_paragraph()
    set_spacing(p)
    r = p.add_run("按顺序完成 lessons/0001–0004.html 与 QUIZ.md。闭卷时必须能回答：")
    set_run_font(r)
    for text in [
        "为什么 KD loss 很小，旧类准确率仍可全部归零？",
        "为什么只看 final AA 不够，AIA 与 forgetting 分别补充什么？",
        "历史 checkpoint 为什么不等于 MTD 的多样化教师？",
        "均值提升小于标准差时应该如何措辞？",
        "多教师收益是否值得额外显存和训练时间？",
    ]:
        add_plain_item(doc, text)

    # Update fields on open, while cached PAGE values still render deterministically.
    settings = doc.settings._element
    update = OxmlElement("w:updateFields")
    update.set(qn("w:val"), "true")
    settings.append(update)
    doc.save(DOCX)

    md = f"""# 类增量学习项目重启：组会成果包

## 结论

- D0 复现 bus→train 替换：bus 0.00%，train 100.00%，old 0.00%。
- D2 冻结旧行后 old 仅 1.36%，说明冻结旧权重仍挡不住新类 logit 跨越决策边界。
- D3/D4 把 old 提升到 58.73%/58.91%，但 bus 仅 10%，因此是显著缓解而非彻底解决。
- KD 共同平移数值误差为约 1.19×10⁻⁷，验证旧类内部 KD 对共同 logit 平移基本不敏感。
- 正式 B50-5S 主结果仍为空；continuum 环境和完整评估插桩通过前不填任何正式数字。

## 诊断三线表

| 方法 | bus ↑ | train ↑ | old ↑ | logit gap ↓ | 替换 |
|:---|---:|---:|---:|---:|:---:|
""" + "\n".join(f"| {' | '.join(row)} |" for row in diag) + """

注：旧 VGG/JPEG 诊断协议，seed=1993，固定 6 epochs，不进入正式排名。

## 下一步

1. 修复 continuum 兼容并完成 1 epoch / 2 task 冒烟。
2. 跑 FineTune/LwF/Replay sanity。
3. PODNet/MTD-PODNet 单种子与论文核对，误差超过 2 个百分点即停止扩展。
4. 通过后完成四个主方法三种子与表 2–5、图 4–8。
"""
    MARKDOWN.write_text(md, encoding="utf-8")
    print(DOCX)
    print(MARKDOWN)


if __name__ == "__main__":
    build_document()
