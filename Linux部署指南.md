# Linux 服务器部署指南

> 目标：将"汽车动力总成抱怨采集分析系统"部署到常开 Linux 服务器，实现 7×24 稳定运行（不关机、不睡眠、每天 9 点自动推送）。
> 适用：Ubuntu/Debian 系服务器（其他发行版命令略有差异）。
> 更新日期：2026-08-13

---

## 0. 部署架构

```
┌─────────────────────────────────────────────────┐
│ Linux 服务器（7×24 常开）                        │
│                                                 │
│  systemd timer 每日 09:00 ──► run.py ──► 采集    │
│        （时区 Asia/Shanghai）      │   识别      │
│                                   │   入库      │
│                                   │   报表      │
│                                   ▼            │
│                          ┌──────────────┐      │
│                          │ 飞书/企微群推送 │      │
│                          └──────────────┘      │
└─────────────────────────────────────────────────┘
```

**前置要求：**
- 服务器能访问 `www.12365auto.com`（国内服务器直连即可）
- 服务器能访问 `qyapi.weixin.qq.com` / `open.feishu.cn`（推送用）
- 建议 1 核 1G 以上，本项目极轻量（内存占用 <200MB）

---

## 1. 环境准备

```bash
# 更新系统并安装 Python 3.10+ 与 venv
sudo apt update && sudo apt install -y python3 python3-venv python3-pip git

# 设置服务器时区为中国标准时间（关键！否则定时任务会差 8 小时）
sudo timedatectl set-timezone Asia/Shanghai
timedatectl   # 确认 Time zone: Asia/Shanghai

python3 --version   # 确认 ≥ 3.10
```

---

## 2. 部署代码

### 方式 A：git clone（推荐）

```bash
cd /opt
sudo mkdir -p /opt/apps && sudo chown $USER /opt/apps
cd /opt/apps
git clone <你的仓库地址> powertrain-complaints
cd powertrain-complaints
```

### 方式 B：从 Mac 整体拷贝（含历史数据）

```bash
# 在 Mac 上执行
scp -r /Users/zhouhaocheng/powertrain-complaints user@服务器IP:/opt/apps/
```

> 若拷贝方式 B，`data/complaints.db` 历史数据会一并带过去（方式 A 不含数据，首次会自动从空库开始，或按第 5 节迁移）。

---

## 3. Python 虚拟环境与依赖

```bash
cd /opt/apps/powertrain-complaints

# 创建虚拟环境（隔离依赖，避免污染系统 Python）
python3 -m venv venv

# 激活并安装依赖
./venv/bin/pip install -r requirements.txt

# 验证
./venv/bin/python -c "import requests, bs4, lxml, openpyxl; print('依赖 OK')"
```

> 之后所有命令都用 `./venv/bin/python run.py`（或 `./venv/bin/python3`），不要用系统 python。

---

## 4. 配置文件

### 4.1 通知 webhook（必配）

```bash
# 从 Mac 拷贝（含飞书+企微 webhook），或手动创建
scp ~/powertrain-complaints/config/notify.json user@服务器IP:/opt/apps/powertrain-complaints/config/
```

或手动编辑：
```bash
cd /opt/apps/powertrain-complaints
nano config/notify.json
```

填入两个渠道的 webhook（与 Mac 上相同，或新机器用新机器人）：

```json
{
  "webhook": "https://open.feishu.cn/open-apis/bot/v2/hook/xxx",
  "enabled": true,
  "report_title": "🚗 动力总成抱怨日报",
  "wecom": {
    "webhook": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx",
    "enabled": true,
    "send_report": true,
    "send_dashboard": true,
    "report_title": "🚗 动力总成抱怨日报"
  }
}
```

### 4.2 采集参数（可选调整）

`config/settings.json`：`default_pages`（默认 20）、`default_days`（默认 7）等。
Linux 服务器无本地代理，通常不需要 `--direct`（如果服务器配了代理且不稳定，可加 `--direct` 直连）。

---

## 5. 首次运行验证（务必先手动跑通）

```bash
cd /opt/apps/powertrain-complaints

# ① 预览推送内容（不发）
./venv/bin/python run.py --report-only --notify --dry-run

# ② 真实推送测试（群里应收到日报）
./venv/bin/python run.py --report-only --notify

# ③ 完整跑一次（采集 + 报表 + 推送）
./venv/bin/python run.py --notify --dashboard
```

确认：控制台无报错、企微群收到日报+Excel+看板、`output/reports/` 有产物。

### 历史数据迁移（可选，保留 Mac 上已采集的基线）

