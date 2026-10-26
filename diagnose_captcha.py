#!/usr/bin/env python3
"""诊断：headless 下 Temu 商品页到底遇到什么验证 + 页面到底渲染出没有"""
import json, re, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

GID = "601100218100590"
URL = f"https://www.temu.com/goods.html?goods_id={GID}"
SHOT = Path("/tmp/captcha_diag"); SHOT.mkdir(exist_ok=True)
PROF = Path("/tmp/diag_profile")

CAP = {
    "slide": r"Slide to complete|slide to",
    "click": r"click on the type of|Security Verification",
    "puzzle": r"puzzle",
}

def classify(txt):
    hits = [k for k, p in CAP.items() if re.search(p, txt, re.I)]
    return hits or []

with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        str(PROF), headless=True, channel="chrome",
        viewport={"width": 1500, "height": 950}, locale="en-US",
        timezone_id="America/New_York",
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    xhrs = []
    page.on("response", lambda r: xhrs.append((r.url, r.status)) if "captcha" in r.url or "challenge" in r.url else None)

    print(">>> goto")
    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    for i in range(12):
        page.wait_for_timeout(2500)
        txt = page.evaluate("document.body.innerText") or ""
        caps = classify(txt)
        imgs = page.evaluate("() => [...document.images].filter(i=>/kwcdn/.test(i.src)).length")
        price = re.findall(r"\$\s?\d+\.\d{2}", txt)
        print(f"  t={(i+1)*2.5:>4}s len={len(txt):>5} kwImg={imgs:<4} price={price[:2]} cap={caps} url={page.url[:52]}")
        if caps:
            page.screenshot(path=str(SHOT / f"cap_{caps[0]}.png"), full_page=False)
            print(f"  📸 截图 -> {SHOT}/cap_{caps[0]}.png")
            # 抓验证区域文本
            print("  验证区文本:", " | ".join(txt.split("\n")[:8])[:300])
            # 找验证 iframe / 容器
            fr = page.evaluate("""() => [...document.querySelectorAll('iframe')].map(f=>f.src||f.title)""")
            print("  iframes:", fr[:5])
            break
        if price:
            print("  ✅ 出现价格！")
            page.screenshot(path=str(SHOT / "ok.png"))
            break

    print("\n>>> captcha 相关请求:")
    for u, s in xhrs[:10]:
        print(f"   {s} {u[:120]}")
    print("\n>>> 最终 cookies:", [c["name"] for c in ctx.cookies()])
    ctx.close()
