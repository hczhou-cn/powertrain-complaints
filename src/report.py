# -*- coding: utf-8 -*-
"""输出层：CSV 与 Excel 多 Sheet 报表（M3）。

Excel 报表结构：
  - 概览：时间范围、核心指标、子系统分布、TOP 品牌/车系、高风险问题
  - 每日趋势：日期/投诉量柱状图
  - 品牌排行 / 车系排行 / 子系统分布 / 投诉明细
"""

import csv
import logging
import os
from datetime import datetime

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

logger = logging.getLogger(__name__)

# 样式常量
HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
TITLE_FONT = Font(bold=True, size=16, color="1F4E79")
SECTION_FONT = Font(bold=True, size=12, color="1F4E79")
THIN_BORDER = Border(*[Side(style="thin", color="D9D9D9")] * 4)
RISK_FILL = PatternFill("solid", fgColor="FCE4E4")
ALT_FILL = PatternFill("solid", fgColor="F2F7FB")


def _style_header_cell(cell) -> None:
    cell.fill = HEADER_FILL
    cell.font = HEADER_FONT
    cell.alignment = Alignment(horizontal="center", vertical="center")
    cell.border = THIN_BORDER


def _style_data_cell(cell, wrap: bool = False) -> None:
    cell.border = THIN_BORDER
    cell.alignment = Alignment(vertical="center", wrap_text=wrap)


def _auto_width(ws, min_w: int = 10, max_w: int = 50) -> None:
    """按内容估算列宽（中文按 2 字符宽计）。"""
    for col in ws.columns:
        letter = get_column_letter(col[0].column)
        width = min_w
        for cell in col:
            if cell.value is None:
                continue
            length = sum(2 if ord(ch) > 127 else 1 for ch in str(cell.value))
            width = max(width, min(length + 2, max_w))
        ws.column_dimensions[letter].width = width


def write_table(ws, start_row: int, start_col: int, headers: list[str],
                rows: list[list], wrap_col: int | None = None,
                risk_rows: set | None = None, fill_risk: bool = False) -> int:
    """在指定起始行列写入带表头的表格，返回表尾行号（最后一行数据行号）。

    risk_rows: 明细主键集合（如投诉编号），命中的行标红；
    fill_risk: 若为 True，则整块区域强制标红（用于高风险区块）。
    """
    for j, h in enumerate(headers):
        _style_header_cell(ws.cell(row=start_row, column=start_col + j, value=h))

    for i, row in enumerate(rows):
        r = start_row + 1 + i
        for j, v in enumerate(row):
            cell = ws.cell(row=r, column=start_col + j, value=v)
            _style_data_cell(cell, wrap=(wrap_col is not None and j == wrap_col))
            if fill_risk or (risk_rows and row[0] in risk_rows):
                cell.fill = RISK_FILL
            elif (r + j) % 2 == 0:
                cell.fill = ALT_FILL
    return start_row + len(rows)


def _percent_cells(ws, start_row: int, n: int, col: int) -> None:
    for r in range(start_row + 1, start_row + 1 + n):
        ws.cell(row=r, column=col).number_format = "0.0%"


def export_csv(conn, since: str, out_path: str) -> int:
    """导出近 N 天动力总成投诉 CSV（utf-8-sig，Excel 直接打开不乱码）。"""
    from .storage import fetch_detail
    records = fetch_detail(conn, since, is_pt=1)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["投诉编号", "品牌", "车系", "车型", "问题简述", "典型问题代码",
                         "投诉日期", "状态", "子系统", "识别通道", "命中关键词", "详情链接"])
        for r in records:
            writer.writerow([r["complaint_no"], r["brand"], r["series"], r["model"],
                             r["title"], r["issue_code"], r["complaint_date"],
                             r["status"], r["pt_subsystem"], r["matched_by"],
                             r["matched_keywords"], r["detail_url"]])
    logger.info("CSV 导出 %d 条: %s", len(records), out_path)
    return len(records)


