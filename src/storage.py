# -*- coding: utf-8 -*-
"""存储层：SQLite 幂等入库与报表查询。"""

import logging
import os
import sqlite3

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS complaints (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source        TEXT DEFAULT 'qczx',
    complaint_no  TEXT UNIQUE NOT NULL,
    brand         TEXT,
    series        TEXT,
    model         TEXT,
    title         TEXT,
    content       TEXT,
    reply         TEXT,
    issue_code    TEXT,
    complaint_date TEXT,
    status        TEXT,
    detail_url    TEXT,
    is_powertrain INTEGER DEFAULT 0,
    pt_subsystem  TEXT,
    matched_by    TEXT,
    matched_keywords TEXT,
    crawled_at    TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_pt ON complaints(is_powertrain, pt_subsystem);
CREATE INDEX IF NOT EXISTS idx_date ON complaints(complaint_date);
"""

# 已发布版本新增列（轻量迁移：检查列存在性，缺失则 ALTER TABLE）
_MIGRATIONS = [
    ("source", "ALTER TABLE complaints ADD COLUMN source TEXT DEFAULT 'qczx'"),
]


def init_db(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """对旧库执行增量迁移（新列/新索引）。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(complaints)")}
    for col, ddl in _MIGRATIONS:
        if col not in cols:
            conn.execute(ddl)
            conn.commit()
            logger.info("迁移: 新增列 %s", col)


def upsert_complaint(conn: sqlite3.Connection, record: dict) -> bool:
    """插入投诉记录；主键已存在则更新内容/识别字段（幂等）。返回是否新增。"""
    is_new = conn.execute(
        "SELECT 1 FROM complaints WHERE complaint_no = ?",
        (record["complaint_no"],),
    ).fetchone() is None

    conn.execute(
        """
        INSERT INTO complaints
            (source, complaint_no, brand, series, model, title, content, reply,
             issue_code, complaint_date, status, detail_url,
             is_powertrain, pt_subsystem, matched_by, matched_keywords)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(complaint_no) DO UPDATE SET
            content = excluded.content,
            reply = excluded.reply,
            is_powertrain = excluded.is_powertrain,
            pt_subsystem = excluded.pt_subsystem,
            matched_by = excluded.matched_by,
            matched_keywords = excluded.matched_keywords,
            status = excluded.status
        """,
        (
            record.get("source", "qczx"), record["complaint_no"],
            record.get("brand", ""), record.get("series", ""),
            record.get("model", ""), record.get("title", ""),
            record.get("content", ""), record.get("reply", ""),
            record.get("issue_code", ""), record.get("complaint_date", ""),
            record.get("status", ""), record.get("detail_url", ""),
            1 if record.get("is_powertrain") else 0,
            record.get("subsystem", ""), record.get("matched_by", ""),
            record.get("matched_keywords", ""),
        ),
    )
    conn.commit()
    return is_new


# ---------- 报表查询（M3） ----------

def fetch_detail(conn: sqlite3.Connection, since: str, is_pt: int | None = None,
                 source: str | None = None) -> list[dict]:
    """近 N 天投诉明细（可按动力总成/来源过滤），按时间倒序。"""
    sql = ("SELECT complaint_no, brand, series, model, title, issue_code, "
           "complaint_date, status, pt_subsystem, matched_by, matched_keywords, "
           "detail_url, source FROM complaints WHERE complaint_date >= ?")
    params: list = [since]
    if is_pt is not None:
        sql += " AND is_powertrain = ?"
        params.append(is_pt)
    if source:
        sql += " AND source = ?"
        params.append(source)
    sql += " ORDER BY complaint_date DESC, complaint_no DESC"
    cols = ["complaint_no", "brand", "series", "model", "title", "issue_code",
            "complaint_date", "status", "pt_subsystem", "matched_by",
            "matched_keywords", "detail_url", "source"]
    rows = conn.execute(sql, params).fetchall()
    return [dict(zip(cols, r)) for r in rows]


def summary_stats(conn: sqlite3.Connection, since: str) -> dict:
    """窗口内聚合统计：总数、动力总成数、子系统分布、品牌/车系排行、按日趋势。"""
    total = conn.execute(
        "SELECT COUNT(*) FROM complaints WHERE complaint_date >= ?", (since,)).fetchone()[0]
    pt_total = conn.execute(
        "SELECT COUNT(*) FROM complaints WHERE complaint_date >= ? AND is_powertrain=1",
        (since,)).fetchone()[0]

    subsystem = conn.execute(
        "SELECT pt_subsystem, COUNT(*) FROM complaints "
        "WHERE complaint_date >= ? AND is_powertrain=1 "
        "GROUP BY pt_subsystem ORDER BY COUNT(*) DESC", (since,)).fetchall()

    brands = conn.execute(
        "SELECT brand, COUNT(*) FROM complaints "
        "WHERE complaint_date >= ? AND is_powertrain=1 "
        "GROUP BY brand ORDER BY COUNT(*) DESC", (since,)).fetchall()

    series = conn.execute(
        "SELECT brand || ' ' || series, COUNT(*) FROM complaints "
        "WHERE complaint_date >= ? AND is_powertrain=1 "
        "GROUP BY brand, series ORDER BY COUNT(*) DESC", (since,)).fetchall()

    trend = conn.execute(
        "SELECT complaint_date, "
        "SUM(is_powertrain) AS pt_cnt, COUNT(*) AS total_cnt "
        "FROM complaints WHERE complaint_date >= ? "
        "GROUP BY complaint_date ORDER BY complaint_date", (since,)).fetchall()

    return {
        "total": total,
        "pt_total": pt_total,
        "subsystem": subsystem,
        "brands": brands,
        "series": series,
        "trend": trend,
    }
