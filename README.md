# 汽车动力总成抱怨采集分析系统（M2 工程化 + M3 报表）

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)
![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux-blue)

自动抓取**车质网**（12365auto.com）中国汽车投诉数据，双通道识别**动力总成（Powertrain）**相关抱怨，结构化入库（SQLite），输出 **CSV + Excel 多 Sheet 报表 + HTML 看板**，支持**飞书 / 企微双渠道日报推送**。

## 目录结构

```
powertrain-complaints/
├── run.py                      # 入口：python3 run.py [选项]
├── config/                     # 业务可直接维护的规则配置（JSON）
│   ├── settings.json           #   抓取参数、限速、路径
│   ├── issue_codes.json        #   典型问题代码 → 子系统映射
│   ├── keywords.json           #   关键词规则 + 高风险词
│   └── notify.json             #   飞书 webhook 配置（勿提交 git）
├── src/                        # 模块化源码
│   ├── main.py                 #   编排入口 + CLI + 日志
│   ├── crawler.py              #   采集层（限速/重试/熔断/编码检测）
│   ├── parser.py               #   解析层（列表页/详情页）
│   ├── classifier.py           #   识别层（双通道规则引擎）
│   ├── storage.py              #   存储层（SQLite 幂等入库 + 报表查询）
│   ├── report.py               #   输出层（CSV + Excel 报表）
│   ├── notifier.py             #   通知层（飞书日报卡片）
│   └── config.py               #   配置加载（默认值兜底）
├── data/complaints.db          # SQLite 数据库（自动创建，勿提交）
├── output/reports/             # CSV + Excel 报表（自动生成）
└── logs/collect.log            # 轮转日志（自动生成）
```

## 快速开始

```bash
pip install -r requirements.txt

# 常规运行：近 7 天增量采集 + 报表
python3 run.py

# 首次回填 30 天历史
python3 run.py --days 30 --pages 100

# 快速模式（不抓详情页正文）
python3 run.py --no-detail

# 识别规则变更后，仅重打标库内记录（不访问网络）
python3 run.py --reclassify

# 仅基于库内数据生成报表（不采集）
python3 run.py --report-only

# 生成报表并推送飞书（先预览 payload）
python3 run.py --report-only --notify --dry-run
python3 run.py --notify
```

## CLI 参数

| 参数 | 说明 |
|------|------|
| `--pages N` | 列表页数上限（默认取配置 20） |
| `--days N` | 回溯天数（默认取配置 7） |
| `--full` | 全量模式，忽略天数限制 |
| `--backfill-months N` | 历史回填：抓取最近 N 个月列表数据（默认不抓详情页） |
| `--with-detail` | 回填模式下同时抓取详情页正文（耗时较长） |
| `--dashboard` | 生成单文件 HTML 网页看板（双击即运行） |
| `--source ID` | 数据源（默认 qczx；多源架构见 src/sources） |
| `--no-detail` | 不抓详情页正文（快速模式） |
| `--reclassify` | 仅重打标库内记录（改规则后用） |
| `--report-only` | 仅生成报表与推送，不采集 |
| `--notify` / `--no-notify` | 覆盖飞书推送开关 |
| `--dry-run` | 飞书推送仅打印 payload |
| `--verbose` | DEBUG 日志 |

## Excel 报表（M3）

`output/reports/powertrain_report_YYYYMMDD.xlsx`，6 个 Sheet：

| Sheet | 内容 |
|-------|------|
| 概览 | 核心指标、子系统分布（含占比）、TOP 10 品牌、⚠ 高风险问题 |
| 每日趋势 | 日期/投诉量 + 柱状图 |
| 品牌排行 | 品牌投诉数与占比 |
| 车系排行 | 车系投诉数 TOP 50 |
| 子系统分布 | 子系统数量与占比 |
| 投诉明细 | 全字段清单，**高风险投诉行标红** |

## 飞书日报（M3）

1. 在飞书群 → 设置 → 群机器人 → 添加**自定义机器人**，复制 webhook
2. 配置二选一：
   - 环境变量：`export FEISHU_WEBHOOK="https://open.feishu.cn/open-apis/bot/v2/hook/xxx"`
   - 或编辑 `config/notify.json` 填入 `webhook` 并设 `"enabled": true`
3. 先 `--dry-run` 预览卡片，再正式推送

日报卡片：统计窗口、动力总成投诉量/占比、子系统分布、TOP 5 品牌、**高风险问题清单**（自燃/失速/无法启动等，含"刹车失灵"关键词），有高风险时卡片红色告警。

## 通知渠道（M3 + 扩展）

