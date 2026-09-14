# -*- coding: utf-8 -*-
"""主编排：采集 → 识别 → 入库 → 报表 → 推送。

CLI 示例：
  python3 run.py                        # 近 7 天增量采集 + 报表
  python3 run.py --days 30 --pages 100  # 首次回填 30 天
  python3 run.py --no-detail            # 快速模式（不抓详情页）
  python3 run.py --report-only          # 仅基于库内数据生成报表
  python3 run.py --reclassify           # 识别规则变更后重打标
  python3 run.py --notify --dry-run     # 推送飞书（仅打印 payload）
"""

import argparse
import logging
import logging.handlers
import os
import sys
from datetime import datetime, timedelta

from . import config as cfg
from .classifier import PowertrainClassifier
from .dashboard import build_dashboard
from .focus import build_focus_summary
from .notifier import FeishuNotifier, WeComNotifier
from .report import export_csv, export_excel
from .sources import SOURCES
from .storage import fetch_detail, init_db, summary_stats, upsert_complaint

logger = logging.getLogger(__name__)

# 回填估算：实测车质网列表页约 300 页 ≈ 21 天数据（约 14.3 页/天）
_BACKFILL_PAGES_PER_DAY = 14.3


def setup_logging(log_dir: str, verbose: bool = False) -> None:
    """控制台 + 文件轮转日志。"""
    os.makedirs(log_dir, exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s | %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)

    fh = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "collect.log"), maxBytes=5 * 1024 * 1024,
        backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    root.addHandler(ch)


def scan_and_ingest(source, classifier, conn, args, settings) -> tuple[int, int, int]:
    """阶段 1-3：列表页扫描 → 初筛 → 详情补全 → 识别入库（多源架构，source 为数据源对象）。

    返回 (新增条数, 详情成功数, 详情失败数)。
    """
    since_date = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")

    # 区分"已完整"（含正文）与"缺正文"记录：缺正文的持续补抓
    complete_nos = {r[0] for r in conn.execute(
        "SELECT complaint_no FROM complaints WHERE content IS NOT NULL AND content != ''")}
    incomplete_nos = {r[0] for r in conn.execute(
        "SELECT complaint_no FROM complaints WHERE content IS NULL OR content = ''")}

    # ---- 阶段 1: 列表页扫描（倒序分页；早于回溯日期或全页已完整即停） ----
    list_records = []
    stopped_reason = ""
    for page in range(1, args.pages + 1):
        html = source.fetch_list_page(page)
        if html is None:
            logger.warning("第 %d 页抓取失败，停止翻页", page)
            stopped_reason = "抓取失败"
            break
        records = source.parse_list(html)
        if not records:
            logger.info("第 %d 页无数据，提前结束", page)
            stopped_reason = "无数据"
            break
        for r in records:
            r["source"] = source.id
        list_records.extend(records)
        oldest = min(r["complaint_date"] for r in records if r["complaint_date"])
        if not args.full and oldest < since_date:
            stopped_reason = "已覆盖回溯日期"
            break
        if not args.full and complete_nos and \
                not args.backfill_months and \
                all(r["complaint_no"] in complete_nos for r in records):
            stopped_reason = "无新增投诉"
            break
        source.polite_sleep()
        if page % 20 == 0:
            logger.info("[翻页进度] 已扫描 %d 页，累计 %d 条，最新日期 %s",
                        page, len(list_records), oldest)

    logger.info("[列表] 扫描 %d 页，共 %d 条投诉（停止原因: %s）",
                page, len(list_records), stopped_reason or "达到页数上限")

    # ---- 阶段 2: 初筛候选（与最终识别同源信号） ----
    candidates = []
    for r in list_records:
        if any(kw in r["title"] for kw in classifier.exclude_keywords):
            continue
        if classifier.code_channel(r["issue_code"]) or \
                classifier.keyword_channel(r["title"]):
            candidates.append(r)
    n_code = sum(1 for r in candidates if classifier.code_channel(r["issue_code"]))
    logger.info("[初筛] 动力总成候选 %d 条（代码 %d / 关键词 %d）",
                len(candidates), n_code, len(candidates) - n_code)

    # ---- 阶段 3: 详情页补全 + 最终识别 + 入库 ----
    detail_ok = detail_fail = new_count = 0
    done_nos = set()
    for i, rec in enumerate(candidates, 1):
        need_detail = (not args.no_detail) and rec.get("detail_url") and \
            rec["complaint_no"] not in done_nos and \
            (rec["complaint_no"] not in complete_nos or rec["complaint_no"] in incomplete_nos)
        if need_detail:
            html = source.fetch_detail(rec["detail_url"])
            if html is not None:
                content, reply = source.parse_detail(html)
                rec["content"], rec["reply"] = content, reply
                detail_ok += 1
                done_nos.add(rec["complaint_no"])
            else:
                detail_fail += 1
                rec["content"], rec["reply"] = "", ""
            source.polite_sleep()

        rec.update(classifier.classify(rec))
        if upsert_complaint(conn, rec):
            new_count += 1
        if i % 20 == 0 or i == len(candidates):
            logger.info("[进度] 候选处理 %d/%d，详情成功 %d，失败 %d",
                        i, len(candidates), detail_ok, detail_fail)

    return new_count, detail_ok, detail_fail


