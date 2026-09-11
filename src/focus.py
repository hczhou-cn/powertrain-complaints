# -*- coding: utf-8 -*-
"""重点集团专项识别与聚合。"""

import re
from collections import Counter, defaultdict


def normalize_text(value: str) -> str:
    """统一大小写并去除空白、连接符，提升中英文品牌匹配稳定性。"""
    text = str(value or "").strip().lower()
    return re.sub(r"[\s\-_·&]+", "", text)


def record_search_text(record: dict) -> str:
    """专项匹配只使用品牌/车系/车型，避免投诉正文中的无关品牌造成误识别。"""
    return normalize_text(" ".join([
        record.get("brand", ""),
        record.get("series", ""),
        record.get("model", ""),
    ]))


def match_focus_group(record: dict, focus_groups: dict) -> tuple[str, str] | None:
    """返回 (group_id, group_name)，未命中返回 None。"""
    text = record_search_text(record)
    for group_id, group in (focus_groups or {}).items():
        aliases = group.get("aliases", [])
        for alias in aliases:
            if normalize_text(alias) and normalize_text(alias) in text:
                return group_id, group.get("name", group_id)
    return None


def annotate_focus(records: list[dict], focus_groups: dict) -> list[dict]:
    """给记录增加 focus_group/focus_group_name 字段，不修改原始业务字段。"""
    result = []
    for record in records:
        item = dict(record)
        matched = match_focus_group(item, focus_groups)
        if matched:
            item["focus_group"], item["focus_group_name"] = matched
        result.append(item)
    return result


def build_focus_summary(records: list[dict], focus_groups: dict,
                        classifier=None) -> dict:
    """按集团聚合动力总成投诉，输出报表、看板、通知共用结构。"""
    annotated = annotate_focus(records, focus_groups)
    summaries = {}
    for group_id, group in (focus_groups or {}).items():
        selected = [r for r in annotated if r.get("focus_group") == group_id]
        if not selected:
            summaries[group_id] = {
                "id": group_id, "name": group.get("name", group_id),
                "description": group.get("description", ""), "total": 0,
                "ratio": 0, "brands": [], "series": [], "subsystems": [],
                "trend": [], "high_risk": [], "records": [],
            }
            continue

        total = len(records)
        brand_counts = Counter(r.get("brand") or "未知" for r in selected)
        series_counts = Counter(
            f"{r.get('brand') or '未知'} {r.get('series') or '未知车系'}"
            for r in selected
        )
        subsystem_counts = Counter(r.get("pt_subsystem") or "其他" for r in selected)
        trend_map = defaultdict(int)
        for r in selected:
            trend_map[r.get("complaint_date", "未知日期")] += 1

        high_risk = []
        focus_records = []
        for record in selected:
            item = dict(record)
            hits = classifier.high_risk_hits(item) if classifier else []
            item["high_risk"] = bool(hits)
            item["risk_keywords"] = ",".join(hits)
            focus_records.append(item)
            if hits:
                high_risk.append({
                    "complaint_no": item.get("complaint_no", ""),
                    "complaint_date": item.get("complaint_date", ""),
                    "brand": item.get("brand", ""),
                    "series": item.get("series", ""),
                    "title": item.get("title", ""),
                    "risk_keywords": item["risk_keywords"],
                })

        summaries[group_id] = {
            "id": group_id,
            "name": group.get("name", group_id),
            "description": group.get("description", ""),
            "total": len(selected),
            "ratio": len(selected) / total if total else 0,
            "brands": [[k, v] for k, v in brand_counts.most_common(10)],
            "series": [[k, v] for k, v in series_counts.most_common(10)],
            "subsystems": [[k, v] for k, v in subsystem_counts.most_common()],
            "trend": [[k, trend_map[k]] for k in sorted(trend_map)],
            "high_risk": high_risk[:20],
            "records": focus_records[:1000],
        }
    return summaries
