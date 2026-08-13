# -*- coding: utf-8 -*-
"""网页看板（M4）：从 SQLite 聚合数据，生成单文件 HTML 看板。

符合原型极速验证原则：0 构建依赖，Tailwind + ECharts 走 CDN，
数据内嵌到 HTML（file:// 双击即运行，无需本地服务器）。
"""

import json
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

_DASHBOARD_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>动力总成抱怨看板（__SINCE__ ~ __TODAY__）</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<script>
window.PI_DATA = __DATA__;
</script>
</head>
<body class="bg-slate-100 min-h-screen">
<div class="bg-slate-900 text-white px-6 py-4 flex items-center justify-between">
  <div>
    <h1 class="text-xl font-bold">🚗 汽车动力总成抱怨看板</h1>
    <p class="text-slate-400 text-sm mt-1">统计窗口：__SINCE__ ~ __TODAY__ ｜ 数据来源：车质网公开投诉</p>
  </div>
  <span class="text-sm px-3 py-1 rounded-full bg-slate-700" id="updateAt"></span>
</div>

<div class="max-w-7xl mx-auto p-6">
  <!-- 指标卡 -->
  <div class="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6" id="metrics"></div>

  <!-- 图表区 -->
  <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
    <div class="bg-white rounded-xl shadow p-4">
      <h2 class="font-semibold text-slate-700 mb-2">📈 每日投诉量趋势</h2>
      <div id="chartTrend" class="h-72"></div>
    </div>
    <div class="bg-white rounded-xl shadow p-4">
      <h2 class="font-semibold text-slate-700 mb-2">🧩 子系统分布</h2>
      <div id="chartSubsystem" class="h-72"></div>
    </div>
    <div class="bg-white rounded-xl shadow p-4">
      <h2 class="font-semibold text-slate-700 mb-2">🏭 TOP 10 品牌</h2>
      <div id="chartBrand" class="h-72"></div>
    </div>
    <div class="bg-white rounded-xl shadow p-4">
      <h2 class="font-semibold text-slate-700 mb-2">🚙 TOP 10 车系</h2>
      <div id="chartSeries" class="h-72"></div>
    </div>
  </div>

  <!-- 高风险区 -->
  <div class="bg-white rounded-xl shadow p-4 mb-6" id="riskSection">
    <h2 class="font-semibold text-red-600 mb-3">⚠️ 高风险问题（自燃/失速/无法启动/刹车失灵等）</h2>
    <div id="riskList" class="space-y-2"></div>
  </div>

  <!-- 明细表 -->
  <div class="bg-white rounded-xl shadow p-4">
    <div class="flex flex-wrap items-center gap-3 mb-3">
      <h2 class="font-semibold text-slate-700">📋 动力总成投诉明细（<span id="detailCount">0</span>）</h2>
      <input id="searchBox" type="text" placeholder="搜索品牌 / 车系 / 问题…"
             class="flex-1 min-w-40 border rounded-lg px-3 py-1.5 text-sm">
      <select id="subFilter" class="border rounded-lg px-3 py-1.5 text-sm"></select>
    </div>
    <div class="overflow-x-auto max-h-96 overflow-y-auto">
      <table class="w-full text-sm">
        <thead class="sticky top-0 bg-slate-800 text-white">
          <tr>
            <th class="px-2 py-2 text-left">日期</th>
            <th class="px-2 py-2 text-left">品牌</th>
            <th class="px-2 py-2 text-left">车系</th>
            <th class="px-2 py-2 text-left">问题简述</th>
            <th class="px-2 py-2 text-left">子系统</th>
            <th class="px-2 py-2 text-left">命中</th>
          </tr>
        </thead>
        <tbody id="detailBody"></tbody>
      </table>
    </div>
  </div>
</div>

<script>
const D = window.PI_DATA;
document.getElementById("updateAt").textContent = "生成于 " + new Date().toLocaleString("zh-CN");

// 指标卡
const metricDefs = [
  ["动力总成投诉", D.metrics.pt_total, "text-blue-600"],
  ["窗口内全部投诉", D.metrics.total, "text-slate-600"],
  ["动力总成占比", D.metrics.ratio, "text-green-600"],
  ["⚠ 高风险问题", D.metrics.high_risk, "text-red-600"],
];
const mBox = document.getElementById("metrics");
metricDefs.forEach(([label, value, color]) => {
  mBox.innerHTML += `
    <div class="bg-white rounded-xl shadow p-4">
      <p class="text-sm text-slate-500">${label}</p>
      <p class="text-3xl font-bold ${color} mt-1">${value}</p>
    </div>`;
});

// 趋势折线
const t = echarts.init(document.getElementById("chartTrend"));
t.setOption({
  tooltip: { trigger: "axis" },
  legend: { data: ["动力总成", "全部"] },
  grid: { left: 40, right: 16, top: 32, bottom: 24 },
  xAxis: { type: "category", data: D.trend.map(r => r[0]) },
  yAxis: { type: "value", minInterval: 1 },
  series: [
    { name: "动力总成", type: "line", smooth: true, data: D.trend.map(r => r[1]), areaStyle: { opacity: 0.15 } },
    { name: "全部", type: "line", smooth: true, data: D.trend.map(r => r[2]) },
  ],
});