def reclassify(conn, classifier, since_date) -> int:
    """识别规则变更后对库内记录重新打标（不访问网络）。返回动力总成条数。"""
    rows = conn.execute(
        "SELECT complaint_no, brand, series, model, title, content, reply, "
        "issue_code, complaint_date, status, detail_url "
        "FROM complaints WHERE complaint_date >= ?", (since_date,)).fetchall()
    n_pt = 0
    for row in rows:
        rec = dict(zip(["complaint_no", "brand", "series", "model", "title",
                        "content", "reply", "issue_code", "complaint_date",
                        "status", "detail_url"], row))
        rec.update(classifier.classify(rec))
        upsert_complaint(conn, rec)
        if rec.get("is_powertrain"):
            n_pt += 1
    logger.info("[重识别] 处理库内记录 %d 条，其中动力总成相关 %d 条", len(rows), n_pt)
    return n_pt


def build_reports(conn, classifier, since_date, args, settings) -> tuple[str, str, dict, list]:
    """阶段 4：CSV + Excel 报表，返回 (csv_path, excel_path, stats, high_risk)。"""
    out_dir = cfg.resolve_path(settings["paths"]["output_dir"])
    stamp = datetime.now().strftime("%Y%m%d")
    csv_path = args.csv_out or os.path.join(out_dir, f"powertrain_complaints_{stamp}.csv")
    excel_path = os.path.join(out_dir, f"powertrain_report_{stamp}.xlsx")

    # 高风险记录（供报表标红与日报告警）
    detail = fetch_detail(conn, since_date, is_pt=1)
    high_risk = []
    for r in detail:
        hits = classifier.high_risk_hits(r)
        if hits:
            r["risk_keywords"] = ",".join(hits)
            high_risk.append(r)

    focus_summaries = build_focus_summary(
        detail, cfg.get_keywords().get("focus_groups", {}), classifier)

    n_csv = export_csv(conn, since_date, csv_path)
    n_excel = export_excel(conn, since_date, excel_path, classifier, high_risk,
                           focus_summaries)

    stats = summary_stats(conn, since_date)
    stats["focus_groups"] = focus_summaries
    pt = stats["pt_total"]
    total = stats["total"]
    logger.info("库视图统计（自 %s）: 投诉 %d 条，动力总成 %d 条（%.1f%%）",
                since_date, total, pt, pt / total * 100 if total else 0)
    for sub, cnt in stats["subsystem"]:
        logger.info("  子系统 %s: %d", sub or "其他", cnt)
    return csv_path, excel_path, stats, high_risk


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="车质网汽车动力总成抱怨采集分析系统")
    parser.add_argument("--pages", type=int, default=None,
                        help="扫描列表页数上限（默认取配置 default_pages）")
    parser.add_argument("--days", type=int, default=None,
                        help="回溯天数（默认取配置 default_days）")
    parser.add_argument("--full", action="store_true",
                        help="全量模式：忽略天数限制，抓满 pages 页")
    parser.add_argument("--backfill-months", type=int, default=0,
                        help="历史回填：抓取最近 N 个月的列表数据（默认不抓详情页，可用 --with-detail 开启）")
    parser.add_argument("--with-detail", action="store_true",
                        help="回填模式下同时抓取详情页正文（耗时较长）")
    parser.add_argument("--no-detail", action="store_true",
                        help="快速模式：不抓详情页，仅列表页字段")
    parser.add_argument("--dashboard", action="store_true",
                        help="生成单文件 HTML 网页看板")
    parser.add_argument("--source", default="",
                        help="数据源 id（默认 qczx；多源注册见 src/sources）")
    parser.add_argument("--direct", action="store_true",
                        help="直连模式：绕过本地代理（实测代理高频隧道易挂起，回填建议开启）")
    parser.add_argument("--reclassify", action="store_true",
                        help="仅重新识别库内近 N 天记录（不访问网络）")
    parser.add_argument("--report-only", action="store_true",
                        help="仅基于库内数据生成报表与推送，不采集")
    parser.add_argument("--notify", action="store_true",
                        help="启用飞书推送（覆盖配置）")
    parser.add_argument("--no-notify", action="store_true",
                        help="禁用飞书推送（覆盖配置）")
    parser.add_argument("--dry-run", action="store_true",
                        help="飞书推送仅打印 payload，不实际发送")
    parser.add_argument("--csv-out", default="", help="CSV 输出路径（默认自动生成）")
    parser.add_argument("--verbose", action="store_true", help="DEBUG 日志")
    args = parser.parse_args(argv)

    settings = cfg.get_settings()
    setup_logging(cfg.resolve_path(settings["paths"]["log_dir"]), args.verbose)

    # 回填模式：按月份估算 days/pages（实测约 14.3 页/天）
    if args.backfill_months > 0:
        args.days = args.days or args.backfill_months * 31
        args.pages = args.pages or int(args.backfill_months * 31 * _BACKFILL_PAGES_PER_DAY) + 50
        if not args.with_detail:
            args.no_detail = True
        logger.info("回填模式: 最近 %d 个月 → days=%d, pages=%d, 详情页=%s",
                    args.backfill_months, args.days, args.pages,
                    "关闭" if args.no_detail else "开启")

    days = args.days if args.days else settings["default_days"]
    pages = args.pages if args.pages else settings["default_pages"]
    args.days, args.pages = days, pages

    since_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    classifier = PowertrainClassifier(cfg.get_issue_codes(), cfg.get_keywords())
    notify_cfg = cfg.get_notify()
    if args.notify:
        notify_cfg["enabled"] = True
        notify_cfg.setdefault("wecom", {})["enabled"] = True
    if args.no_notify:
        notify_cfg["enabled"] = False
        notify_cfg.setdefault("wecom", {})["enabled"] = False
    notifiers = [FeishuNotifier(notify_cfg), WeComNotifier(notify_cfg)]
    notifiers = [n for n in notifiers if n.available(args.dry_run)]

    conn = init_db(cfg.resolve_path(settings["paths"]["db"]))
    logger.info("启动: 回溯近 %d 天 | 列表页上限 %d | 全量=%s | 详情页=%s",
                days, pages, args.full, "关闭" if args.no_detail else "开启")

    if args.reclassify:
        reclassify(conn, classifier, since_date)

    # 重识别或报表模式均跳过网络采集
    if not (args.reclassify or args.report_only):
        source_cls = SOURCES.get(args.source or "qczx")
        if source_cls is None:
            logger.error("未知数据源: %s（可用: %s）", args.source, list(SOURCES))
            return 1
        source = source_cls(settings, bypass_proxy=args.direct)
        new_count, detail_ok, detail_fail = scan_and_ingest(
            source, classifier, conn, args, settings)
        logger.info("[采集] 本次入库新增 %d 条（重复已跳过），详情成功 %d，失败 %d",
                    new_count, detail_ok, detail_fail)

    # 报表与推送
    csv_path, excel_path, stats, high_risk = build_reports(
        conn, classifier, since_date, args, settings)
    print(f"\n[完成] CSV: {csv_path}\n[完成] Excel: {excel_path}")

    dash_path = ""
    if args.dashboard:
        out_dir = cfg.resolve_path(settings["paths"]["output_dir"])
        dash_path = os.path.join(out_dir, f"dashboard_{datetime.now():%Y%m%d}.html")
        build_dashboard(conn, since_date, classifier, dash_path)
        print(f"[完成] 看板: {dash_path}（浏览器打开）")

    notification_failures = 0
    if notifiers:
        for notifier in notifiers:
            if not notifier.send_daily(stats, since_date, high_risk,
                                       dry_run=args.dry_run):
                notification_failures += 1
        # 企微渠道随日报推送产物文件（飞书自定义机器人不支持文件消息）
        for notifier in notifiers:
            if not isinstance(notifier, WeComNotifier):
                continue
            if notifier.send_report and not notifier.send_file(
                    excel_path, dry_run=args.dry_run):
                notification_failures += 1
            if notifier.send_dashboard and dash_path and not notifier.send_file(
                    dash_path, dry_run=args.dry_run):
                notification_failures += 1
        if notification_failures:
            logger.error("[通知] 失败 %d 项；任务返回失败状态，调度器将按策略重试",
                         notification_failures)
        else:
            logger.info("[通知] 所有已启用渠道推送成功（%d 项）", len(notifiers))
    elif args.notify:
        logger.error("[通知] --notify 已启用，但没有可用通知渠道，请检查 webhook 和 enabled")
        notification_failures = 1
    else:
        logger.info("通知渠道均未启用（enabled=false 或未配置 webhook）")

    conn.close()
    return 2 if notification_failures else 0


if __name__ == "__main__":
    sys.exit(main())
