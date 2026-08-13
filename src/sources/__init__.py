# -*- coding: utf-8 -*-
"""多源可插拔架构（M4）。

接入新数据源只需实现 ComplaintSource 接口并注册：
  1. 实现本模块中的抽象方法（列表页抓取/解析、详情页抓取/解析）
  2. 在 main.py 的 SOURCES 注册表中登记 source id
  3. 入库记录自动带 source 字段，可跨源统一分析

2026-08 源可用性实测：
  - qczx（车质网）：可用，列表页可翻 300+ 页（约 3 周数据）
  - dpac（缺陷产品中心）：不可达（HTTP 000），需代理后接入
  - heimao（黑猫投诉）：入口需 JS 渲染，分类路径不公开稳定，需逆向 API
  - autohome（汽车之家）：仅口碑无投诉板块，反爬签名强，暂不接入
"""

from abc import ABC, abstractmethod


class ComplaintSource(ABC):
    """数据源接口：统一列表页/详情页的抓取与解析。"""

    id: str = ""
    name: str = ""

    @abstractmethod
    def fetch_list_page(self, page: int) -> str | None:
        """抓取第 page 页投诉列表，返回解码后 HTML。"""

    @abstractmethod
    def parse_list(self, html: str) -> list[dict]:
        """解析列表页，返回记录列表（字段见 qczx 实现）。"""

    @abstractmethod
    def fetch_detail(self, url: str) -> str | None:
        """抓取投诉详情页 HTML。"""

    @abstractmethod
    def parse_detail(self, html: str) -> tuple[str, str]:
        """解析详情页，返回 (完整内容, 回复)。"""

    def polite_sleep(self) -> None:
        """请求间隔限速（默认空实现，由具体源决定）。"""


# 已注册数据源（接入新源在此登记）
from .qczx import QczxSource  # noqa: E402  （依赖上方抽象基类）

SOURCES = {
    "qczx": QczxSource,
}
