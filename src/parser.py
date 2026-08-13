# -*- coding: utf-8 -*-
"""解析层：列表页与详情页 HTML → 结构化记录。"""

import logging

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def _text(tag) -> str:
    """安全取标签文本，空值兜底。"""
    return tag.get_text(strip=True) if tag is not None else ""


def parse_list_page(html: str) -> list[dict]:
    """解析投诉列表页表格（table.ar_c），返回投诉记录列表。

    实测字段顺序：投诉编号 / 品牌 / 车系 / 车型 / 问题简述(含详情链接)
    / 典型问题(data-cti) / 时间 / 状态
    """
    records = []
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table.ar_c")
    if table is None:
        return records

    for tr in table.select("tr"):
        cells = tr.find_all("td")
        if len(cells) < 7:
            continue  # 表头行或无数据行

        complaint_no = _text(cells[0])
        if not complaint_no.isdigit():
            continue

        title_tag = cells[4].select_one("a")
        title = _text(title_tag)
        detail_url = ""
        if title_tag and title_tag.get("href"):
            detail_url = title_tag["href"]
            if detail_url.startswith("//"):
                detail_url = "https:" + detail_url

        code_cell = cells[5]
        issue_code = code_cell.get("data-cti", "") if code_cell else ""

        records.append({
            "complaint_no": complaint_no,
            "brand": _text(cells[1]),
            "series": _text(cells[2]),
            "model": _text(cells[3]),
            "title": title,
            "detail_url": detail_url,
            "issue_code": issue_code,
            "complaint_date": _text(cells[6]),
            "status": _text(cells[7]) if len(cells) > 7 else "",
        })
    return records


def parse_detail_page(html: str) -> tuple[str, str]:
    """解析详情页，返回 (完整投诉内容, 投诉回复)。

    实测结构：投诉内容在 div.tsnr，投诉回复在 div.tshf。
    字段缺失时返回空字符串，不中断主流程。
    """
    soup = BeautifulSoup(html, "lxml")
    content = ""
    tsnr = soup.select_one("div.tsnr")
    if tsnr is not None:
        content = tsnr.get_text("\n", strip=True)

    reply = ""
    tshf = soup.select_one("div.tshf")
    if tshf is not None:
        reply = tshf.get_text("\n", strip=True)

    return content, reply
