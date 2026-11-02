#!/usr/bin/env python3
"""
决定性实验：浏览器内试 goods_list 的各种参数组合
目标：看有没有办法让免登录接口按关键词/类目返回，而不是首页推荐位
"""
import json, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "https://www.temu.com"
KEY = "laundry bag"

# 先用 curl_cffi 拿搜索页的 listId（SSR 里唯一可用的搜索相关参数）
from curl_cffi import requests as cr
cs = cr.Session()
cs.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                    "Accept-Language": "en-US,en;q=0.9", "Referer": BASE + "/"})
Q = ("search_key=laundry%20bag&search_method=shade&refer_page_el_sn=200010"
     "&srch_enter_source=top_search_entrance_10005&refer_page_name=home"
     "&refer_page_sn=10005&filter_items=1%3A1")
html = cs.get(f"{BASE}/search_result.html?{Q}", impersonate="chrome124", timeout=30).text
sys.path.insert(0, str(Path(__file__).parent))
from temu_parse import get_rawdata
raw = get_rawdata(html)
st = (raw or {}).get("store", {})
slist = st.get("listId")
print(f"搜索页 listId = {slist}")

with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        "/tmp/exp_why_prof", headless=True, channel="chrome",
        viewport={"width":1500,"height":950}, locale="en-US",
        timezone_id="America/New_York",
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        args=["--disable-blink-features=AutomationControlled"])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(BASE + "/", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(10000)

    JS = """async (a) => {
      try {
        const r = await fetch(a.url, {method:'POST', credentials:'include',
          headers:{'Content-Type':'application/json;charset=UTF-8',
                   'Accept':'application/json, text/plain, */*'},
          body: JSON.stringify(a.body)});
        const t = await r.text();
        let code=null, titles=[];
        try { const j=JSON.parse(t); code=j.error_code;
              const gl=(j.result&&j.result.data&&j.result.data.goodsList)||[];
              gl.slice(0,3).forEach(x=>titles.push((x.title||x.goodsName||'').slice(0,42)));
        } catch(e){}
        return {status:r.status, len:t.length, code:code, n:(t.match(/goods_id/g)||[]).length,
                titles:titles, head:t.slice(0,120)};
      } catch(e){ return {err:String(e)}; }
    }"""

    def probe(label, body, url="/api/alexa/homepage/goods_list"):
        r = page.evaluate(JS, {"url": url, "body": body})
        flag = "🎉" if r.get("n") else ("  " if r.get("status") == 200 else "❌")
        print(f"  {flag} {label:<46} {r.get('status')} err={r.get('code')} goods={r.get('n')}")
        for t in r.get("titles", []): print(f"        · {t}")
        if not r.get("n") and r.get("status") != 200:
            print(f"        {r.get('head','')[:100]}")
        return r

    base = {"offset":0,"count":120,"list_id":"","opt_id":None,"listId":"",
            "scene":"home","page_list_id":"","extend_fields":{}}

    print("\n=== 1) 基线（已知可用）===")
    probe("基线 scene=home", base)

    print("\n=== 2) 换 list_id（用搜索页 listId）===")
    probe("list_id=搜索页listId", {**base, "list_id": slist})
    probe("listId=搜索页listId", {**base, "listId": slist})

    print("\n=== 3) opt_id 各种值 ===")
    for oid in ["1", "10007", "0", slist]:
        probe(f"opt_id={oid[:14]}", {**base, "opt_id": oid})

    print("\n=== 4) 加关键词类参数 ===")
    for k, v in [("search_key", KEY), ("keyword", KEY), ("query", KEY),
                 ("goods_name", KEY), ("searchKey", KEY)]:
        probe(f"extend_fields+{k}", {**base, "extend_fields": {k: v}})
        probe(f"顶层 {k}", {**base, k: v})

    print("\n=== 5) scene 变体 + listId 组合 ===")
    for sc in ["search", "category", "goods_list", "recommend", "feed"]:
        probe(f"scene={sc}", {**base, "scene": sc})
    probe("scene=search + listId", {**base, "scene": "search", "listId": slist,
                                    "list_id": slist})

    print("\n=== 6) 试 /api/poppy/v1/opt_list（拿筛选器列表）===")
    probe("opt_list scene=search", {"scene":"search","pageSn":10009,"listId":slist,
                                     "offset":0,"pageSize":20},
          url="/api/poppy/v1/opt_list")

    ctx.close()
