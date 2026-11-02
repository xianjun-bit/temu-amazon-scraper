#!/usr/bin/env python3
"""
1) 类目页走什么端点？免登录吗？
2) /api/seo/homepage_rec_goods_list 是不是也一样（SEO 推荐）
"""
import json, re, sys
from concurrent.futures import ThreadPoolExecutor
from curl_cffi import requests

BASE = "https://www.temu.com"
s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                  "Accept-Language": "en-US,en;q=0.9"})

# ── 1) 类目页 ──
print("=== 类目页探测 ===")
for url in [f"{BASE}/category-shoes.html",
            f"{BASE}/category-home-supplies.html",
            f"{BASE}/category-luggage.html",
            f"{BASE}/c-10007.html"]:
    try:
        r = s.get(url, impersonate="chrome124", timeout=25)
        t = r.text
        print(f"  {url.replace(BASE,''):<38} {r.status_code} len={len(t):<8} "
              f"rawData={'window.rawData' in t}")
        if "window.rawData" in t:
            # 看类目页 bundle
            us = sorted(set(re.findall(r'"(https://static\.kwcdn\.com/[^"]+\.js)"', t)))
            print(f"      {len(us)} bundle")
    except Exception as e:
        print(f"  {url}: ERR {str(e)[:40]}")

# ── 2) 搜类目页用的 goods 端点 ──
print("\n=== 找类目/推荐相关的端点 ===")
html = s.get(BASE + "/", impersonate="chrome124", timeout=30).text
urls = sorted(set(re.findall(r'"(https://static\.kwcdn\.com/[^"]+\.js)"', html)))

def get(u):
    try: return u, s.get(u, impersonate="chrome124", timeout=40).text
    except Exception: return u, ""

allp = {}
with ThreadPoolExecutor(max_workers=10) as ex:
    for u, js in ex.map(get, urls):
        if len(js) < 3000: continue
        ps = set(re.findall(r'["\'`](/api/[a-zA-Z0-9_\-/{}\.]{3,80})["\'`]', js))
        ps = {p for p in ps if re.search(r"goods|rec|category|feed|channel", p, re.I)}
        if ps: allp[u.split("/")[-1]] = sorted(ps)

for name, ps in allp.items():
    print(f"\n--- {name}")
    for p in ps[:14]: print("   ", p)

# ── 3) seo 版推荐端点试一下 ──
print("\n=== /api/seo/homepage_rec_goods_list 是否可免登录 ===")
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        "/tmp/exp_seo", headless=True, channel="chrome",
        viewport={"width":1500,"height":950}, locale="en-US",
        timezone_id="America/New_York",
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        args=["--disable-blink-features=AutomationControlled"])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(BASE + "/", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(10000)
    for url, body in [
        ("/api/seo/homepage_rec_goods_list",
         {"offset":0,"count":120,"list_id":"","opt_id":None,"listId":"",
          "scene":"home","page_list_id":"","extend_fields":{}}),
        ("/api/alexa/homepage/goods_list",
         {"offset":0,"count":120,"list_id":"","opt_id":None,"listId":"",
          "scene":"home","page_list_id":"","extend_fields":{}}),
    ]:
        r = page.evaluate("""async (a) => {
          try { const res = await fetch(a.url, {method:'POST', credentials:'include',
            headers:{'Content-Type':'application/json;charset=UTF-8'},
            body: JSON.stringify(a.body)});
            const t = await res.text();
            return {status:res.status, len:t.length,
                    goods:(t.match(/goods_id/g)||[]).length, head:t.slice(0,110)};
          } catch(e){ return {err:String(e)}; } }""", {"url":url,"body":body})
        print(f"  {url.replace('/api/',''):<40} {r.get('status')} len={r.get('len')} goods={r.get('goods')} {r.get('head','')[:60]}")
    ctx.close()
