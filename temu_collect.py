#!/usr/bin/env python3
"""
Temu 选品数据采集器 —— 生产版（基于 2026-10-26 实测结论）

实测结论（Temu 反爬 4 道门）：
  门1 JS Challenge  → curl_cffi (TLS 指纹伪装) 100% 突破（实测 26/26）
  门2 SSR 空壳      → 商品数据只在 XHR，需真实浏览器执行 JS
  门3 IP 风控       → 直连 API 一律 429 (error_code 406008)
  门4 登录墙/验证码 → region=211 (美国) 强制登录；headless 触发点选验证码

已验证可用的路径：
  ✅ 浏览器内 fetch 首页 goods_list API  -> 返回真实商品列表（含图片/价格/标题/goods_id）
  ✅ curl_cffi 拿 SSR 页（不过 challenge） -> 页面骨架 + listId 等参数
  ✅ img.kwcdn.com 图片 CDN 无鉴权可直接下载
  ✅ 搜索页在 curl_cffi 层加 refer_page_sn=10005 入口参数不跳登录
  ❌ 搜索/商品页在浏览器层仍被服务端强制登录（需住宅代理或 Apify）

三种运行模式：
  1) --mode apify    : 用 Apify token 跑（最省事，$0.01/条，最稳）
  2) --mode browser  : 本机 headed 浏览器 + 人工过一次验证码（需 GUI）
  3) --mode api      : 仅用浏览器内 fetch 首页类目 API 拿商品列表（免费，但非关键词搜索）
"""
import argparse, csv, hashlib, json, os, random, re, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from curl_cffi import requests

BASE = "https://www.temu.com"

# Temu challenge 对 TLS 指纹是动态判定的（同一指纹上轮能过下轮可能失效），
# 所以请求时轮换指纹，而不是写死一个。
_FP_CYCLE = ["chrome131", "chrome124", "chrome120", "chrome119",
             "safari17_0", "safari15_3", "edge101"]
_fp_idx = 0


def _pick_imp():
    global _fp_idx
    imp = _FP_CYCLE[_fp_idx % len(_FP_CYCLE)]
    _fp_idx += 1
    return imp



ROOT = Path(__file__).parent
OUT = ROOT / "output"
PROFILE = ROOT / ".browser_profile"

MUA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# 入口参数（让服务端不强制跳登录；来源：Temu-Item-Scraper 的历史可用 URL 形态）
ENTRY_Q = ("&search_method=shade&refer_page_el_sn=200010"
           "&srch_enter_source=top_search_entrance_10005&refer_page_name=home"
           "&refer_page_sn=10005&filter_items=1%3A1")

STEALTH = r"""
(() => {
  try { Object.defineProperty(Navigator.prototype,'webdriver',{get:()=>undefined,configurable:true}); } catch(e){}
  try { if(!window.chrome) window.chrome={runtime:{},loadTimes:()=>{},csi:()=>{},app:{isInstalled:false}}; } catch(e){}
  try { Object.defineProperty(Navigator.prototype,'languages',{get:()=>['en-US','en'],configurable:true}); } catch(e){}
  try {
    const mk=(n,a)=>{const o=a.map(x=>({name:x,filename:x,description:x,length:1}));
      Object.setPrototypeOf(o,PluginArray.prototype);o.item=i=>o[i];o.namedItem=n=>o.find(x=>x.name===n);o.refresh=()=>{};return o;};
    Object.defineProperty(Navigator.prototype,'plugins',{get:()=>mk('Plugin',
      ['PDF Viewer','Chrome PDF Viewer','Chromium PDF Viewer','Microsoft Edge PDF Viewer','WebKit built-in PDF']),configurable:true});
  } catch(e){}
  try { const o=window.navigator.permissions.query;
    window.navigator.permissions.query=(p)=>(p&&p.name==='notifications'
      ?Promise.resolve({state:Notification.permission,onchange:null}):o.call(window.navigator.permissions,p)); } catch(e){}
  try { const g=WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter=function(p){
      if(p===37445)return'Intel Inc.'; if(p===37446)return'Intel Iris OpenGL Engine';
      return g.apply(this,[p]); }; } catch(e){}
  try { Object.defineProperty(Navigator.prototype,'hardwareConcurrency',{get:()=>8,configurable:true}); } catch(e){}
  try { Object.defineProperty(Navigator.prototype,'deviceMemory',{get:()=>8,configurable:true}); } catch(e){}
})();
"""