```bash
# Mac 上
scp ~/powertrain-complaints/data/complaints.db \
    user@服务器IP:/opt/apps/powertrain-complaints/data/
```

---

## 6. 定时任务配置（推荐 systemd，备选 cron）

### 方案一：systemd timer（推荐——日志规范、失败可查、随系统启动）

```bash
sudo tee /etc/systemd/system/powertrain.service > /dev/null <<'EOF'
[Unit]
Description=车质网动力总成抱怨采集
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/opt/apps/powertrain-complaints
ExecStart=/opt/apps/powertrain-complaints/venv/bin/python run.py --notify --dashboard
# 单次任务最长 2 小时（网络慢/回填时），超时强制结束
TimeoutStartSec=7200
EOF

sudo tee /etc/systemd/system/powertrain.timer > /dev/null <<'EOF'
[Unit]
Description=每日 09:00 运行动力总成采集

[Timer]
OnCalendar=*-*-* 09:00:00
Persistent=true        # 错过（关机）后开机立即补跑
RandomizedDelaySec=120 # 随机延迟 0-2 分钟，避免整点高峰

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now powertrain.timer
sudo systemctl list-timers | grep powertrain   # 确认 next elapse
```

**systemd 优势**：`Persistent=true` 让关机错过的任务**开机自动补跑**（解决 Mac 上"关机漏跑"的痛点）；日志用 `journalctl` 查看。

```bash
# 查看运行日志
sudo journalctl -u powertrain -n 50
# 立即手动触发一次
sudo systemctl start powertrain
```

### 方案二：cron（简单版）

```bash
crontab -e
# 加入：
0 9 * * * cd /opt/apps/powertrain-complaints && ./venv/bin/python run.py --notify --dashboard >> logs/cron.log 2>&1
```

> ⚠️ cron 没有"错过补跑"机制；如需补跑请用方案一 systemd。

---

## 7. 日志轮转（防止日志无限增长）

```bash
sudo tee /etc/logrotate.d/powertrain > /dev/null <<'EOF'
/opt/apps/powertrain-complaints/logs/*.log {
    daily
    rotate 14
    compress
    missingok
    notifempty
    copytruncate
}
EOF
# 项目内日志自带有 5MB×3 轮转，此配置兜底保留 14 天
```

systemd 方案日志走 journald（`journalctl` 管理，无需 logrotate）。

---

## 8. 日常运维速查

| 操作 | 命令 |
|------|------|
| 查看下次执行时间 | `systemctl list-timers \| grep powertrain` |
| 查看最近日志 | `sudo journalctl -u powertrain -n 50` |
| 立即执行一次 | `sudo systemctl start powertrain` |
| 暂停定时 | `sudo systemctl stop powertrain.timer` |
| 恢复定时 | `sudo systemctl start powertrain.timer` |
| 手动采集（不带推送） | `./venv/bin/python run.py` |
| 改关键词后重打标 | `./venv/bin/python run.py --reclassify` |
| 回填历史 3 个月 | `./venv/bin/python run.py --backfill-months 3 --direct` |
| 代码更新 | `cd /opt/apps/powertrain-complaints && git pull && ./venv/bin/pip install -r requirements.txt` |

---

## 9. 常见问题

| 现象 | 处理 |
|------|------|
| 定时任务到点没跑 | ① `timedatectl` 确认时区是 Asia/Shanghai ② `systemctl status powertrain.timer` 看状态 ③ `journalctl -u powertrain` 看报错 |
| 推送失败（飞书/企微） | 服务器能否访问对应域名（`curl -I https://qyapi.weixin.qq.com`）；webhook 是否正确 |
| 采集 403/超时 | 源站偶发限流，程序自动重试；连续失败可加 `--direct` 或稍后手动重跑 |
| 内存/磁盘不足 | 检查 `output/reports/` 与 `logs/`（第 7 节已配轮转）；数据库单文件很小 |
| 服务器时间不准 | `sudo timedatectl set-ntp true` 开启 NTP |

---

## 10. 从 Mac 迁移到服务器的检查清单

- [ ] 服务器可访问车质网与飞书/企微 API
- [ ] Python 3.10+、venv、依赖安装完成
- [ ] `config/notify.json` webhook 已配置（或已从 Mac 拷贝）
- [ ] 手动运行一次全流程成功（`--notify --dashboard`）
- [ ] （可选）历史 `data/complaints.db` 已拷贝
- [ ] systemd timer 已启用且 `next elapse` 正确（09:00 Asia/Shanghai）
- [ ] 日志轮转已配置
- [ ] 原 Mac 的 crontab 已删除（避免 Mac 和服务器重复推送）
