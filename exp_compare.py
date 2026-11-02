#!/usr/bin/env python3
"""
决定性验证：goods_list 传的参数到底有没有作用？
做法：同一接口，同一浏览器会话，两次调用（基线 vs 带关键词），
     对比返回的 goods_id 集合和标题。
"""
import json, re, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "https://www.temu.com"

with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        "/tmp/exp_cmp", headless=True, channel="chrome",
        viewport={"width":1500,"height":950}, locale="en-US",
        timezone_id="America/New_York",
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        args=["--disable-blink-features=AutomationControlled"])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(BASE + "/", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(10000)

    JS = """async (a) => {
      const r = await fetch('/api/alexa/homepage/goods_list', {method:'POST',
        credentials:'include',
        headers:{'Content-Type':'application/json;charset=UTF-8',
                 'Accept':'application/json, text/plain, */*'},
        body: JSON.stringify(a.body)});
      const t = await r.text();
      const out = [];
      const walk = o => {
        if (Array.isArray(o)) o.forEach(walk);
        else if (o && typeof o === 'object') {
          if (o.goods_id && (o.price_info || o.title)) out.push(
            {id: String(o.goods_id), title: String(o.title||'').replace(/<[^>]+>/g,'').slice(0,46),
             price: (o.price_info||{}).price_str});
          else Object.values(o).forEach(walk);
        }
      };
      try { walk(JSON.parse(t)); } catch(e) { return {err:String(e), raw:t.slice(0,200)}; }
      return {items: out};
    }"""

    base = {"offset":0,"count":120,"list_id":"","opt_id":None,"listId":"",
            "scene":"home","page_list_id":"","extend_fields":{}}

    def call(body):
        r = page.evaluate(JS, {"body": body})
        return r.get("items", [])

    print("=== 1) 基线（无关键词参数）===")
    a = call(base)
    print(f"  {len(a)} 个商品，前 3 个:")
    for x in a[:3]: print(f"    {x['id']:<16} {x['title'][:44]:<46} {x['price']}")

    print("\n=== 2) 传 search_key='laundry bag'（在 extend_fields 里）===")
    b = call({**base, "extend_fields": {"search_key": "laundry bag"}})
    print(f"  {len(b)} 个商品，前 3 个:")
    for x in b[:3]: print(f"    {x['id']:<16} {x['title'][:44]:<46} {x['price']}")

    print("\n=== 3) 传 keyword 顶层 ===")
    c = call({**base, "keyword": "laundry bag"})
    print(f"  {len(c)} 个商品，前 3 个:")
    for x in c[:3]: print(f"    {x['id']:<16} {x['title'][:44]:<46} {x['price']}")

    print("\n=== 4) 传 scene='search' ===")
    d = call({**base, "scene": "search"})
    print(f"  {len(d)} 个商品，前 3 个:")
    for x in d[:3]: print(f"    {x['id']:<16} {x['title'][:44]:<46} {x['price']}")

    ids_a = {x["id"] for x in a}
    for label, other in [("search_key", b), ("keyword", c), ("scene=search", d)]:
        ids_o = {x["id"] for x in other}
        overlap = len(ids_a & ids_o)
        print(f"\n  基线 vs {label}: 重叠 {overlap}/{len(ids_a)} "
              f"({'完全相同 → 参数被忽略' if overlap == len(ids_a) else '不同 → 参数生效！'})")

    # 再看标题里有没有出现关键词
    print("\n=== 5) 标题里是否出现关键词 'laundry' / 'bag' ===")
    for label, other in [("基线", a), ("search_key", b), ("keyword", c), ("scene=search", d)]:
        hit = sum(1 for x in other if "laundry" in x["title"].lower() or "bag" in x["title"].lower())
        print(f"  {label:<14} {hit}/{len(other)} 条标题含 laundry/bag")

    ctx.close()
