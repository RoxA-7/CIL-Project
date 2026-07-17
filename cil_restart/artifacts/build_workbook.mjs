import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const ROOT = path.resolve(import.meta.dirname, "..");
const TIDY = path.join(ROOT, "results", "tidy");
const OUTPUT = path.join(ROOT, "outputs", "019f6909-f4fb-7c22-a796-01dc514831c1");
const QA = path.join(OUTPUT, "qa_workbook");
const XLSX = path.join(OUTPUT, "CIL三线表与实验结果.xlsx");
const methods = ["FineTune", "LwF", "Replay", "PODNet", "MTD-PODNet", "SS-IL", "MTD-SSIL"];
const diagOrder = ["D0", "D1", "D2", "D3", "D4"];

await fs.mkdir(QA, { recursive: true });

async function readCsv(file) {
  const csv = await fs.readFile(file, "utf8");
  const temp = await Workbook.fromCSV(csv, { sheetName: "Data" });
  return temp.worksheets.getItem("Data").getUsedRange(true).values;
}

function objects(values) {
  const headers = values[0].map(String);
  return values.slice(1).filter(r => r.some(v => v !== null && v !== "")).map(row =>
    Object.fromEntries(headers.map((h, i) => [h, row[i]]))
  );
}

function colName(index) {
  let n = index + 1, s = "";
  while (n) { n--; s = String.fromCharCode(65 + (n % 26)) + s; n = Math.floor(n / 26); }
  return s;
}

function addTitle(sheet, title, subtitle, cols) {
  const end = colName(cols - 1);
  sheet.getRange(`A1:${end}1`).merge();
  sheet.getRange("A1").values = [[title]];
  sheet.getRange("A1").format = {
    font: { name: "Microsoft YaHei", size: 16, bold: true, color: "#163A59" },
    rowHeight: 28,
  };
  sheet.getRange(`A2:${end}2`).merge();
  sheet.getRange("A2").values = [[subtitle]];
  sheet.getRange("A2").format = {
    font: { name: "Microsoft YaHei", size: 9, color: "#5F6B76" },
    wrapText: true,
    rowHeight: 31,
  };
}

