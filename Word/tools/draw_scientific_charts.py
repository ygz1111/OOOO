"""Render thesis figures from existing table values; do not evaluate models.

Run with the Codex bundled Python. Inputs are the original extracted DOCX
tables in source_tables.json, not inferred or newly computed metrics. PDFs
are vector originals; pypdfium2 renders their one-page PNGs at scale=3.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pypdfium2 as pdfium
from reportlab.graphics import renderPDF
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / 'Word/materials/thesis_update'
TABLES = json.loads((OUTPUT_DIR / "source_tables.json").read_text(encoding="utf-8-sig"))
WIDTH, HEIGHT = 480, 260
FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
FONT_SIZE = 11
INK = colors.HexColor("#182835")
MUTED = colors.HexColor("#445662")
GRID = colors.HexColor("#D8DFE4")
PALETTE = [
    colors.HexColor("#234F72"),
    colors.HexColor("#B5632D"),
    colors.HexColor("#5D8475"),
    colors.HexColor("#786888"),
]


def find_table(header: list[str]) -> list[list[str]]:
    matched = [table for table in TABLES if table and table[0] == header]
    if len(matched) != 1:
        raise ValueError(f"Expected one original table for {header!r}, got {len(matched)}")
    return matched[0]


def numeric(value: str, expect_percent: bool = False) -> float:
    text = value.strip()
    if text.upper() in {"NA", "N/A", "NAN", "", "-", "—"}:
        raise ValueError(f"Missing original metric: {value!r}")
    if expect_percent and not text.endswith("%"):
        raise ValueError(f"Expected original percentage cell, got {value!r}")
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?%?", text):
        raise ValueError(f"Unexpected original metric format: {value!r}")
    result = float(text.removesuffix("%"))
    if not math.isfinite(result):
        raise ValueError(f"Non-finite original metric: {value!r}")
    return result


def add_legend(drawing: Drawing, entries: list[tuple[str, colors.Color]]) -> None:
    # Explicit placement keeps all text at >=11pt without chart legend auto-fit.
    from reportlab.pdfbase.pdfmetrics import stringWidth

    widths = [14 + stringWidth(label, FONT, FONT_SIZE) + 18 for label, _ in entries]
    total_width = sum(widths) - 18
    x = (WIDTH - total_width) / 2
    for width, (label, color) in zip(widths, entries):
        drawing.add(Rect(x, 242, 9, 9, fillColor=color, strokeColor=color))
        drawing.add(String(x + 14, 242, label, fontName=FONT, fontSize=FONT_SIZE, fillColor=INK))
        x += width


def add_chart(
    drawing: Drawing,
    *,
    x: float,
    width: float,
    title: str,
    names: list[str],
    data: list[list[float]],
    maximum: float,
    step: float,
    series_colors: list[colors.Color],
) -> None:
    drawing.add(String(x, 219, title, fontName=FONT_BOLD, fontSize=11.5, fillColor=INK))
    chart = VerticalBarChart()
    chart.x = x
    chart.y = 76
    chart.width = width
    chart.height = 130
    chart.data = data
    chart.barWidth = 12
    chart.barSpacing = 1.4
    chart.groupSpacing = 10
    chart.fillColor = None
    chart.strokeColor = None
    chart.categoryAxis.categoryNames = names
    chart.categoryAxis.strokeColor = MUTED
    chart.categoryAxis.strokeWidth = 0.7
    chart.categoryAxis.tickUp = 0
    chart.categoryAxis.tickDown = 3
    chart.categoryAxis.labels.fontName = FONT
    chart.categoryAxis.labels.fontSize = FONT_SIZE
    chart.categoryAxis.labels.fillColor = INK
    chart.categoryAxis.labels.boxAnchor = "n"
    chart.categoryAxis.labels.dy = -7
    chart.categoryAxis.labels.leading = 12
    chart.categoryAxis.labels.textAnchor = "middle"
    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueMax = maximum
    chart.valueAxis.valueStep = step
    chart.valueAxis.strokeColor = MUTED
    chart.valueAxis.strokeWidth = 0.7
    chart.valueAxis.tickLeft = 3
    chart.valueAxis.visibleGrid = True
    chart.valueAxis.gridStrokeColor = GRID
    chart.valueAxis.gridStrokeWidth = 0.5
    chart.valueAxis.drawGridLast = False
    chart.valueAxis.labels.fontName = FONT
    chart.valueAxis.labels.fontSize = FONT_SIZE
    chart.valueAxis.labels.fillColor = MUTED
    chart.valueAxis.labels.dx = -5
    chart.valueAxis.labelTextFormat = "%d"
    chart.barLabelFormat = None
    for i, color in enumerate(series_colors):
        chart.bars[i].fillColor = color
        chart.bars[i].strokeColor = color
        chart.bars[i].strokeWidth = 0.3
    drawing.add(chart)


def make_drawing(
    *,
    series_labels: list[str],
    mw_names: list[str],
    mw_data: list[list[float]],
    percent_names: list[str],
    percent_data: list[list[float]],
    mw_maximum: float,
    mw_step: float,
    percent_maximum: float,
    percent_step: float,
    footnotes: list[str],
) -> Drawing:
    drawing = Drawing(WIDTH, HEIGHT)
    drawing.add(Rect(0, 0, WIDTH, HEIGHT, fillColor=colors.white, strokeColor=None))
    series_colors = PALETTE[: len(series_labels)]
    add_legend(drawing, list(zip(series_labels, series_colors)))
    dense_categories = len(mw_names) > 2
    left_width = 230 if dense_categories else 240
    right_x = 319 if dense_categories else 333
    right_width = 147 if dense_categories else 133
    divider_x = 290 if dense_categories else 306
    add_chart(
        drawing,
        x=42,
        width=left_width,
        title="Absolute error (MW)",
        names=mw_names,
        data=mw_data,
        maximum=mw_maximum,
        step=mw_step,
        series_colors=series_colors,
    )
    add_chart(
        drawing,
        x=right_x,
        width=right_width,
        title="Relative error (%)",
        names=percent_names,
        data=percent_data,
        maximum=percent_maximum,
        step=percent_step,
        series_colors=series_colors,
    )
    drawing.add(Line(divider_x, 51, divider_x, 223, strokeColor=GRID, strokeWidth=0.6))
    for i, footnote in enumerate(footnotes):
        y = 26 - 13 * i if len(footnotes) == 2 else 14
        drawing.add(String(42, y, footnote, fontName=FONT, fontSize=FONT_SIZE, fillColor=MUTED))
    return drawing


def save(drawing: Drawing, name: str, original_table: str) -> None:
    pdf_path = OUTPUT_DIR / f"{name}.pdf"
    png_path = OUTPUT_DIR / f"{name}.png"
    renderPDF.drawToFile(drawing, str(pdf_path), title=f"Original {original_table}: separate-unit error comparison")
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        page = pdf[0]
        try:
            bitmap = page.render(scale=3)
            try:
                bitmap.to_pil().save(png_path)
            finally:
                bitmap.close()
        finally:
            page.close()
    finally:
        pdf.close()
    print(f"{name}: {original_table} -> {png_path}; 480x260pt, 1440x780px")


def load_baseline() -> None:
    table = find_table(["方法", "MAE (MW)", "RMSE (MW)", "MAPE"])
    rows = table[1:]
    if [row[0] for row in rows] != ["tf_load_split_v1", "DA Demand", "naive-24", "naive-168"]:
        raise ValueError("Unexpected original Table 6-4 series order")
    drawing = make_drawing(
        series_labels=[row[0] for row in rows],
        mw_names=["MAE", "RMSE"],
        mw_data=[[numeric(row[1]), numeric(row[2])] for row in rows],
        percent_names=["MAPE"],
        percent_data=[[numeric(row[3], expect_percent=True)] for row in rows],
        mw_maximum=3500,
        mw_step=500,
        percent_maximum=18,
        percent_step=3,
        footnotes=["Source: Table 6-4; lower is better; each panel has its own unit."],
    )
    save(drawing, "load_baseline_current", "Table 6-4")


MW_ROWS = ["全时段 MAE (MW)", "全时段 RMSE (MW)", "白天 MAE (MW)", "白天 RMSE (MW)", "平均峰值误差 (MW)"]
PERCENT_ROWS_VALIDATION = ["白天 WAPE", "真实值>500 MW 条件MAPE", "平均日能量误差"]
PERCENT_ROWS_BASELINE = ["白天 WAPE", "条件MAPE", "平均日能量误差"]
MW_NAMES = ["All\nMAE", "All\nRMSE", "Day\nMAE", "Day\nRMSE", "Peak\nMAE"]
PERCENT_NAMES = ["Day\nWAPE", "Cond.\nMAPE", "Window\nenergy"]


def pv_comparison(*, validation: bool) -> None:
    if validation:
        table = find_table(["指标", "验证集", "测试集"])
        labels = ["Validation", "Test"]
        percent_rows = PERCENT_ROWS_VALIDATION
        mw_maximum, mw_step = 700, 100
        percent_maximum, percent_step = 24, 4
        name, table_name = "pv_validation_test_current", "Table 6-6"
    else:
        table = find_table(["指标", "PV v2", "naive-24", "相对降低"])
        labels = ["PV v2", "naive-24"]
        percent_rows = PERCENT_ROWS_BASELINE
        mw_maximum, mw_step = 1600, 400
        percent_maximum, percent_step = 60, 10
        name, table_name = "pv_baseline_current", "Table 6-7"
    indexed = {row[0]: row for row in table[1:]}
    drawing = make_drawing(
        series_labels=labels,
        mw_names=MW_NAMES,
        mw_data=[[numeric(indexed[key][col]) for key in MW_ROWS] for col in (1, 2)],
        percent_names=PERCENT_NAMES,
        percent_data=[[numeric(indexed[key][col], expect_percent=True) for key in percent_rows] for col in (1, 2)],
        mw_maximum=mw_maximum,
        mw_step=mw_step,
        percent_maximum=percent_maximum,
        percent_step=percent_step,
        footnotes=[
            "Day: daylight; conditional MAPE: reference PV > 500 MW.",
            f"{table_name}; energy and peak use overlapping 24-hour windows.",
        ],
    )
    save(drawing, name, table_name)


if __name__ == "__main__":
    load_baseline()
    pv_comparison(validation=False)
    pv_comparison(validation=True)
