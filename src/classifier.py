# -*- coding: utf-8 -*-
"""识别层：动力总成双通道识别规则引擎（规则全部来自配置，业务可维护）。"""

import logging

logger = logging.getLogger(__name__)


def _matches(text: str, keywords: list[str]) -> list[str]:
    """返回 text 中命中的关键词列表（全词包含匹配）。"""
    return [kw for kw in keywords if kw and kw in text]


def _split_codes(issue_code: str) -> list[str]:
    """拆分逗号分隔的多代码（实测 data-cti 可为 'A9,A63,H185'）。"""
    return [c.strip() for c in issue_code.split(",") if c.strip()]


class PowertrainClassifier:
    """动力总成识别器。

    双通道设计（实测依据）：
      - 通道一（代码）：data-cti 前缀 A/B/C → 发动机/变速器/离合器；
        精确白名单（H340/H343）→ 新能源三电。多代码逐个判断。
      - 通道二（关键词）：子系统专有词定类；无条件通用词单独命中即可；
        条件通用词（异响/漏油/抖动）需与子系统词共现，避免刹车/玻璃异响误报。
      - 排除黑名单仅对标题判定（正文含"贷款买的"等噪声语境）。
    """

    def __init__(self, issue_codes: dict, keywords: dict):
        self.code_prefix_map = issue_codes["code_prefix_map"]
        self.code_whitelist = issue_codes["code_whitelist"]
        self.subsystem_keywords = keywords["subsystem_keywords"]
        self.generic_keywords = keywords["generic_keywords"]
        self.context_keywords = keywords["context_keywords"]
        self.exclude_keywords = keywords["exclude_keywords"]
        self.subsystem_order = keywords["subsystem_order"]
        self.high_risk_keywords = keywords.get("high_risk_keywords", [])

    # ---------- 通道一：代码 ----------

    def code_channel(self, issue_code: str) -> dict | None:
        """代码通道：精确白名单优先，其次前缀映射。命中返回 {subsystem, code}。"""
        for code in _split_codes(issue_code):
            if code in self.code_whitelist:
                return {"subsystem": self.code_whitelist[code], "code": code}
        for code in _split_codes(issue_code):
            if code[0] in self.code_prefix_map:
                return {"subsystem": self.code_prefix_map[code[0]], "code": code}
        return None

    # ---------- 通道二：关键词 ----------

    def keyword_channel(self, text: str) -> dict | None:
        """关键词通道：命中返回 {subsystem, matched}；未命中返回 None。"""
        hit_subsystems = []
        for sub in self.subsystem_order:
            if sub == "其他":
                continue
            hits = _matches(text, self.subsystem_keywords.get(sub, []))
            if hits:
                hit_subsystems.append((sub, hits))

        hit_generic = _matches(text, self.generic_keywords)
        hit_context = _matches(text, self.context_keywords)
        subsystem_words = [w for _, hits in hit_subsystems for w in hits]
        context_ok = bool(hit_context and subsystem_words)  # 条件词需共现

        if hit_subsystems or hit_generic or context_ok:
            if hit_subsystems:
                sub, kws = hit_subsystems[0]  # 按配置顺序优先取首个
                matched = kws + (hit_generic or []) + (hit_context if context_ok else [])
            else:
                sub = "其他"
                matched = (hit_generic or []) + (hit_context if context_ok else [])
            return {"subsystem": sub, "matched": matched}
        return None

    # ---------- 综合判定 ----------

    def classify(self, record: dict) -> dict:
        """双通道识别一条投诉，返回 is_powertrain / subsystem / matched_by / matched_keywords。"""
        title = record.get("title", "")
        content = record.get("content", "")
        haystack = f"{title}\n{content}"

        # 1. 排除黑名单（仅标题，见类注释）
        for kw in self.exclude_keywords:
            if kw in title:
                return {"is_powertrain": False, "subsystem": "",
                        "matched_by": "excluded", "matched_keywords": kw}

        # 2. 代码通道
        hit = self.code_channel(record.get("issue_code", ""))
        if hit:
            return {"is_powertrain": True, "subsystem": hit["subsystem"],
                    "matched_by": "code", "matched_keywords": hit["code"]}

        # 3. 关键词通道
        hit = self.keyword_channel(haystack)
        if hit:
            return {"is_powertrain": True, "subsystem": hit["subsystem"],
                    "matched_by": "keyword",
                    "matched_keywords": ",".join(hit["matched"])}

        return {"is_powertrain": False, "subsystem": "",
                "matched_by": "", "matched_keywords": ""}

    # ---------- 辅助 ----------

    def high_risk_hits(self, record: dict) -> list[str]:
        """返回命中的高风险关键词（自燃/失速/无法启动等，供日报告警）。"""
        haystack = f"{record.get('title', '')}\n{record.get('content', '')}"
        return _matches(haystack, self.high_risk_keywords)
