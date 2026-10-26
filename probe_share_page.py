#!/usr/bin/env python3
"""
关键实验：带 top_gallery_url 的商品页，在浏览器里加载后读 store.goods
（服务端已识别该参数 -> 可能走的是「分享/SEO 渲染」路径，不需要登录）
"""
import json, re
from pathlib import Path
from playwright.sync_api import sync_playwright

PROF = Path("/tmp/sh_profile")
GID = "601100218100590"
SHARE = ("https://www.temu.com/sturdy-washing-machine-bag-for-shoes-of--kind-features-a-zipper-closure-"
         "and-a-soft-protective-interior-perfect-for-sneakers-and-day-footwear-laundry-wash-bag-"
         f"ideal-for-mothers-day-laundry-bags-g-{GID}.html"
         "?top_gallery_url=https%3A%2F%2Fimg.kwcdn.com%2Fproduct%2Fopen%2F0189276f3ee74de4a50705d3663a4a85-goods.jpeg"
         "&spec_gallery_id=649901&refer_page_sn=10032")

with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        str(PROF), headless=True, channel="chrome",
        viewport={"width":1500,"height":950}, locale="en-US", timezone_id="America/New_York",
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        args=["--disable-blink-features=AutomationControlled"])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    caught = []
    def on_resp(res):
        u = res.url
        if "temu.com" not in u or "/api/" not in u: return
        try:
            if "json" not in (res.headers or {}).get("content-type",""): return
            b = res.text()
        except Exception: return
        if b and len(b) > 150:
            caught.append({"url":u,"status":res.status,"len":len(b),
                           "post":res.request.post_data,"body":b})
    page.on("response", on_resp)

    # 先首页建会话
    page.goto("https://www.temu.com/", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(9000)

    # 用页面内 fetch 加载 share 页（避开跳转）
    print(">>> 页面内 fetch share 商品页")
    r = page.evaluate("""async (u) => {
      const res = await fetch(u, {credentials:'include'});
      const t = await res.text();
      return {status: res.status, len: t.length};
    }""", SHARE)
    print("   ", r)

    # 真实导航（带 referer 从首页来）
    print(">>> 导航到 share 商品页")
    caught.clear()
    page.goto(SHARE, wait_until="domcontentloaded", timeout=60000,
              referer="https://www.temu.com/")
    page.wait_for_timeout(16000)

    print("   url:", page.url[:110])
    print("   跳登录?", "/login" in page.url)
    txt = page.evaluate("document.body.innerText") or ""
    print("   文本长度:", len(txt))
    print("   前 400:", txt[:400].replace("\n", " | "))
    prices = re.findall(r"\$\s?\d+\.\d{2}", txt)
    print("   价格:", prices[:5])

    # store.goods
    st = page.evaluate("""() => {
      try {
        const s = window.rawData?.store || {};
        const g = s.goods || {};
        const out = {
          goodsKeys: Object.keys(g),
          goodsSize: JSON.stringify(g).length,
          galleryStore: Object.keys(s.galleryStore || {}),
          preloadFirstImgList: s.preloadFirstImgList || s.detailStore?.preloadFirstImgList,
          goodsProperty: s.goodsProperty || s.goodsStore?.goodsProperty,
        };
        out.goods = JSON.stringify(g).slice(0, 3000);
        return out;
      } catch(e){ return {err: String(e)}; }
    }""")
    print("\n   store:", json.dumps(st, ensure_ascii=False)[:1800])

    # 商品图片（DOM 里）
    imgs = page.evaluate("""() => [...new Set([...document.images]
        .map(i=>i.currentSrc||i.src).filter(s=>/img\\.kwcdn\\.com/.test(s)
        && !/upload_aimg/.test(s) && !/\\?imageView/.test(s)))]""")
    print("\n   DOM 商品图:", len(imgs))
    for u in imgs[:10]: print("     ", u[:120])

    print("\n   XHR:")
    for i,c in enumerate(caught):
        g = "🎉GOODS" if '"goods_id"' in c["body"] else ""
        print(f"   [{i}] {c['status']} {c['url'].split('temu.com')[-1][:70]} len={c['len']} {g}")
        if c["post"] and ("detail" in c["url"] or "goods" in c["url"]):
            print(f"        post={c['post'][:300]}")
        if g:
            Path("/tmp/SH_goods_xhr.json").write_text(json.dumps(
                [{"url":c["url"],"post":c["post"],"body":c["body"][:80000]} for c in caught],
                ensure_ascii=False, indent=1))
            print("        💾 /tmp/SH_goods_xhr.json")
    ctx.close()