# ══════════════════════════════════════════════════════════════
# 模式 1：Apify（推荐）
# ══════════════════════════════════════════════════════════════
def run_apify(keyword, limit, token, actor="crw~temu-products-scraper"):
    """用 Apify actor 抓 —— 服务端代理池已养熟，绕开本地 IP 风控"""
    print(f">>> Apify actor: {actor}")
    url = (f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
           f"?token={token}&format=json")
    # 不同 actor 的输入字段不同，按常见几种依次尝试
    payloads = [
        {"searchKeyword": keyword, "maxItems": limit, "sortBy": "relevance"},
        {"searchKeyword": keyword, "maxItems": limit},
        {"query": keyword, "maxItems": limit},
        {"keyword": keyword, "maxItems": limit, "startUrls": []},
        {"searchKeyword": keyword, "maxItems": limit, "startPageNum": 1, "sortBy": "relevance"},
    ]
    for i, pl in enumerate(payloads):
        print(f"    尝试输入形态 #{i}: {json.dumps(pl, ensure_ascii=False)}")
        try:
            r = requests.post(url, json=pl, impersonate=_pick_imp(), timeout=300)
            if r.status_code == 200:
                items = r.json()
                if isinstance(items, dict):
                    items = items.get("items", [])
                if items:
                    print(f"    ✅ 成功! {len(items)} 条")
                    return items
                print(f"    返回 0 条（可能输入字段不对）: {r.text[:200]}")
            else:
                print(f"    HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            print(f"    ERR {str(e)[:90]}")
    return []


# ══════════════════════════════════════════════════════════════
# 模式 2：本机浏览器（headed + 人工过验证码）
# ══════════════════════════════════════════════════════════════
def run_browser(keyword, limit, urls_file=None, headless=False):
    """本机浏览器采集。headed 模式下若弹验证码，人工过一次即可。"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(PROFILE), headless=headless, channel="chrome",
            viewport={"width":1500,"height":950}, locale="en-US",
            timezone_id="America/New_York", user_agent=MUA,
            args=["--disable-blink-features=AutomationControlled","--no-sandbox"])
        ctx.add_cookies([{"name":"region","value":"37","domain":".temu.com","path":"/"},
                         {"name":"currency","value":"CAD","domain":".temu.com","path":"/"},
                         {"name":"language","value":"en","domain":".temu.com","path":"/"}])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.add_init_script(STEALTH)

        # 1) 拿商品 URL 列表
        urls = []
        if urls_file:
            urls = [l.strip() for l in Path(urls_file).read_text().splitlines() if l.strip()]
        else:
            print(f">>> 浏览器搜索: {keyword}")
            page.goto(f"{BASE}/search_result.html?search_key={keyword}{ENTRY_Q}",
                      wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(12000)
            if "/login" in page.url and not headless:
                print("   🔒 跳登录页 —— 请在浏览器窗口完成登录/验证，然后回车继续")
                input("   回车继续: ")
            for _ in range(10):
                links = page.evaluate(
                    "() => [...new Set([...document.querySelectorAll(\"a[href*='-g-']\")].map(e=>e.href.split('?')[0]))]")
                urls = links
                print(f"   滚动后商品数: {len(urls)}")
                if len(urls) >= limit: break
                page.mouse.wheel(0, 2500); page.wait_for_timeout(1600)

        # 2) 逐个抓
        rows = []
        for i, u in enumerate(urls[:limit], 1):
            print(f"  [{i}/{min(len(urls),limit)}] {u[:76]}")
            rec = collect_one(page, u)
            rows.append(rec)
            print(f"      {'✅' if rec['title'] else '❌'} {(rec['title'] or '')[:50]} | "
                  f"{rec['price'][:20]} | 图{len(rec['images'])} | 五点{len(rec['bullet_points'])}")
            if rec.get("error"): print(f"      ⚠️ {rec['error'][:70]}")
            time.sleep(1.0 + random.random())
        ctx.close()
        return rows


def collect_one(page, url):
    rec = {"url":url,"goods_id":"","title":"","price":"","currency":"$","sold":"",
           "rating":"","images":[],"bullet_points":[],"props":{},"scraped_at":"","error":""}
    m = re.search(r"-g-(\d{10,})", url) or re.search(r"goods_id=(\d+)", url)
    if m: rec["goods_id"] = m.group(1)

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        rec["error"] = f"goto {str(e)[:60]}"; return rec

    deadline = time.time() + 50
    body = ""
    while time.time() < deadline:
        page.wait_for_timeout(1500)
        body = page.evaluate("document.body.innerText") or ""
        if re.search(r"Slide to complete|Security Verification|puzzle|Verify", body, re.I):
            print("      🔒 验证码 —— 请手动完成")
            while True:
                page.wait_for_timeout(2500)
                body = page.evaluate("document.body.innerText") or ""
                if not re.search(r"Slide to complete|Security Verification|puzzle|Verify", body, re.I):
                    print("      ✅ 验证通过"); break
                if re.search(r"\$\d+\.\d{2}", body): break
        if body and len(body) > 400 and re.search(r"\$\d+\.\d{2}", body): break
    page.wait_for_timeout(2500)

    if "/login" in page.url:
        rec["error"] = "被重定向到登录页（需要住宅代理或登录态）"; return rec

    rec["title"] = (page.evaluate(
        "() => { const e=document.querySelector('h1,[class*=goodsTitle],[class*=title]'); return e?e.innerText.trim():''; }") or "").strip()
    ptxt = page.evaluate("""() => { const els=[...document.querySelectorAll('[class*=price]')]
        .map(e=>e.innerText.trim()).filter(t=>t&&/\\d/.test(t)); return els[0]||''; }""") or ""
    rec["price"] = re.sub(r"\s+", " ", ptxt)
    rec["currency"] = "$" if "$" in ptxt else ("€" if "€" in ptxt else ("£" if "£" in ptxt else "$"))
    rec["sold"] = (page.evaluate("""() => { const m=document.body.innerText.match(/([\\d.,]+\\s*[KkMm]?\\+?)\\s*sold/i); return m?m[0]:''; }""") or "")
    rec["bullet_points"] = (page.evaluate("""() => {
        for (const s of ['[class*=goodsProperty]','[class*=property]','[class*=desc]',
                         '[class*=bullet]','[class*=feature]','[class*=highlight]','[class*=specification]']) {
          const e=document.querySelector(s); if(!e) continue;
          const items=[...e.querySelectorAll('li,p,div')].map(x=>(x.innerText||'').trim())
            .filter(t=>t.length>12&&t.length<300&&!/\\n\\n/.test(t));
          if(items.length>=3) return [...new Set(items)];
        }
        return document.body.innerText.split('\\n').map(x=>x.trim())
          .filter(x=>/^\\d+[.、)]\\s|^(?:✔|✅|•)/.test(x)&&x.length>12&&x.length<300);
    }""") or [])[:12]
    rec["images"] = (page.evaluate("""() => {
        const out=[]; document.querySelectorAll('img').forEach(i=>{
          const s=i.currentSrc||i.src||''; if(!/kwcdn/.test(s))return;
          if(/upload_aimg\\/(basic_pic|account|login|m-image|message|web|pc|dawn|temu)/.test(s))return;
          if(/\\/w\\d+\\//.test(s))return; out.push(s); });
        return [...new Set(out)];
    }""") or [])[:30]
    rec["props"] = (page.evaluate("""() => { const o={};
        document.querySelectorAll('[class*=property],[class*=spec] [class*=item]').forEach(e=>{
          const m=(e.innerText||'').trim().match(/^([^:\\n]{1,40})[:：]\\s*(.{1,80})$/);
          if(m) o[m[1].trim()]=m[2].trim(); }); return o; }""") or {})
    rec["scraped_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    return rec


# ══════════════════════════════════════════════════════════════
# 模式 3：仅浏览器内 fetch 首页 API（免费，无需代理）
# ══════════════════════════════════════════════════════════════
def run_api_only(limit):
    """首页类目 API —— 已验证可用，能拿到真实商品列表（非关键词搜索）"""
    from playwright.sync_api import sync_playwright
    print(">>> 浏览器内 fetch 首页 goods_list API（已验证可用）")
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(PROFILE), headless=True, channel="chrome",
            viewport={"width":1500,"height":950}, locale="en-US",
            user_agent=MUA, args=["--disable-blink-features=AutomationControlled"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.add_init_script(STEALTH)
        page.goto(f"{BASE}/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(10000)
        r = page.evaluate("""async () => {
          const res = await fetch('/api/alexa/homepage/goods_list', {method:'POST',
            credentials:'include', headers:{'Content-Type':'application/json;charset=UTF-8'},
            body: JSON.stringify({offset:0,count:120,list_id:'',opt_id:null,listId:'',
                                  scene:'home',page_list_id:'',extend_fields:{}})});
          return {status: res.status, text: (await res.text())};
        }""")
        print("   status:", r.get("status"), "len:", len(r.get("text","")))
        items = []
        try:
            j = json.loads(r["text"])
            def walk(o):
                if isinstance(o, dict):
                    if "goods_id" in o and "price_info" in o: items.append(o)
                    else:
                        for v in o.values(): walk(v)
                elif isinstance(o, list):
                    for v in o: walk(v)
            walk(j)
        except Exception as e:
            print("   parse err", e)
        print(f"   ✅ 抓到 {len(items)} 个商品")
        ctx.close()
    return items


# ══════════════════════════════════════════════════════════════
def normalize(items):
    """统一成标准字段"""
    rows = []
    for it in items:
        if not isinstance(it, dict): continue
        gi = it.get("image") or {}
        pi = it.get("price_info") or {}
        title = it.get("title") or ""
        title = re.sub(r"<[^>]+>", "", title).strip() if isinstance(title, str) else ""
        rows.append({
            "goods_id": it.get("goods_id", ""),
            "title": title,
            "price": pi.get("price_str") or pi.get("price", "") if isinstance(pi, dict) else "",
            "currency": pi.get("currency", "") if isinstance(pi, dict) else "",
            "sold": it.get("sold_cnt") or it.get("sales") or "",
            "rating": it.get("goods_score") or "",
            "images": [gi.get("url", "")] if isinstance(gi, dict) and gi.get("url") else [],
            "bullet_points": [],
            "props": {},
            "url": it.get("link_url") or (f"{BASE}/goods.html?goods_id={it.get('goods_id','')}"),
            "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "error": "",
        })
    return rows


def export(rows):
    OUT.mkdir(exist_ok=True)
    cp = OUT / "products.csv"
    with open(cp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["goods_id","title","price","currency","sold","rating","image_count",
                    "image_urls","bullet_points","props","url","scraped_at","error"])
        for r in rows:
            w.writerow([r.get("goods_id",""), r.get("title",""), r.get("price",""),
                        r.get("currency",""), r.get("sold",""), r.get("rating",""),
                        len(r.get("images",[])), " | ".join(r.get("images",[])),
                        " | ".join(r.get("bullet_points",[])),
                        json.dumps(r.get("props",{}), ensure_ascii=False),
                        r.get("url",""), r.get("scraped_at",""), r.get("error","")])
    (OUT / "products.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    ok = sum(1 for r in rows if r.get("title"))
    print(f"\n✅ 导出 {len(rows)} 条（有标题 {ok}）-> {cp}")
    print(f"   JSON -> {OUT/'products.json'}")
    return cp


def download_images(rows, outdir):
    outdir = Path(outdir)

    def one(u, d):
        try:
            r = requests.get(u, impersonate=_pick_imp(), timeout=30)
            ct = r.headers.get("content-type","")
            if r.status_code == 200 and len(r.content) > 1200:
                ext = ".png" if "png" in ct else (".webp" if "webp" in ct else ".jpg")
                (d / (hashlib.md5(u.encode()).hexdigest()[:16] + ext)).write_bytes(r.content)
                return 1
        except Exception: pass
        return 0
    total = 0
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = []
        for r in rows:
            gid = str(r.get("goods_id") or "unknown")
            d = outdir / gid
            d.mkdir(parents=True, exist_ok=True)
            for u in r.get("images", []):
                futs.append(ex.submit(one, u, d))
        for f in as_completed(futs): total += bool(f.result())
    print(f"   图片下载完成: {total} 张 -> {outdir}")


def main():
    ap = argparse.ArgumentParser(description="Temu 选品数据采集器")
    ap.add_argument("--mode", choices=["apify","browser","api"], default="browser")
    ap.add_argument("--keyword", default="laundry bag")
    ap.add_argument("--limit", type=int, default=80)
    ap.add_argument("--token", default=os.environ.get("APIFY_TOKEN",""))
    ap.add_argument("--actor", default="crw~temu-products-scraper")
    ap.add_argument("--urls", help="URL 文件（browser 模式）")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--images", action="store_true")
    a = ap.parse_args()

    if a.mode == "apify":
        if not a.token:
            print("❌ 需要 Apify token：export APIFY_TOKEN=xxx  或 --token xxx")
            print("   免费注册 https://apify.com （新账号有 $5 额度，80 条约 $0.8）")
            sys.exit(1)
        items = run_apify(a.keyword, a.limit, a.token, a.actor)
        rows = normalize(items)
    elif a.mode == "api":
        rows = normalize(run_api_only(a.limit))
    else:
        rows = run_browser(a.keyword, a.limit, a.urls, a.headless)

    export(rows)
    if a.images and rows:
        download_images(rows, OUT / "images")


if __name__ == "__main__":
    main()
