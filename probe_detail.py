#!/usr/bin/env python3
"""
针对单个 SKU 深挖详情数据。
新思路：
 1) 商品卡片 API 返回的原始 goods 对象里，可能已含 gallery/desc 字段（我之前只取了 4 个字段就扔了）
 2) goods_list 传 scene=goods + goods_id 试试
 3) /api/alexa/homepage/goods_list 的 goods 对象全字段 dump
"""
import json, re, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

PROF = Path("/tmp/detail_profile")
GID = "601100218100590"

JS = """async (a) => {
  try {
    const res = await fetch(a.url, {method:'POST', credentials:'include',
      headers:{'Content-Type':'application/json;charset=UTF-8'},
      body: JSON.stringify(a.body)});
    const t = await res.text();
    return {status: res.status, len: t.length, text: t.slice(0,500000)};
  } catch(e){ return {err: String(e)}; }
}"""

with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        str(PROF), headless=True, channel="chrome",
        viewport={"width":1500,"height":950}, locale="en-US", timezone_id="America/New_York",
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        args=["--disable-blink-features=AutomationControlled"])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://www.temu.com/", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(9000)

    # ---- 1) 把 goods_list 里的商品对象全字段 dump ----
    print("=== 1) 首页 goods_list 单条商品的完整字段 ===")
    r = page.evaluate(JS, {"url":"/api/alexa/homepage/goods_list",
        "body":{"offset":0,"count":5,"list_id":"","opt_id":None,"listId":"",
                "scene":"home","page_list_id":"","extend_fields":{}}})
    j = json.loads(r["text"])
    goods = []
    def walk(o):
        if isinstance(o, dict):
            if "goods_id" in o and "price_info" in o: goods.append(o)
            else:
                for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    walk(j)
    if goods:
        g = goods[0]
        print(f"  字段总数: {len(g)}")
        for k, v in g.items():
            sv = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
            print(f"    {k:<24} {sv[:150]}")

    # ---- 2) goods_list 支持按 goods_id 取详情吗 ----
    print("\n=== 2) goods_list 传 scene=goods / goods_id ===")
    TRIES = [
        ("scene=goods", {"offset":0,"count":10,"list_id":"","opt_id":None,"listId":"",
                          "scene":"goods","page_list_id":"","extend_fields":{},
                          "goods_id":GID,"goods_ids":[GID]}),
        ("scene=home+goods_id", {"offset":0,"count":10,"list_id":"","opt_id":None,"listId":"",
                                 "scene":"home","page_list_id":"","extend_fields":{"goods_id":GID}}),
        ("goods_ids 数组", {"offset":0,"count":10,"list_id":"","opt_id":None,"listId":"",
                            "scene":"home","page_list_id":"","extend_fields":{},
                            "goods_ids":[GID],"goods_id_list":[GID]}),
        ("scene=detail", {"offset":0,"count":10,"list_id":"","opt_id":None,"listId":"",
                          "scene":"detail","page_list_id":"","extend_fields":{"goods_id":GID}}),
    ]
    for name, body in TRIES:
        rr = page.evaluate(JS, {"url":"/api/alexa/homepage/goods_list","body":body})
        tt = rr.get("text","")
        gid_hit = GID in tt
        print(f"  {name:<20} {rr.get('status')} len={rr.get('len')} 含目标SKU={gid_hit} gallery={tt.count('gallery')} desc={tt.count('desc')}")
        if gid_hit:
            Path("/tmp/DETAIL_goodslist.json").write_text(tt)
            print("     💾 /tmp/DETAIL_goodslist.json")
            # 找该 SKU 的对象
            def find_target(o, out=None):
                if out is None: out=[]
                if isinstance(o, dict):
                    if str(o.get("goods_id")) == GID: out.append(o)
                    for v in o.values(): find_target(v, out)
                elif isinstance(o, list):
                    for v in o: find_target(v, out)
                return out
            tg = find_target(j)
            print("     找到目标对象数:", len(tg))
            if tg:
                print("     全字段:")
                for k,v in tg[0].items():
                    sv = json.dumps(v, ensure_ascii=False) if not isinstance(v,str) else v
                    print(f"       {k:<22} {sv[:200]}")

    # ---- 3) 试试用户原始链接里的 top_gallery_url 参数形式 ----
    print("\n=== 3) 带 top_gallery_url 的商品页 ===")
    SHARE = ("https://www.temu.com/sturdy-washing-machine-bag-for-shoes-of--kind-features-a-zipper-closure-"
             "and-a-soft-protective-interior-perfect-for-sneakers-and-day-footwear-laundry-wash-bag-"
             f"ideal-for-mothers-day-laundry-bags-g-{GID}.html"
             "?top_gallery_url=https%3A%2F%2Fimg.kwcdn.com%2Fproduct%2Fopen%2F0189276f3ee74de4a50705d3663a4a85-goods.jpeg"
             "&spec_gallery_id=649901&refer_page_sn=10032")
    rr = page.evaluate("""async (u) => {
      const res = await fetch(u, {credentials:'include'});
      const t = await res.text();
      return {status: res.status, len: t.length, text: t.slice(0, 500000)};
    }""", SHARE)
    t3 = rr.get("text","")
    print(f"  status={rr.get('status')} len={rr.get('len')}")
    for kw in ["goods_id","goodsName","gallery","goodsGallery","goodsProperty","priceInfo",
               "bullet","desc","-g-"]:
        c = t3.count(kw)
        if c: print(f"    {kw}: {c}")
    if "goodsGallery" in t3 or '"goods"' in t3:
        Path("/tmp/DETAIL_share.html").write_text(t3)
        print("  💾 /tmp/DETAIL_share.html")
        # 抽 rawData
        i = t3.find("window.rawData=")
        if i > 0:
            print("  rawData 上下文:", t3[i:i+200])
    ctx.close()
