#!/usr/bin/env python3
"""
temu_login.py —— Temu 登录助手（独立脚本）

用途：在一个有图形界面的机器上，登录一次 Temu，登录态存进 profile 目录，
      之后的采集任务直接复用，不用反复登录。

为什么单独做一个：
  - **登录是风控权重最高的动作**，必须尽量少做
  - 登录态可以跨机器复制（.browser_profile 目录整体拷走即可）
  - 采集脚本保持干净，遇到没登录时提示你跑这个脚本

用法：
    .venv/bin/python temu_login.py                    # 打开浏览器，登录完按回车退出
    .venv/bin/python temu_login.py --profile /tmp/p   # 指定 profile 目录
    .venv/bin/python temu_login.py --proxy http://u:p@h:port

登录完会输出：
    ✅ 登录成功（检测到 token）
    profile: /path/to/.browser_profile
    接下来直接跑采集即可，不用再登录
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

BASE = "https://www.temu.com"
ROOT = Path(__file__).parent


def _proxy_args(proxy: str):
    if not proxy:
        return [], None
    m = re.match(r"^(?:https?://)?(?:([^:@/]+):([^@/]*)@)?([^:/]+):(\d+)$", proxy)
    if not m:
        return [], None
    user, pwd, host, port = m.groups()
    server = f"http://{host}:{port}"
    if user:
        return [f"--proxy-server=http://{user}:{pwd}@{host}:{port}"], server
    return [f"--proxy-server={server}"], server


def check_login(ctx) -> bool:
    """检查是否已登录：看有没有账号相关 cookie / token"""
    names = {c["name"] for c in ctx.cookies()}
    logged = any(n in names for n in
                 ("sessionid", "temu_token", "login_token", "_token",
                  "user_token", "auth_token", "passportToken", "msToken"))
    # 再看 passport 接口
    try:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        r = page.evaluate("""async () => {
          try {
            const res = await fetch('/api/passport/token/touch', {method:'POST',
              credentials:'include',
              headers:{'Content-Type':'application/json;charset=UTF-8'}, body:'{}'});
            const t = await res.text();
            let code=null, ok=false;
            try { const j=JSON.parse(t); code=j.error_code; ok=!!(j.result&&j.result.token); } catch(e){}
            return {code:code, ok:ok, head:t.slice(0,90)};
          } catch(e){ return {err:String(e)}; }
        }""")
        if r.get("ok"):
            return True
        if r.get("code") == 1000000 and "token" not in str(r.get("head", "")).lower():
            pass
    except Exception:
        pass
    return logged


def main():
    ap = argparse.ArgumentParser(description="Temu 登录助手")
    ap.add_argument("--profile", default=os.environ.get(
        "TEMU_PROFILE", str(ROOT / ".browser_profile")))
    ap.add_argument("--proxy", default=os.environ.get("TEMU_PROXY", ""))
    ap.add_argument("--url", default=f"{BASE}/", help="登录页地址")
    ap.add_argument("--wait", type=int, default=600, help="最长等待秒数")
    args = ap.parse_args()

    prof = Path(args.profile)
    prof.parent.mkdir(parents=True, exist_ok=True)
    proxy_args, _ = _proxy_args(args.proxy)

    from playwright.sync_api import sync_playwright

    print("""
╔══════════════════════════════════════════════════════════╗
║  Temu 登录助手                                           ║
╠══════════════════════════════════════════════════════════╣
║  浏览器窗口会弹出来，请在里面完成登录                   ║
║  （账号密码 + 可能有的点选验证码）                        ║
║                                                          ║
║  登录完成后回到这里按回车，登录态会保存                 ║
║  profile: %-46s ║
╚══════════════════════════════════════════════════════════╝
""" % str(prof)[:46])

    pw = sync_playwright().start()
    try:
        ctx = pw.chromium.launch_persistent_context(
            str(prof), headless=False, channel="chrome",
            viewport={"width": 1400, "height": 900}, locale="en-US",
            timezone_id="America/New_York",
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
            args=["--disable-blink-features=AutomationControlled"] + proxy_args,
            ignore_default_args=["--enable-automation"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)

        # 已登录？
        if check_login(ctx):
            print("✅ 检测到已有登录态，无需重新登录")
            ctx.close()
            return

        print("\n⏳ 请在浏览器窗口完成登录…（最多等 %d 秒）\n" % args.wait)
        t0 = time.time()
        while time.time() - t0 < args.wait:
            try:
                page.wait_for_timeout(2000)
                if check_login(ctx):
                    print("\n✅ 登录成功！")
                    break
            except Exception:
                pass
            # 每 15 秒提示一次
            if int(time.time() - t0) % 15 == 0:
                print(f"   等待中… {int(time.time()-t0)}s  当前页面: {page.url[:60]}")
        else:
            print("\n⏰ 等待超时。登录态仍会保存，可以直接回车尝试采集。")

        print("\n按回车关闭浏览器并保存登录态…")
        try:
            input()
        except EOFError:
            pass
        ctx.close()
    finally:
        try: pw.stop()
        except Exception: pass

    # 校验
    print(f"\nprofile 已保存：{prof}")
    print(f"接下来直接跑采集即可：")
    print(f"  .venv/bin/python collectors.py temu_browser \"关键词\" 80")
    print(f"（如果换机器，把整个 {prof.name}/ 目录拷过去即可复用登录态）")


if __name__ == "__main__":
    main()
