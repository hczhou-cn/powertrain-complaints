# -*- coding: utf-8 -*-
"""采集层：带 UA/超时/重试退避/限速/熔断的 HTML 抓取，以及智能编码检测。"""

import logging
import random
import re
import sys
import time

import requests

logger = logging.getLogger(__name__)


class Crawler:
    """车质网页面抓取器。

    设计要点（实测验证）：
      - 站点响应波动大（实测 1~17s），采用连接/读取分离超时，快速失败
      - 列表页为 UTF-8、详情页为 GB2312，逐响应智能判定编码
      - 连续触发反爬（403/captcha）时熔断退出，避免被封 IP
    """

    def __init__(self, settings: dict):
        req = settings["request"]
        self.timeout = (req["timeout_connect"], req["timeout_read"])
        self.delay_range = (req["delay_min"], req["delay_max"])
        self.max_retries = req["max_retries"]
        self.retry_backoff = req["retry_backoff"]
        self.circuit_break_threshold = req["circuit_break_threshold"]
        self._circuit_breaker = 0

        self._session = requests.Session()
        self._session.headers.update(settings["headers"])

    # ---------- 基础抓取 ----------

    @staticmethod
    def decode_response(raw: bytes, content_type: str = "") -> str:
        """智能编码检测：响应头 charset → meta charset → 严格 UTF-8 → GB18030 兜底。"""
        m = re.search(r"charset=[\"']?([\w-]+)", content_type, re.I)
        if m:
            try:
                return raw.decode(m.group(1))
            except (LookupError, UnicodeDecodeError):
                pass
        m = re.search(rb"charset=[\"']?([\w-]+)", raw[:2000], re.I)
        if m:
            try:
                return raw.decode(m.group(1).decode("ascii"))
            except (LookupError, UnicodeDecodeError):
                pass
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            pass
        return raw.decode("gb18030", errors="replace")

    def fetch_html(self, url: str) -> str | None:
        """抓取并解码 HTML；失败返回 None（调用方决定继续或停止）。"""
        for attempt in range(self.max_retries):
            try:
                resp = self._session.get(url, timeout=self.timeout)
                if resp.status_code == 403 or "captcha" in resp.text.lower():
                    self._circuit_breaker += 1
                    if self._circuit_breaker >= self.circuit_break_threshold:
                        logger.error("连续 %d 次反爬响应，触发熔断，停止抓取",
                                     self._circuit_breaker)
                        sys.exit(2)
                    raise requests.HTTPError(f"反爬响应 HTTP {resp.status_code}")
                resp.raise_for_status()
                self._circuit_breaker = 0
                return self.decode_response(
                    resp.content, resp.headers.get("Content-Type", ""))
            except requests.RequestException as exc:
                wait = self.retry_backoff[attempt] + random.uniform(0, 1)
                logger.warning("抓取失败 %s 第 %d/%d 次: %s，%.1fs 后重试",
                               url, attempt + 1, self.max_retries, exc, wait)
                if attempt < self.max_retries - 1:
                    time.sleep(wait)
        return None

    def polite_sleep(self) -> None:
        """请求间隔限速（随机抖动，规避风控）。"""
        time.sleep(random.uniform(*self.delay_range))

    # ---------- 页面级抓取 ----------

    def fetch_list_page(self, base_url: str, page: int) -> str | None:
        return self.fetch_html(base_url.format(page=page))

    def fetch_detail(self, detail_url: str) -> str | None:
        return self.fetch_html(detail_url)