// 子系统饼图
const s = echarts.init(document.getElementById("chartSubsystem"));
s.setOption({
  tooltip: { trigger: "item", formatter: "{b}: {c} 条 ({d}%)" },
  series: [{
    type: "pie", radius: ["38%", "68%"],
    data: D.subsystem.map(([name, value]) => ({ name: name || "其他", value })),
    label: { formatter: "{b}\\n{c} ({d}%)" },
  }],
});

// 品牌条形
const b = echarts.init(document.getElementById("chartBrand"));
b.setOption({
  tooltip: {},
  grid: { left: 90, right: 24, top: 16, bottom: 24 },
  xAxis: { type: "value", minInterval: 1 },
  yAxis: { type: "category", data: D.brands.map(r => r[0]).reverse() },
  series: [{ type: "bar", data: D.brands.map(r => r[1]).reverse(),
             itemStyle: { color: "#2563eb" }, barMaxWidth: 18 }],
});

// 车系条形
const sc = echarts.init(document.getElementById("chartSeries"));
sc.setOption({
  tooltip: {},
  grid: { left: 120, right: 24, top: 16, bottom: 24 },
  xAxis: { type: "value", minInterval: 1 },
  yAxis: { type: "category", data: D.series.map(r => r[0]).reverse() },
  series: [{ type: "bar", data: D.series.map(r => r[1]).reverse(),
             itemStyle: { color: "#0891b2" }, barMaxWidth: 18 }],
});

window.addEventListener("resize", () => { t.resize(); s.resize(); b.resize(); sc.resize(); });

// 高风险列表
const riskBox = document.getElementById("riskList");
if (D.high_risk.length === 0) {
  riskBox.innerHTML = '<p class="text-slate-400 text-sm">本窗口内无高风险问题 ✅</p>';
} else {
  D.high_risk.forEach(r => {
    riskBox.innerHTML += `
      <div class="bg-red-50 border border-red-200 rounded-lg px-4 py-2.5 flex flex-wrap gap-x-6 gap-y-1 text-sm">
        <span class="text-slate-500">${r.complaint_date}</span>
        <span class="font-semibold">${r.brand} ${r.series}</span>
        <span class="text-slate-700 flex-1 min-w-40">${r.title}</span>
        <span class="text-red-500 text-xs self-center">${r.risk_keywords}</span>
      </div>`;
  });
}

// 子系统筛选下拉
const subFilter = document.getElementById("subFilter");
const subSet = new Set(D.detail.map(r => r.pt_subsystem || "其他"));
subFilter.innerHTML = '<option value="">全部子系统</option>' +
  [...subSet].map(s => `<option value="${s}">${s}</option>`).join("");

// 明细表渲染
let rows = D.detail;
document.getElementById("detailCount").textContent = rows.length;
const body = document.getElementById("detailBody");
function render() {
  const kw = document.getElementById("searchBox").value.trim().toLowerCase();
  const sub = subFilter.value;
  const filtered = rows.filter(r =>
    (!sub || (r.pt_subsystem || "其他") === sub) &&
    (!kw || (r.brand + r.series + r.title).toLowerCase().includes(kw)));
  body.innerHTML = filtered.map(r => `
    <tr class="border-b hover:bg-blue-50 ${r.high_risk ? "bg-red-50" : ""}">
      <td class="px-2 py-1.5 whitespace-nowrap">${r.complaint_date}</td>
      <td class="px-2 py-1.5">${r.brand}</td>
      <td class="px-2 py-1.5">${r.series}</td>
      <td class="px-2 py-1.5">${r.title}</td>
      <td class="px-2 py-1.5"><span class="px-2 py-0.5 rounded-full bg-blue-100 text-blue-700 text-xs">${r.pt_subsystem || "其他"}</span></td>
      <td class="px-2 py-1.5 text-xs text-slate-400">${r.matched_keywords}</td>
    </tr>`).join("");
  document.getElementById("detailCount").textContent = filtered.length;
}
document.getElementById("searchBox").addEventListener("input", render);
subFilter.addEventListener("change", render);
render();
</script>
</body>
</html>
"""


def build_dashboard(conn, since: str, classifier, out_path: str) -> int:
    """生成看板 HTML，返回明细条数。"""
    from .storage import fetch_detail, summary_stats

    stats = summary_stats(conn, since)
    detail = fetch_detail(conn, since, is_pt=1)

    # 高风险标注
    high_risk = []
    risk_nos = set()
    for r in detail:
        hits = classifier.high_risk_hits(r)
        if hits:
            r["high_risk"] = True
            r["risk_keywords"] = ",".join(hits)
            high_risk.append(r)
            risk_nos.add(r["complaint_no"])
        else:
            r["high_risk"] = False

    data = {
        "metrics": {
            "total": stats["total"],
            "pt_total": stats["pt_total"],
            "ratio": f"{stats['pt_total'] / stats['total'] * 100:.1f}%" if stats["total"] else "0%",
            "high_risk": len(high_risk),
        },
        "trend": stats["trend"],
        "subsystem": stats["subsystem"],
        "brands": stats["brands"][:10],
        "series": stats["series"][:10],
        "high_risk": high_risk[:20],
        "detail": detail[:1000],
    }

    today = datetime.now().strftime("%Y-%m-%d")
    html = (_DASHBOARD_TEMPLATE
            .replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
            .replace("__SINCE__", since)
            .replace("__TODAY__", today))

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    logger.info("看板生成: %s（明细 %d 条，高风险 %d 条）", out_path, len(detail), len(high_risk))
    return len(detail)
