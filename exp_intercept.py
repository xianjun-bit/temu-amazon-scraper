#!/usr/bin/env python3
"""
技术验证：拦截页面自己的 API 响应 —— 这条路登录后能不能拿到数据？

思路：不去猜参数、不去伪造 anti-token，而是让页面自己去发请求
（它会带正确的签名和 cookie），我们只监听 response。

验证三件事：
  1. 未登录时，页面自己发的 search 请求返回什么错误码
  2. 页面自己发的 goods_detail 请求返回什么
  3. 拦截器能不能稳定拿到 JSON
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "https://www.temu.com"
KEY = "laundry bag"
Q = (f"search_key={KEY.replace(' ', '%20')}&search_method=shade&refer_page_el_sn=200010"
     f"&srch_enter_source=top_search_entrance_10005&refer_page_name=home"
     f"&refer_page_sn=10005&filter_items=1%3A1")

caught = []

with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        "/tmp/exp_intercept", headless=True, channel="chrome",
        viewport={"width": 1500, "height": 950}, locale="en-US",
        timezone_id="America/New_York",
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        args=["--disable-blink-features=AutomationControlled"])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    def on_resp(res):
        u = res.url
        if "/api/" not in u:
            return
        if not any(k in u for k in ("search", "goods_detail", "goods_list", "opt_list")):
            return
        try:
            ct = (res.headers or {}).get("content-type", "")
            if "json" not in ct:
                return
            body = res.text()
        except Exception:
            return
        info = {"url": u, "status": res.status, "len": len(body)}
        try:
            j = json.loads(body)
            info["code"] = j.get("error_code")
            info["success"] = j.get("success")
            res_data = (j.get("result") or {})
            data = res_data.get("data") or {}
            gl = data.get("goodsList") or []
            info["goods_count"] = len(gl)
            if gl:
                info["sample_keys"] = list(gl[0].keys())[:22]
                info["sample_title"] = str(gl[0].get("title") or gl[0].get("goodsName") or "")[:60]
                # 详情字段探测
                g = gl[0]
                info["has_bullets"] = bool(g.get("bulletDesc") or g.get("goodsProperty")
                                          or g.get("featureDesc") or g.get("sellingPoint"))
                info["gallery"] = len(g.get("goodsGallery") or g.get("imageList") or [])
                info["sales"] = g.get("salesTip") or g.get("soldCount") or g.get("goodsSales")
        except Exception as e:
            info["parse_err"] = str(e)[:60]
        caught.append(info)

    page.on("response", on_resp)

    print(">>> 导航到搜索页（未登录）")
    page.goto(f"{BASE}/search_result.html?{Q}", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(16000)
    print("    当前 URL:", page.url[:110])
    print("    跳登录?", "/login" in page.url)

    print("\n>>> 捕获到的相关 API 响应:")
    for c in caught:
        print(f"  [{c['status']}] {c['url'].split('temu.com')[-1][:74]}")
        print(f"       code={c.get('code')} success={c.get('success')} goods={c.get('goods_count')} len={c['len']}")
        if c.get("sample_title"):
            print(f"       样例: {c['sample_title']}")
            print(f"       字段: {c.get('sample_keys')}")
            print(f"       有五点={c.get('has_bullets')} 图集={c.get('gallery')} 销量={c.get('sales')}")

    ctx.close()
