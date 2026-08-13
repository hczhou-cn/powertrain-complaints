# -*- coding: utf-8 -*-
"""通知层：多渠道日报推送（飞书 interactive 卡片 + 企业微信 markdown）。

架构：
  - _build_content_lines(): 通用统计内容行（两渠道共用，避免口径漂移）
  - FeishuNotifier: 飞书群机器人（interactive 卡片，高风险红色告警）
  - WeComNotifier: 企业微信群机器人（markdown 消息）
  - 两渠道均支持 --dry-run 预览；webhook 支持环境变量或 config/notify.json
"""

import json
import logging
import os
from datetime import datetime

import requests

logger = logging.getLogger(__name__)


def _build_content_lines(stats: dict, since: str, high_risk: list[dict]) -> list[str]:
    """生成通用日报内容行（不含平台专属格式标记）。"""
    date_range = f"{since} ~ {datetime.now():%Y-%m-%d}"
    pt = stats["pt_total"]
    total = stats["total"]
    ratio = f"{pt / total * 100:.1f}%" if total else "0%"

    lines = [f"统计窗口：{date_range}",
             f"动力总成抱怨：{pt} 条（占全部投诉 {ratio}，共 {total} 条）",
             "",
             "子系统分布："]

    subs = stats["subsystem"] or []
    if subs:
        for s, c in subs:
            lines.append(f"· {s or '其他'}：{c}")
    else:
        lines.append("· 无")

    brands = stats["brands"] or []
    if brands:
        lines.append("")
        lines.append("TOP 5 品牌：" + " / ".join(
            f"{b or '未知'}({c})" for b, c in brands[:5]))

    risk_lines = []
    for r in high_risk[:5]:
        risk_lines.append(f"· {r['complaint_date']} {r['brand']} {r['series']}"
                          f"：{r['title'][:40]}")
    if risk_lines:
        lines.append("")
        lines.append("⚠ 高风险问题（自燃/失速/无法启动等）：")
        lines.extend(risk_lines)

    return lines


def _resolve_webhook(env_var: str, cfg_value: str) -> str:
    """webhook 解析：环境变量优先，其次配置文件。"""
    return os.environ.get(env_var, "").strip() or str(cfg_value).strip()


class FeishuNotifier:
    """飞书自定义群机器人推送（interactive 卡片）。"""

    def __init__(self, notify_cfg: dict):
        self.webhook = _resolve_webhook("FEISHU_WEBHOOK", notify_cfg.get("webhook", ""))
        self.enabled = bool(notify_cfg.get("enabled")) and bool(self.webhook)
        self.report_title = notify_cfg.get("report_title", "🚗 动力总成抱怨日报")

    def available(self, dry_run: bool = False) -> bool:
        return True if dry_run else (self.enabled and bool(self.webhook))

    def build_daily_card(self, stats: dict, since: str, high_risk: list[dict]) -> dict:
        """构造飞书 interactive 卡片。"""
        lines = _build_content_lines(stats, since, high_risk)
        # 转飞书 lark_md 加粗
        lines[0] = f"**{lines[0]}**"
        lines[1] = f"**{lines[1]}**"
        for i, line in enumerate(lines):
            if line.startswith("子系统分布") or line.startswith("TOP 5") or \
                    line.startswith("⚠"):
                lines[i] = f"**{line}**"

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

    def send_card(self, card: dict, dry_run: bool = False) -> bool:
        """发送飞书卡片；dry_run 仅打印。"""
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

    def send_daily(self, stats: dict, since: str, high_risk: list[dict],
                   dry_run: bool = False) -> bool:
        """一站式发送日报。"""
        return self.send_card(self.build_daily_card(stats, since, high_risk), dry_run)


class WeComNotifier:
    """企业微信群机器人推送（markdown 消息）。

    企微机器人能力限制：markdown 消息 ≤4096 字节、每分钟 ≤20 条。
    webhook 形如 https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx
    """

    def __init__(self, notify_cfg: dict):
        wecom = notify_cfg.get("wecom", {}) or {}
        self.webhook = _resolve_webhook("WECOM_WEBHOOK", wecom.get("webhook", ""))
        self.enabled = bool(wecom.get("enabled")) and bool(self.webhook)
        self.report_title = wecom.get("report_title", "🚗 动力总成抱怨日报")

    def available(self, dry_run: bool = False) -> bool:
        return True if dry_run else (self.enabled and bool(self.webhook))

    def build_daily_markdown(self, stats: dict, since: str,
                             high_risk: list[dict]) -> str:
        """构造企微 markdown 日报内容。"""
        lines = _build_content_lines(stats, since, high_risk)
        date_range = f"{since} ~ {datetime.now():%Y-%m-%d}"

        md = [f"## {self.report_title}（{date_range}）", "",
              f"**{lines[0]}**", f"**{lines[1]}**", ""]

        # 子系统分布（引用块）
        in_subs = False
        for line in lines[2:]:
            if line == "子系统分布：":
                md.append("**子系统分布**")
                in_subs = True
                continue
            if line.startswith("TOP 5"):
                md.append("")
                md.append(f"**{line}**")
                in_subs = False
                continue
            if line.startswith("⚠"):
                md.append("")
                md.append(f'<font color="warning">**{line}**</font>')
                in_subs = False
                continue
            if line.startswith("· "):
                md.append(f"> {line[2:]}" if in_subs else line)
                continue
            if line:
                md.append(line)

        if high_risk:
            md.append("")
            md.append('<font color="warning">数据来源：车质网公开投诉 | 详细清单见 Excel 报表</font>')
        else:
            md.append("")
            md.append("数据来源：车质网公开投诉 | 详细清单见 Excel 报表")
        return "\n".join(md)

    def send_message(self, content: str, dry_run: bool = False) -> bool:
        """发送企微 markdown 消息；dry_run 仅打印。"""
        payload = json.dumps({"msgtype": "markdown",
                              "markdown": {"content": content}},
                             ensure_ascii=False, indent=2)
        if dry_run:
            print("[dry-run] 企微 markdown 消息:\n" + content)
            return True
        if not self.webhook:
            logger.warning("未配置企微 webhook，跳过推送")
            return False
        try:
            resp = requests.post(self.webhook,
                                 json={"msgtype": "markdown",
                                       "markdown": {"content": content}},
                                 timeout=10)
            body = resp.json()
            if resp.status_code == 200 and body.get("errcode") == 0:
                logger.info("企微日报推送成功")
                return True
            logger.error("企微推送失败: %s %s", resp.status_code, body)
            return False
        except (requests.RequestException, ValueError) as exc:
            logger.error("企微推送异常: %s", exc)
            return False

    def send_daily(self, stats: dict, since: str, high_risk: list[dict],
                   dry_run: bool = False) -> bool:
        """一站式发送日报。"""
        return self.send_message(self.build_daily_markdown(stats, since, high_risk),
                                 dry_run)
