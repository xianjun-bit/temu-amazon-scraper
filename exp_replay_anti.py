#!/usr/bin/env python3
"""
决定性实验：能不能重放页面自己的 anti-content 头？

背景发现：
  - 我之前用 page.evaluate 里的原生 fetch() 调 /poppy/v1/search
  - 但 anti-content 是**页面的 axios 封装**加的，原生 fetch 绕过它 -> 根本没带签名
  - 而页面自己发的请求**是带 anti-content 的**（已抓到过）

所以真正要验证的是：
  A. 拿页面自己的 anti-content 头 + 我的 body -> 能不能过？
  B. 能不能直接调用页面的 axios 实例？
  C. 页面自己发 search 请求时，URL/body 长什么样？

如果 A 能过 -> 根本不需要登录！只需要复用签名头。
"""
import json, time
from playwright.sync_api import sync_playwright

BASE = "https://www.temu.com"
KEY = "laundry bag"
LISTID = "69426b1cc6dd4a499b2c56b3ce0e2389"

captured_headers = []

with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        "/tmp/exp_replay", headless=True, channel="chrome",
        viewport={"width": 1500, "height": 950}, locale="en-US",
        timezone_id="America/New_York",
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        args=["--disable-blink-features=AutomationControlled"])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    def on_req(req):
        if "/api/" in req.url and req.url.endswith(tuple([])) is False:
            h = req.headers
            if "anti-content" in h:
                captured_headers.append({"url": req.url, "headers": dict(h),
                                         "method": req.method, "post": req.post_data})
    page.on("request", on_req)

    print(">>> 打开首页，抓带 anti-content 的请求")
    page.goto(BASE + "/", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(12000)
    print(f"    抓到 {len(captured_headers)} 个带 anti-content 的请求")
    for c in captured_headers[:3]:
        ac = c["headers"].get("anti-content", "")
        print(f"    {c['method']} {c['url'].split('temu.com')[-1][:60]}  anti-content 长度={len(ac)}")
        if c["post"]:
            print(f"       post={c['post'][:150]}")

    if not captured_headers:
        print("❌ 没抓到 anti-content")
    else:
        anti = captured_headers[0]["headers"]["anti-content"]
        ref_headers = captured_headers[0]["headers"]

        JS = """async (a) => {
          try {
            const res = await fetch(a.url, {method:'POST', credentials:'include',
              headers: a.headers, body: JSON.stringify(a.body)});
            const t = await res.text();
            let code=null, n=0, sample='';
            try { const j=JSON.parse(t); code=j.error_code;
                  const gl=((j.result||{}).data||{}).goodsList||[]; n=gl.length;
                  if(gl.length) sample=String(gl[0].title||gl[0].goodsName||'').slice(0,52);
            } catch(e){}
            return {status:res.status, code:code, goods:n, sample:sample, head:t.slice(0,120)};
          } catch(e){ return {err:String(e)}; }
        }"""

        body = {"scene": "search", "pageSn": 10009, "offset": 0, "listId": LISTID,
                "pageSize": 120, "query": KEY, "filterItems": "",
                "searchMethod": "user", "disableCorrect": False}

        print("\n=== A) 重放 anti-content 头 + 我的 body ===")
        h = {"Content-Type": "application/json;charset=UTF-8",
             "Accept": "application/json, text/plain, */*",
             "anti-content": anti,
             "Referer": ref_headers.get("referer", BASE + "/"),
             "Origin": BASE,
             "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-origin"}
        r = page.evaluate(JS, {"url": "/api/poppy/v1/search?scene=search", "headers": h, "body": body})
        flag = "🎉" if r.get("goods") else ("  " if r.get("status") == 200 else "❌")
        print(f"  {flag} 重放签名 -> {r.get('status')} err={r.get('code')} goods={r.get('goods')}")
        print(f"     {r.get('sample','') or r.get('head','')[:110]}")

        print("\n=== B) 调页面自己的 axios 实例 ===")
        r2 = page.evaluate("""async (b) => {
          try {
            let ax = window.axios;
            if (!ax) {
              // 找 webpack 里的 axios
              for (const k in window) { if (k==='axios') ax = window[k]; }
            }
            if (!ax) return {err:'no axios on window'};
            const res = await ax.post('/api/poppy/v1/search?scene=search', b,
              {headers:{'Content-Type':'application/json;charset=UTF-8'}});
            const j = res.data;
            const gl=((j.result||{}).data||{}).goodsList||[];
            return {code:j.error_code, goods:gl.length,
                    sample: gl.length? String(gl[0].title||gl[0].goodsName||'').slice(0,52):'',
                    head: JSON.stringify(j).slice(0,120)};
          } catch(e){ return {err:String(e).slice(0,150)}; }
        }""", body)
        print(f"  {r2}")

        print("\n=== C) 用页面自己的 axios.get + params ===")
        r3 = page.evaluate("""async (b) => {
          try {
            const res = await window.axios.get('/api/poppy/v1/search', {params:b});
            const j = res.data;
            const gl=((j.result||{}).data||{}).goodsList||[];
            return {code:j.error_code, goods:gl.length, head:JSON.stringify(j).slice(0,140)};
          } catch(e){ return {err:String(e).slice(0,150)}; }
        }""", body)
        print(f"  {r3}")

    ctx.close()
