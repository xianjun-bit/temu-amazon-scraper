#!/usr/bin/env python3
"""
最后一轮：剩下 3 个可能相关的端点
  /api/poppy/v1/mall_home_recommend
  /api/promotion/open/recommend/promotion/goods/list
  /api/poppy/v1/opt_list   （筛选器列表 —— 配合 opt_id 可能能按类目过滤）
"""
import json, re, sys
from pathlib import Path
from playwright.sync_api import sync_playwright
from curl_cffi import requests as cr

BASE = "https://www.temu.com"
KEY = "laundry bag"

# 从 bundle 挖 queryGoodsList 的 url + opt_list 的参数
cs = cr.Session()
cs.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                    "Accept-Language": "en-US,en;q=0.9"})
for name, url in [
    ("1561", "https://static.kwcdn.com/m-assets/assets/modernjs/1561_b110d62e3e0215246aee.js"),
    ("1504", "https://static.kwcdn.com/m-assets/assets/modernjs/1504_b961db8985c73b0c156a.js"),
    ("8226", "https://static.kwcdn.com/m-assets/assets/modernjs/8226_549eb80a5d99f1217887.js"),
]:
    js = cs.get(url, impersonate="chrome124", timeout=40).text
    for kw in ["queryGoodsList(", "mall_home_recommend", "promotion/goods/list", "opt_list"]:
        i = js.find(kw)
        if i > 0:
            print(f"--- {name} [{kw}]")
            print("   ", js[max(0,i-260):i+420].replace("\n", " ")[:640])
            print()

with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        "/tmp/exp_last", headless=True, channel="chrome",
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
        const r = await fetch(a.url, {method:a.method||'POST', credentials:'include',
          headers:{'Content-Type':'application/json;charset=UTF-8',
                   'Accept':'application/json, text/plain, */*'},
          body: JSON.stringify(a.body)});
        const t = await r.text();
        let code=null, titles=[];
        try { const j=JSON.parse(t); code=j.error_code;
              const gl=(j.result&&j.result.data&&j.result.data.goodsList)||[];
              gl.slice(0,3).forEach(x=>titles.push(String(x.title||x.goodsName||'').replace(/<[^>]+>/g,'').slice(0,40)));
        } catch(e){}
        return {status:r.status, len:t.length, code:code,
                goods:(t.match(/goods_id/g)||[]).length, titles:titles, head:t.slice(0,110)};
      } catch(e){ return {err:String(e)}; }
    }"""

    def probe(label, url, body, method="POST"):
        r = page.evaluate(JS, {"url":url,"body":body,"method":method})
        flag = "🎉" if r.get("goods") else ("  " if r.get("status")==200 else "❌")
        print(f"  {flag} {label:<44} {r.get('status')} err={r.get('code')} goods={r.get('goods')}")
        for t in r.get("titles", []): print(f"        · {t}")
        if not r.get("goods"): print(f"        {r.get('head','')[:100]}")
        return r

    print("\n=== 剩余端点实测 ===")
    probe("mall_home_recommend", "/api/poppy/v1/mall_home_recommend",
          {"scene":"home","pageSn":10032,"listId":"a"*32,"offset":0,"pageSize":40})
    probe("promotion/goods/list", "/api/promotion/open/recommend/promotion/goods/list",
          {"scene":"home","pageSn":10032,"listId":"a"*32,"offset":0,"pageSize":40})
    probe("opt_list scene=search", "/api/poppy/v1/opt_list",
          {"scene":"search","pageSn":10009,"listId":"a"*32,"offset":0,"pageSize":20})
    probe("opt_list scene=home", "/api/poppy/v1/opt_list",
          {"scene":"home","pageSn":10032,"listId":"a"*32,"offset":0,"page_size":-1,
           "mainGoodsId":"601100218100590"})
    probe("opt_list 带 search_key", "/api/poppy/v1/opt_list",
          {"scene":"search","pageSn":10009,"listId":"a"*32,"offset":0,"pageSize":20,
           "search_key":KEY,"query":KEY})

    ctx.close()