function styleThreeLine(sheet, headers, rows, widths = []) {
  const cols = headers.length;
  const end = colName(cols - 1);
  addTitle(sheet, sheet.name, "数据源：results/tidy；数值禁止手工修改。顶/底线 1.5 pt，表头线 0.75 pt，无竖线。", cols);
  sheet.getRange(`A3:${end}3`).values = [headers];
  if (rows.length) sheet.getRange(`A4:${end}${3 + rows.length}`).values = rows;
  const usedEnd = Math.max(4, 3 + rows.length);
  sheet.getRange(`A3:${end}${usedEnd}`).format = {
    fill: "#FFFFFF",
    font: { name: "Microsoft YaHei", size: 10, color: "#18212B" },
    verticalAlignment: "center",
  };
  sheet.getRange(`A3:${end}3`).format = {
    font: { name: "Microsoft YaHei", size: 10, bold: true, color: "#18212B" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    rowHeight: 26,
    borders: {
      top: { style: "medium", color: "#111111" },
      bottom: { style: "thin", color: "#111111" },
    },
  };
  if (rows.length) {
    sheet.getRange(`A${3 + rows.length}:${end}${3 + rows.length}`).format.borders = {
      bottom: { style: "medium", color: "#111111" },
    };
  }
  sheet.getRange(`A4:A${usedEnd}`).format.horizontalAlignment = "left";
  if (cols > 1) sheet.getRange(`B4:${end}${usedEnd}`).format.horizontalAlignment = "right";
  widths.forEach((w, i) => { sheet.getRange(`${colName(i)}:${colName(i)}`).format.columnWidth = w; });
  sheet.freezePanes.freezeRows(3);
  sheet.showGridLines = false;
}

function styleDataSheet(sheet, values, title) {
  if (!values.length) return;
  const cols = values[0].length;
  const rows = values.length;
  const end = colName(cols - 1);
  sheet.getRange(`A1:${end}${rows}`).values = values;
  sheet.getRange(`A1:${end}1`).format = {
    fill: "#163A59", font: { name: "Calibri", size: 10, bold: true, color: "#FFFFFF" },
    wrapText: true, rowHeight: 30,
  };
  sheet.getRange(`A2:${end}${rows}`).format = { font: { name: "Calibri", size: 9 }, verticalAlignment: "center" };
  sheet.getRange(`A1:${end}${Math.min(rows, 200)}`).format.autofitColumns();
  for (let c = 0; c < cols; c++) {
    const range = sheet.getRange(`${colName(c)}:${colName(c)}`);
    if (range.format.columnWidth > 24) range.format.columnWidth = 24;
  }
  sheet.freezePanes.freezeRows(1);
  sheet.showGridLines = false;
}

const taskValues = await readCsv(path.join(TIDY, "task_metrics.csv"));
const summaryValues = await readCsv(path.join(TIDY, "run_summary.csv"));
const auditValues = await readCsv(path.join(TIDY, "legacy_code_audit.csv"));
const tasks = objects(taskValues);
const summaries = objects(summaryValues);

const workbook = Workbook.create();
const readme = workbook.worksheets.add("说明");
readme.getRange("A1:F1").merge();
readme.getRange("A1").values = [["CIFAR-100 类增量学习：三线表与可审计结果"]];
readme.getRange("A1").format = { font: { name: "Microsoft YaHei", size: 18, bold: true, color: "#163A59" }, rowHeight: 32 };
const info = [
  ["用途", "组会中文表格、论文英文备用表格、原始/清洗结果核对"],
  ["正式协议", "CIFAR-100, ResNet-32, B50-5S, 20 exemplars/class, seeds 1993/1994/1995"],
  ["诊断协议", "旧 VGG/JPEG 仅解释 11→12 类别替换，不进入正式排名"],
  ["数据规则", "所有数值来自 results/raw JSON → results/tidy CSV；不允许在最终表格手改"],
  ["当前状态", "D0–D4 已完成；正式 CLearning 结果因 continuum 兼容阻点尚未进入主表"],
  ["官方源码", "https://github.com/HaitaoWen/CLearning @ ce0789a40bda9e566a1e0432d3ac320937ca48f0"],
];
readme.getRange("A3:B8").values = info;
readme.getRange("A3:A8").format = { fill: "#E8EEF5", font: { name: "Microsoft YaHei", bold: true }, verticalAlignment: "center" };
readme.getRange("B3:B8").format = { font: { name: "Microsoft YaHei" }, wrapText: true, verticalAlignment: "center" };
readme.getRange("A:A").format.columnWidth = 18;
readme.getRange("B:B").format.columnWidth = 78;
readme.getRange("A3:B8").format.borders = { preset: "outside", style: "thin", color: "#AAB6C0" };
readme.showGridLines = false;

const latestDiag = [];
for (const method of diagOrder) {
  const candidates = tasks.filter(r => r.scenario === "legacy_head_diagnostic" && r.method === method);
  if (!candidates.length) continue;
  const latestId = candidates.map(r => String(r.run_id)).sort().at(-1);
  const runRows = candidates.filter(r => String(r.run_id) === latestId).sort((a, b) => Number(a.task_id) - Number(b.task_id));
  latestDiag.push(runRows.at(-1));
}
const diagRows = latestDiag.map(r => [r.method, Number(r.bus_accuracy), Number(r.train_accuracy), Number(r.old_accuracy), Number(r.logit_gap), null]);
const table1 = workbook.worksheets.add("表1_诊断");
styleThreeLine(table1, ["方法", "bus accuracy ↑", "train accuracy ↑", "old accuracy ↑", "logit gap ↓", "类别替换"], diagRows, [13, 17, 18, 17, 15, 14]);
if (diagRows.length) {
  table1.getRange("F4").formulas = [['=IF(AND(B4<1,C4>50),"是","否")']];
  table1.getRange(`F4:F${3 + diagRows.length}`).fillDown();
  table1.getRange(`B4:E${3 + diagRows.length}`).format.numberFormat = "0.00";
  table1.getRange(`F4:F${3 + diagRows.length}`).format.horizontalAlignment = "center";
}
table1.getRange(`A${5 + diagRows.length}:F${5 + diagRows.length}`).merge();
table1.getRange(`A${5 + diagRows.length}`).values = [["注：D0=旧实现；D1=整头重置；D2=冻结旧行；D3=重放；D4=重放+old/new 分组校准。"]];
table1.getRange(`A${5 + diagRows.length}`).format = { font: { name: "Microsoft YaHei", size: 9, italic: true, color: "#5F6B76" }, wrapText: true };

const table1en = workbook.worksheets.add("Table1_Diagnostic");
styleThreeLine(table1en, ["Method", "Bus acc. ↑", "Train acc. ↑", "Old acc. ↑", "Logit gap ↓", "Replacement"], diagRows.map(r => [...r.slice(0, 5), null]), [13, 15, 15, 15, 15, 15]);
if (diagRows.length) {
  table1en.getRange("F4").formulas = [['=IF(AND(B4<1,C4>50),"Yes","No")']];
  table1en.getRange(`F4:F${3 + diagRows.length}`).fillDown();
  table1en.getRange(`B4:E${3 + diagRows.length}`).format.numberFormat = "0.00";
}

const completeFormal = summaries.filter(r => r.scenario === "cifar100_b50_5s" && r.status === "complete");
function mainRowsEnglish(zh = false) {
  return methods.map(method => {
    const g = completeFormal.filter(r => r.method === method);
    const required = methods.indexOf(method) < 3 ? 1 : 3;
    if (g.length < required) return [method, zh ? `待运行（${g.length}/${required} seeds）` : `Pending (${g.length}/${required} seeds)`, "—", "—", "—", "—"];
    const metric = key => {
      const xs = g.map(r => Number(r[key]));
      const mean = xs.reduce((a, b) => a + b, 0) / xs.length;
      if (xs.length === 1) return mean.toFixed(2);
      const sd = Math.sqrt(xs.reduce((a, x) => a + (x - mean) ** 2, 0) / (xs.length - 1));
      return `${mean.toFixed(2)} ± ${sd.toFixed(2)}`;
    };
    return [method, metric("aia"), metric("final_aa"), metric("forgetting"), metric("old_accuracy"), metric("new_accuracy")];
  });
}
const table2 = workbook.worksheets.add("表2_主结果");
styleThreeLine(table2, ["方法", "AIA ↑", "final AA ↑", "forgetting ↓", "old acc. ↑", "new acc. ↑"], mainRowsEnglish(true), [18, 22, 16, 17, 16, 16]);
const table2en = workbook.worksheets.add("Table2_Main");
styleThreeLine(table2en, ["Method", "AIA ↑", "Final AA ↑", "Forgetting ↓", "Old acc. ↑", "New acc. ↑"], mainRowsEnglish(false), [18, 22, 16, 17, 16, 16]);

const stageRows = methods.map(m => [m, ...Array(8).fill("—")]);
const table3 = workbook.worksheets.add("表3_逐阶段");
styleThreeLine(table3, ["方法", "Task 0", "Task 1", "Task 2", "Task 3", "Task 4", "Task 5", "AIA", "final AA"], stageRows, [17, 12, 12, 12, 12, 12, 12, 12, 14]);

const table4 = workbook.worksheets.add("表4_二因素");
styleThreeLine(table4, ["分类方式", "单教师 AIA", "多教师 AIA", "增益"], [["普通分类", "—", "—", "—"], ["偏差校正", "—", "—", "—"], ["交互增益", "—", "—", "—"]], [18, 20, 20, 16]);

const table5 = workbook.worksheets.add("表5_效率");
styleThreeLine(table5, ["方法", "参数量 (M)", "额外教师参数 (M)", "峰值显存 (GB)", "总训练时间 (h)", "AIA/训练小时"], methods.map(m => [m, "—", "—", "—", "—", "—"]), [18, 16, 20, 18, 19, 18]);

const auditRows = auditValues.slice(1).map(r => [r[0], r[1], r[2], r[3], String(r[4]).toLowerCase() === "true" ? "已验证" : "待验证"]);
const table6 = workbook.worksheets.add("表6_审计");
styleThreeLine(table6, ["检查项", "旧实现", "标准实现", "可能影响", "状态"], auditRows, [22, 38, 38, 30, 14]);
table6.getRange(`A4:E${3 + auditRows.length}`).format.wrapText = true;
table6.getRange(`A4:E${3 + auditRows.length}`).format.rowHeight = 42;

const rawTask = workbook.worksheets.add("Task_Metrics");
styleDataSheet(rawTask, taskValues, "Task metrics");
const rawSummary = workbook.worksheets.add("Run_Summary");
styleDataSheet(rawSummary, summaryValues, "Run summary");

const inspect = await workbook.inspect({ kind: "sheet", include: "id,name", maxChars: 6000 });
console.log(inspect.ndjson);
const check = await workbook.inspect({ kind: "table", range: "表1_诊断!A1:F10", include: "values,formulas", tableMaxRows: 12, tableMaxCols: 8 });
console.log(check.ndjson);
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 100 }, summary: "final formula error scan" });
console.log(errors.ndjson);

for (const sheet of workbook.worksheets.items) {
  const preview = await workbook.render({ sheetName: sheet.name, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(path.join(QA, `${sheet.name}.png`), new Uint8Array(await preview.arrayBuffer()));
}

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(XLSX);
console.log(XLSX);
