# -*- coding: utf-8 -*-
"""车质网数据源实现（包装 Crawler 与解析函数）。"""

from ..crawler import Crawler
from ..parser import parse_detail_page, parse_list_page
from . import ComplaintSource


class QczxSource(ComplaintSource):
    """车质网（12365auto.com）投诉源。"""

    id = "qczx"
    name = "车质网"

    def __init__(self, settings: dict, bypass_proxy: bool = False):
        self.crawler = Crawler(settings, bypass_proxy=bypass_proxy)
        self.base_url = settings["base_list_url"]

    def fetch_list_page(self, page: int) -> str | None:
        return self.crawler.fetch_list_page(self.base_url, page)

    def parse_list(self, html: str) -> list[dict]:
        return parse_list_page(html)

    def fetch_detail(self, url: str) -> str | None:
        return self.crawler.fetch_detail(url)

    def parse_detail(self, html: str) -> tuple[str, str]:
        return parse_detail_page(html)

    def polite_sleep(self) -> None:
        self.crawler.polite_sleep()


# 已注册数据源（接入新源在此登记）
SOURCES = {
    "qczx": QczxSource,
}
