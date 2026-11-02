#!/usr/bin/env bash
# 一键启动选品数据采集控制台
# 双击运行，或 ./start_web.sh
cd "$(dirname "$0")"

PORT="${PORT:-8899}"
PY=".venv/bin/python"

# 没装依赖就先装
if [ ! -x "$PY" ]; then
  echo "首次运行，正在创建环境…"
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
  python3 setup.py
fi

# 清掉内部代理（否则 curl_cffi 会走代理导致 502）
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY

# 端口被占就往后找一个空的
while lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; do
  echo "端口 $PORT 被占用，换下一个…"
  PORT=$((PORT+1))
  if [ $PORT -gt 8920 ]; then echo "找不到空闲端口了"; exit 1; fi
done

echo ""
echo "  🛒 选品数据采集控制台"
echo "  ─────────────────────────────────────"
echo "  地址：http://127.0.0.1:$PORT"
echo "  停止：在本窗口按 Ctrl+C"
echo ""
echo "  ⚠️  请用上面的地址访问，不要直接双击打开 HTML 文件"
echo ""

sleep 1
# 3 秒后自动打开浏览器
( sleep 3
  if command -v open >/dev/null 2>&1; then open "http://127.0.0.1:$PORT"
  else xdg-open "http://127.0.0.1:$PORT" 2>/dev/null || true
  fi ) &

exec .venv/bin/python web_server.py