| 渠道 | 格式 | 高风险样式 | Excel 报表 | HTML 看板 |
|------|------|-----------|-----------|----------|
| 飞书 | interactive 卡片 | 红色告警模板 | ❌（自定义机器人不支持文件） | ❌ |
| 企微 | markdown 消息 | `<font color="warning">` 橙色警示 | ✅ `send_report` | ✅ `send_dashboard` |

- 环境变量 `FEISHU_WEBHOOK` / `WECOM_WEBHOOK` 优先级高于 `config/notify.json`
- 企微推送 Excel：`config/notify.json` → `wecom.send_report: true`（文件 ≤20MB，media_id 有效期 3 天）
- `--dry-run` 预览两种渠道的日报与文件推送

## 定时任务（macOS launchd / cron）

每日 09:00 自动采集并推送，cron 示例：

```bash
0 9 * * * cd /Users/zhouhaocheng/powertrain-complaints && /opt/anaconda3/bin/python3 run.py --notify >> logs/cron.log 2>&1
```

程序幂等：重复运行不产生脏数据；日常运行第一页即停（无新增时仅 1-2 个请求）。

## 网页看板（M4）

`output/reports/dashboard_YYYYMMDD.html` —— 单文件 HTML，0 构建依赖，**浏览器双击即运行**：

```bash
python3 run.py --report-only --dashboard    # 用库内数据生成看板
python3 run.py --dashboard                 # 采集后直接生成
```

看板内容：4 指标卡（总数/动力总成/占比/高风险）＋ 4 图表（每日趋势折线、子系统饼图、TOP 品牌/车系条形）＋ 高风险问题列表 ＋ 可搜索/筛选的明细表。数据内嵌在 HTML 中（无需本地服务器）。

## 历史回填（M4）

建立趋势基线（实测车质网列表页可翻 300+ 页，约 3 周数据/300 页）：

```bash
# 回填最近 1 个月（默认只抓列表页字段，约 10 分钟）
python3 run.py --backfill-months 1

# 回填 3 个月并抓详情页正文（量大，可分次执行，幂等可断点续跑）
python3 run.py --backfill-months 3 --with-detail
```

## 多源架构（M4）

数据入库自动带 `source` 字段（当前 `qczx`）。接入新源：在 `src/sources/` 实现 `ComplaintSource` 接口（列表/详情页抓取与解析），并在 `src/sources/__init__.py` 的 `SOURCES` 注册表登记，`--source <id>` 即可切换。

2026-08 源可用性实测：车质网可用；缺陷产品中心（dpac）不可达；黑猫投诉入口需 JS 渲染；汽车之家仅口碑无投诉板块——后三者需代理/逆向后接入。

## 识别规则维护

改 `config/` 下 JSON 即生效（下次运行自动加载，无需改代码）：

- **issue_codes.json**：`code_prefix_map`（A/B/C 前缀映射）、`code_whitelist`（精确代码白名单，如 H340/H343）
- **keywords.json**：`subsystem_keywords`（子系统专有词定类）、`generic_keywords`（无条件通用词）、`context_keywords`（条件词，需与子系统词共现）、`exclude_keywords`（仅对标题判定的排除词）、`high_risk_keywords`（日报告警词）
- 改完执行 `python3 run.py --reclassify` 重打标

## 运行原理

```
列表页扫描（增量停止） → 初筛候选（代码/标题双信号） → 详情页正文补全（缺正文才抓）
→ 双通道识别 + 子系统打标 → SQLite 幂等入库 → CSV + Excel 报表 → 飞书日报
```

### 工程特性（M2）

- **幂等**：投诉编号主键，重复运行无脏数据
- **增量**：翻页遇"全页编号已完整"即停；快速模式缺正文的记录自动补抓
- **稳健**：连接/读取分离超时、指数退避重试、403 熔断、智能编码检测（列表页 UTF-8 / 详情页 GB2312）
- **日志**：控制台 + `logs/collect.log` 轮转（5MB × 3）
- **配置外置**：识别规则业务可直接维护，零代码改动

### 识别准确率（2026-08-13 抽样实测）

近 7 天扫描 166 条 → 识别动力总成 159 条（95.8%）。抽检人工复核：制动/辅助驾驶/电路系统误判已通过条件词与排除规则修正；埃安（广汽）动力电池投诉高度集中（36 条，多为中创新航 H343），与市场舆情吻合。

## 已知局限

1. 个别 `data-cti` 代码与实际故障模式有偏差（如 A359 实为驱动电机故障），可在 `issue_codes.json` 校准
2. 子系统单标签：多故障投诉仅取首个子系统，原文全文已留存
3. 新型故障模式（如"增程器""半轴异响"）需季度维护关键词表

## 合规声明

- 仅采集车质网公开投诉信息用于内部质量分析，不对外二次分发
- 请求限速（1~2.5s 随机抖动）、指数退避、反爬熔断；源站响应波动大（实测 1~17s），请勿高频调用
