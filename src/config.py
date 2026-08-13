# -*- coding: utf-8 -*-
"""配置加载：config/*.json 与默认值合并，业务可直接维护规则文件。"""

import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BASE_DIR, "config")

# 默认值（配置文件缺字段时兜底，保证零配置可运行）
_DEFAULTS = {
    "settings": {
        "base_list_url": "https://www.12365auto.com/zlts/0-0-0-0-0-0_0-0-{page}.shtml",
        "headers": {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
        "request": {
            "timeout_connect": 5, "timeout_read": 10,
            "delay_min": 1.0, "delay_max": 2.5,
            "max_retries": 2, "retry_backoff": [3, 6],
            "circuit_break_threshold": 3, "bypass_proxy": False,
        },
        "default_pages": 20,
        "default_days": 7,
        "paths": {
            "db": "data/complaints.db",
            "output_dir": "output/reports",
            "log_dir": "logs",
        },
    },
    "issue_codes": {
        "code_prefix_map": {"A": "发动机", "B": "变速器", "C": "离合器"},
        "code_whitelist": {"H340": "动力电池", "H343": "动力电池/BMS"},
    },
    "keywords": {
        "subsystem_keywords": {
            "发动机": ["发动机", "引擎", "机油", "烧机油", "增压器", "拉缸", "失火",
                       "催化", "水温", "冷却液"],
            "变速器": ["变速箱", "变速器", "顿挫", "挂挡", "换挡", "双离合", "CVT",
                       "传动系统", "传动轴", "差速器", "分动箱"],
            "离合器": ["离合器", "离合片", "压盘"],
            "动力电池": ["电池", "电芯", "续航", "衰减", "充不进", "充电故障",
                          "BMS", "热失控", "鼓包", "掉电", "自燃", "起火"],
            "驱动电机": ["电机", "电驱", "驱动电机", "失去动力", "动力中断"],
            "电控系统": ["电控", "控制器", "整车断电", "绝缘故障", "三电系统"],
            "混动系统": ["混动", "增程", "PHEV", "插混", "保电"],
        },
        "generic_keywords": [
            "无法启动", "打不着火", "熄火", "失速", "动力中断", "失去动力",
            "动力不足", "加速无力", "高温", "过热", "排放", "尾气", "油耗异常",
        ],
        "context_keywords": ["异响", "漏油", "抖动", "窜车"],
        "exclude_keywords": [
            "不予兑现", "承诺赠送", "购车时承诺", "订金", "定金", "锁单", "退订",
            "销售欺诈", "变相收费", "经销商服务", "承诺的充电桩",
        ],
        "subsystem_order": ["发动机", "变速器", "离合器", "动力电池", "驱动电机",
                            "电控系统", "混动系统", "其他"],
        "high_risk_keywords": [
            "自燃", "起火", "爆炸", "热失控", "失速", "动力中断", "无法启动",
            "刹车失灵", "召回",
        ],
    },
    "notify": {
        "webhook": "",
        "enabled": False,
        "report_title": "🚗 动力总成抱怨日报",
        "wecom": {
            "webhook": "",
            "enabled": False,
            "report_title": "🚗 动力总成抱怨日报",
        },
    },
}


def _load(name: str) -> dict:
    """加载单个配置文件（存在则读取，否则用默认值）。"""
    path = os.path.join(CONFIG_DIR, f"{name}.json")
    data = dict(_DEFAULTS[name])
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            user = json.load(f)
        # 浅合并顶层键；嵌套结构（request/paths 等）按需再合并
        for key, value in user.items():
            if isinstance(value, dict) and isinstance(data.get(key), dict):
                data[key].update(value)
            else:
                data[key] = value
    return data


def get_settings() -> dict:
    return _load("settings")


def get_issue_codes() -> dict:
    return _load("issue_codes")


def get_keywords() -> dict:
    return _load("keywords")


def get_notify() -> dict:
    return _load("notify")


def resolve_path(rel: str) -> str:
    """将配置中的相对路径解析为项目根下的绝对路径。"""
    if os.path.isabs(rel):
        return rel
    return os.path.join(BASE_DIR, rel)
