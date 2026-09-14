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
import time
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

_RETRY_DELAYS = (1, 3, 8)


def _post_json_with_retry(url: str, payload: dict, timeout: int,
                          label: str) -> tuple[int | None, dict | None]:
    """通知请求重试：先走系统网络，代理失败后自动切换直连。

    不把 URL 写入日志，避免 webhook key 出现在日志文件中。
    """
    last_status = None
    last_body = None
    for attempt, delay in enumerate(_RETRY_DELAYS, 1):
        for direct in (False, True):
            try:
                with requests.Session() as session:
                    if direct:
                        session.trust_env = False
                    response = session.post(url, json=payload, timeout=timeout)
                last_status = response.status_code
                try:
                    last_body = response.json()
                except ValueError:
                    last_body = {"text": response.text[:200]}
                if response.status_code == 200:
                    return last_status, last_body
                logger.warning("%s返回 HTTP %s（第 %d/%d 次，直连=%s）: %s",
                               label, response.status_code, attempt, len(_RETRY_DELAYS),
                               direct, last_body)
                if response.status_code not in (408, 429) and response.status_code < 500:
                    return last_status, last_body
            except requests.RequestException as exc:
                logger.warning("%s连接失败（第 %d/%d 次，直连=%s）: %s",
                               label, attempt, len(_RETRY_DELAYS), direct,
                               type(exc).__name__)
        if attempt < len(_RETRY_DELAYS):
            time.sleep(delay)
    return last_status, last_body


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

    # 重点集团专项提示（当前配置默认关注吉利集团）
    for focus in (stats.get("focus_groups") or {}).values():
        if not focus.get("total"):
            continue
        focus_brands = " / ".join(
            f"{brand or '未知'}({count})" for brand, count in focus.get("brands", [])[:4])
        lines.append("")
        lines.append(
            f"🔎 {focus.get('name', '重点集团')}专项：{focus['total']} 条，"
            f"占动力总成 {focus.get('ratio', 0) * 100:.1f}%"
        )
        if focus_brands:
            lines.append(f"· 重点品牌：{focus_brands}")
        if focus.get("high_risk"):
            lines.append(f"⚠ {focus.get('name', '重点集团')}专项高风险：{len(focus['high_risk'])} 条")
            for item in focus["high_risk"][:3]:
                lines.append(f"· {item['brand']} {item['series']}：{item['title'][:36]}")

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
        status, body = _post_json_with_retry(
            self.webhook, card, timeout=15, label="飞书日报")
        if status == 200 and body and body.get("code") == 0:
            logger.info("飞书日报推送成功")
            return True
        logger.error("飞书推送失败（HTTP %s）: %s", status, body)
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
        self.send_report = bool(wecom.get("send_report", False))  # 是否随日报推送 Excel 报表
        self.send_dashboard = bool(wecom.get("send_dashboard", False))  # 是否随日报推送 HTML 看板
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
            md.append('<font color="warning">数据来源：车质网公开投诉 | 详细清单见 Excel 报表 | HTML 看板建议使用浏览器打开</font>')
        else:
            md.append("")
            md.append("数据来源：车质网公开投诉 | 详细清单见 Excel 报表 | HTML 看板建议使用浏览器打开")
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
        status, body = _post_json_with_retry(
            self.webhook,
            {"msgtype": "markdown", "markdown": {"content": content}},
            timeout=15,
            label="企微日报",
        )
        if status == 200 and body and body.get("errcode") == 0:
            logger.info("企微日报推送成功")
            return True
        logger.error("企微推送失败（HTTP %s）: %s", status, body)
        return False

    def send_daily(self, stats: dict, since: str, high_risk: list[dict],
                   dry_run: bool = False) -> bool:
        """一站式发送日报。"""
        return self.send_message(self.build_daily_markdown(stats, since, high_risk),
                                 dry_run)

    # ---------- Excel 报表文件推送 ----------

    def _extract_key(self) -> str:
        """从 webhook URL 提取 key 参数（上传文件接口需要）。"""
        from urllib.parse import parse_qs, urlparse
        return parse_qs(urlparse(self.webhook).query).get("key", [""])[0]

    def upload_media(self, file_path: str) -> str | None:
        """上传文件到企微，返回 media_id（文件 ≤ 20MB，media_id 有效期 3 天）。"""
        key = self._extract_key()
        url = ("https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media"
               f"?key={key}&type=file")
        for attempt, delay in enumerate(_RETRY_DELAYS, 1):
            for direct in (False, True):
                try:
                    with requests.Session() as session:
                        if direct:
                            session.trust_env = False
                        with open(file_path, "rb") as f:
                            resp = session.post(
                                url, files={"media": (os.path.basename(file_path), f)},
                                timeout=30)
                    body = resp.json()
                    if resp.status_code == 200 and body.get("errcode") == 0:
                        logger.info("企微文件上传成功: %s", os.path.basename(file_path))
                        return body["media_id"]
                    logger.warning("企微文件上传失败（HTTP %s，第 %d/%d 次，直连=%s）: %s",
                                   resp.status_code, attempt, len(_RETRY_DELAYS), direct, body)
                    if resp.status_code not in (408, 429) and resp.status_code < 500:
                        return None
                except requests.RequestException as exc:
                    logger.warning("企微文件上传连接失败（第 %d/%d 次，直连=%s）: %s",
                                   attempt, len(_RETRY_DELAYS), direct, type(exc).__name__)
                except (OSError, ValueError) as exc:
                    logger.error("企微文件上传异常（%s）: %s", type(exc).__name__, exc)
                    return None
            if attempt < len(_RETRY_DELAYS):
                time.sleep(delay)
        logger.error("企微文件上传最终失败: %s", os.path.basename(file_path))
        return None

    def send_file(self, file_path: str, dry_run: bool = False) -> bool:
        """发送 Excel 报表文件到企微群；dry_run 仅打印。"""
        if not os.path.exists(file_path):
            logger.warning("报表文件不存在，跳过推送: %s", file_path)
            return False
        if dry_run:
            print(f"[dry-run] 企微发送报表文件: {file_path}")
            return True
        media_id = self.upload_media(file_path)
        if not media_id:
            return False
        status, body = _post_json_with_retry(
            self.webhook,
            {"msgtype": "file", "file": {"media_id": media_id}},
            timeout=15,
            label="企微文件推送",
        )
        if status == 200 and body and body.get("errcode") == 0:
            logger.info("企微报表文件推送成功: %s", os.path.basename(file_path))
            return True
        logger.error("企微文件推送失败（HTTP %s）: %s", status, body)
        return False
