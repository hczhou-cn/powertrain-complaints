#!/bin/bash
# macOS launchd 调用的定时任务包装器：失败后自动重跑，避免短时网络波动造成漏发。
set -u

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-/opt/anaconda3/bin/python3}"
if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="$(command -v python3 || true)"
fi

if [ -z "$PYTHON_BIN" ] || [ ! -x "$PYTHON_BIN" ]; then
    echo "[scheduled] 找不到可执行的 python3"
    exit 127
fi

cd "$PROJECT_DIR" || exit 1

for attempt in 1 2 3; do
    echo "[scheduled] 开始执行，第 ${attempt}/3 次"
    "$PYTHON_BIN" run.py --notify --dashboard
    status=$?
    if [ "$status" -eq 0 ]; then
        echo "[scheduled] 执行成功"
        exit 0
    fi
    echo "[scheduled] 执行失败，退出码 ${status}"
    if [ "$attempt" -lt 3 ]; then
        echo "[scheduled] 10 分钟后重试"
        sleep 600
    fi
done

echo "[scheduled] 三次执行均失败"
exit 1