def export_excel(conn, since: str, out_path: str, classifier=None,
                 high_risk: list[dict] | None = None,
                 focus_summaries: dict | None = None) -> int:
    """生成多 Sheet Excel 报表，返回动力总成明细条数。"""
    from .storage import fetch_detail, summary_stats

    stats = summary_stats(conn, since)
    detail = fetch_detail(conn, since, is_pt=1)
    today = datetime.now().strftime("%Y-%m-%d")
    title = f"汽车动力总成抱怨分析报表（{since} ~ {today}）"
    risk_nos = {r["complaint_no"] for r in (high_risk or [])}

    wb = Workbook()

    # ---------- Sheet 1: 概览 ----------
    ws = wb.active
    ws.title = "概览"
    ws.merge_cells("A1:F1")
    ws["A1"] = title
    ws["A1"].font = TITLE_FONT
    ws.row_dimensions[1].height = 28

    metrics = [
        ("扫描窗口投诉总数", stats["total"]),
        ("动力总成相关投诉", stats["pt_total"]),
        ("动力总成占比",
         f"{stats['pt_total'] / stats['total'] * 100:.1f}%" if stats["total"] else "0%"),
        ("涉及品牌数", len(stats["brands"])),
        ("涉及车系数", len(stats["series"])),
    ]
    for i, (label, value) in enumerate(metrics):
        ws.cell(row=3 + i, column=1, value=label).font = SECTION_FONT
        ws.cell(row=3 + i, column=2, value=value)

    # 子系统分布（左上）
    ws.cell(row=9, column=1, value="子系统分布").font = SECTION_FONT
    sub_rows = [[s or "其他", c] for s, c in stats["subsystem"]]
    sub_end = write_table(ws, 10, 1, ["子系统", "投诉数"], sub_rows)
    ws.cell(row=10, column=3, value="占比")
    _style_header_cell(ws.cell(row=10, column=3))
    for i, (_, c) in enumerate(sub_rows):
        cell = ws.cell(row=11 + i, column=3,
                       value=c / stats["pt_total"] if stats["pt_total"] else 0)
        cell.number_format = "0.0%"
        _style_data_cell(cell)

    # TOP 品牌（右上 D/E/F 列）
    ws.cell(row=9, column=4, value="TOP 10 品牌").font = SECTION_FONT
    brand_rows = [[b or "未知", c] for b, c in stats["brands"][:10]]
    write_table(ws, 10, 4, ["品牌", "投诉数"], brand_rows)

    # 高风险问题
    hr = high_risk or []
    if hr:
        risk_start = max(sub_end, 11) + 2
        ws.cell(row=risk_start, column=1,
                value="⚠ 高风险问题（自燃/失速/无法启动等）").font = SECTION_FONT
        hr_rows = [[r["complaint_date"], r["brand"], r["series"], r["title"],
                    r.get("risk_keywords", "")] for r in hr[:10]]
        write_table(ws, risk_start + 1, 1, ["日期", "品牌", "车系", "问题简述", "命中词"],
                    hr_rows, wrap_col=3, fill_risk=True)
    _auto_width(ws)

    # ---------- 专项监测 Sheet ----------
    for group_id, focus in (focus_summaries or {}).items():
        sheet_name = "吉利集团专项" if group_id == "geely_group" else f"专项-{group_id}"[:31]
        wsf = wb.create_sheet(sheet_name)
        wsf.merge_cells("A1:F1")
        wsf["A1"] = f"{focus['name']}动力总成专项监测（{since} ~ {today}）"
        wsf["A1"].font = TITLE_FONT
        wsf.row_dimensions[1].height = 28
        focus_metrics = [
            (f"{focus['name']}投诉数", focus["total"]),
            ("占全部动力总成投诉", f"{focus['ratio'] * 100:.1f}%"),
            ("涉及品牌数", len(focus["brands"])),
            ("高风险问题数", len(focus["high_risk"])),
        ]
        for i, (label, value) in enumerate(focus_metrics):
            wsf.cell(row=3 + i, column=1, value=label).font = SECTION_FONT
            wsf.cell(row=3 + i, column=2, value=value)

        wsf.cell(row=9, column=1, value="重点品牌").font = SECTION_FONT
        write_table(wsf, 10, 1, ["品牌", "投诉数"], focus["brands"])
        wsf.cell(row=9, column=4, value="重点车系").font = SECTION_FONT
        write_table(wsf, 10, 4, ["车系", "投诉数"], focus["series"])

        sub_start = 10 + max(len(focus["brands"]), len(focus["series"])) + 2
        wsf.cell(row=sub_start, column=1, value="子系统分布").font = SECTION_FONT
        write_table(wsf, sub_start + 1, 1, ["子系统", "投诉数"], focus["subsystems"])

        if focus["high_risk"]:
            risk_start = sub_start + len(focus["subsystems"]) + 4
            wsf.cell(row=risk_start, column=1,
                     value="⚠ 吉利集团高风险问题").font = SECTION_FONT
            risk_rows = [[r["complaint_date"], r["brand"], r["series"], r["title"],
                          r["risk_keywords"]] for r in focus["high_risk"][:20]]
            write_table(wsf, risk_start + 1, 1,
                        ["日期", "品牌", "车系", "问题简述", "命中词"],
                        risk_rows, wrap_col=3, fill_risk=True)
        _auto_width(wsf, max_w=50)

    # ---------- Sheet: 每日趋势 ----------
    ws2 = wb.create_sheet("每日趋势")
    ws2.merge_cells("A1:C1")
    ws2["A1"] = "每日投诉量趋势"
    ws2["A1"].font = TITLE_FONT
    trend_rows = [[d, pt, total] for d, pt, total in stats["trend"]]
    trend_end = write_table(ws2, 3, 1, ["日期", "动力总成投诉", "全部投诉"], trend_rows)
    if len(trend_rows) > 1:
        chart = BarChart()
        chart.type = "col"
        chart.style = 10
        chart.title = "每日投诉量"
        chart.y_axis.title = "条数"
        data = Reference(ws2, min_col=2, min_row=3, max_col=3, max_row=trend_end)
        cats = Reference(ws2, min_col=1, min_row=4, max_row=trend_end)
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(cats)
        chart.width = 24
        chart.height = 10
        ws2.add_chart(chart, "E4")
    _auto_width(ws2)

    # ---------- Sheet 3: 品牌排行 ----------
    ws3 = wb.create_sheet("品牌排行")
    ws3.merge_cells("A1:D1")
    ws3["A1"] = "品牌排行（动力总成投诉）"
    ws3["A1"].font = TITLE_FONT
    brand_rows = [[b or "未知", c] for b, c in stats["brands"]]
    write_table(ws3, 3, 1, ["品牌", "投诉数", "占比"],
                [[b, c, c / stats["pt_total"] if stats["pt_total"] else 0]
                 for b, c in brand_rows])
    _percent_cells(ws3, 3, len(brand_rows), 3)
    _auto_width(ws3)

    # ---------- Sheet 4: 车系排行 ----------
    ws4 = wb.create_sheet("车系排行")
    ws4.merge_cells("A1:C1")
    ws4["A1"] = "车系排行（动力总成投诉）"
    ws4["A1"].font = TITLE_FONT
    series_rows = [[s, c] for s, c in stats["series"][:50]]
    write_table(ws4, 3, 1, ["车系", "投诉数"], series_rows)
    _auto_width(ws4)

    # ---------- Sheet 5: 子系统分布 ----------
    ws5 = wb.create_sheet("子系统分布")
    ws5.merge_cells("A1:C1")
    ws5["A1"] = "子系统分布"
    ws5["A1"].font = TITLE_FONT
    sub_rows = [[s or "其他", c] for s, c in stats["subsystem"]]
    write_table(ws5, 3, 1, ["子系统", "投诉数", "占比"],
                [[s, c, c / stats["pt_total"] if stats["pt_total"] else 0]
                 for s, c in sub_rows])
    _percent_cells(ws5, 3, len(sub_rows), 3)
    _auto_width(ws5)

    # ---------- Sheet 6: 投诉明细 ----------
    ws6 = wb.create_sheet("投诉明细")
    ws6.merge_cells("A1:L1")
    ws6["A1"] = "动力总成投诉明细"
    ws6["A1"].font = TITLE_FONT
    detail_headers = ["投诉编号", "品牌", "车系", "车型", "问题简述", "典型问题代码",
                      "投诉日期", "状态", "子系统", "识别通道", "命中关键词", "详情链接"]
    detail_rows = [[r["complaint_no"], r["brand"], r["series"], r["model"],
                    r["title"], r["issue_code"], r["complaint_date"], r["status"],
                    r["pt_subsystem"], r["matched_by"], r["matched_keywords"],
                    r["detail_url"]] for r in detail]
    write_table(ws6, 3, 1, detail_headers, detail_rows,
                wrap_col=4, risk_rows=risk_nos)
    ws6.freeze_panes = "A4"
    _auto_width(ws6, max_w=45)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    wb.save(out_path)
    logger.info("Excel 报表生成: %s（动力总成明细 %d 条）", out_path, len(detail))
    return len(detail)
