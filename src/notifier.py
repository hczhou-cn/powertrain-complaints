# -*- coding: utf-8 -*-
"""通知层：飞书群机器人日报推送（interactive 卡片）。"""

import json
import logging
import os
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

FEISHU_API = "https://open.feishu.cn/open-apis/bot/v2/hook/"


class FeishuNotifier:
    """飞书自定义群机器人推送。

    webhook 优先级：环境变量 FEISHU_WEBHOOK > config/notify.json。
    使用 --dry-run 可只打印卡片 payload 不实际发送。
    """

    def __init__(self, notify_cfg: dict):
        self.webhook = os.environ.get("FEISHU_WEBHOOK", "").strip() or \
            str(notify_cfg.get("webhook", "")).strip()
        self.enabled = bool(notify_cfg.get("enabled")) and bool(self.webhook)
        self.report_title = notify_cfg.get("report_title", "🚗 动力总成抱怨日报")

    def available(self, dry_run: bool = False) -> bool:
        """是否可推送：dry-run 模式无需 webhook（仅打印 payload）。"""
        if dry_run:
            return True
        return self.enabled and bool(self.webhook)

    # ---------- 卡片构造 ----------

    def build_daily_card(self, stats: dict, since: str, high_risk: list[dict]) -> dict:
        """构造日报卡片。"""
        date_range = f"{since} ~ {datetime.now():%Y-%m-%d}"
        pt = stats["pt_total"]
        total = stats["total"]
        ratio = f"{pt / total * 100:.1f}%" if total else "0%"

        lines = [f"**统计窗口**: {date_range}",
                 f"**动力总成抱怨**: {pt} 条（占全部投诉 {ratio}，共 {total} 条）",
                 "",
                 "**子系统分布**："]

        subs = stats["subsystem"] or []
        if subs:
            for s, c in subs:
                lines.append(f"· {s or '其他'}: {c}")
        else:
            lines.append("· 无")

        brands = stats["brands"] or []
        if brands:
            lines.append("")
            lines.append("**TOP 5 品牌**：" + " / ".join(
                f"{b or '未知'}({c})" for b, c in brands[:5]))

        risk_lines = []
        for r in high_risk[:5]:
            risk_lines.append(f"· {r['complaint_date']} {r['brand']} {r['series']}"
                              f"：{r['title'][:40]}")
        if risk_lines:
            lines.append("")
            lines.append("⚠ **高风险问题**（自燃/失速/无法启动等）：")
            lines.extend(risk_lines)

        elements = [
            {"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}},
            {"tag": "hr"},
            {"tag": "note", "element": [{"tag": "plain_text",
                                         "content": "数据来源：车质网公开投诉 | 详细清单见 Excel 报表"}]},
        ]

        return {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text",
                              "content": f"{self.report_title}（{since}）"},
                    "template": "red" if high_risk else "blue",
                },
                "elements": elements,
            },
        }

    # ---------- 发送 ----------

    def send_card(self, card: dict, dry_run: bool = False) -> bool:
        """发送卡片；dry_run 仅打印。返回是否发送成功。"""
        payload = json.dumps(card, ensure_ascii=False, indent=2)
        if dry_run:
            print("[dry-run] 飞书卡片 payload:\n" + payload)
            return True
        if not self.webhook:
            logger.warning("未配置飞书 webhook，跳过推送")
            return False
        try:
            resp = requests.post(self.webhook, data=payload.encode("utf-8"),
                                 headers={"Content-Type": "application/json"},
                                 timeout=10)
            body = resp.json()
            if resp.status_code == 200 and body.get("code") == 0:
                logger.info("飞书日报推送成功")
                return True
            logger.error("飞书推送失败: %s %s", resp.status_code, body)
            return False
        except (requests.RequestException, ValueError) as exc:
            logger.error("飞书推送异常: %s", exc)
            return False
