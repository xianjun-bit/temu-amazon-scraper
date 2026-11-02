#!/usr/bin/env python3
"""
collectors.py —— 统一的采集接口（供 CLI 与 Web 服务共用）

每个采集器都是 **生成器**：逐条 yield 标准化后的记录，
这样 Web 端可以实时把进度推给浏览器，而不是等全部跑完才看到结果。

标准化记录结构：
  {
    platform, id, title, price, currency, rating, review_count, sold,
    brand, seller, in_stock, images[], image_count, bullets[], bullet_count,
    specs{}, variations{}, url, error
  }
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).parent
OUT = ROOT / "output"
OUT_AMZ = OUT / "amazon"
OUT_TEMU = OUT / "temu"

BASE = "https://www.temu.com"
AMZ_BASE = "https://www.amazon.com"

MUA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


# ══════════════════════════════════════════════════════════════
# 通用工具
# ══════════════════════════════════════════════════════════════
def _norm(platform, rec_id, title, price=None, currency="", rating=None,
          review_count=None, sold=None, brand=None, seller=None, in_stock=None,
          images=None, bullets=None, specs=None, variations=None, url="", error=""):
    return {
        "platform": platform, "id": rec_id or "", "title": title or "",
        "price": price, "currency": currency, "rating": rating,
        "review_count": review_count, "sold": sold,
        "brand": brand, "seller": seller, "in_stock": in_stock,
        "images": images or [], "image_count": len(images or []),
        "bullets": bullets or [], "bullet_count": len(bullets or []),
        "specs": specs or {}, "variations": variations or {},
        "url": url, "error": error,
    }


def _save_images(urls, folder: Path, concurrency=12):
    """并发下载图片。返回 {远程URL: 本地文件名} 映射"""
    from curl_cffi import requests
    from concurrent.futures import ThreadPoolExecutor as TE, as_completed as AC

    folder.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, str] = {}

    def one(u):
        try:
            r = requests.get(u, impersonate="chrome124", timeout=30)
            ct = r.headers.get("content-type", "")
            if r.status_code == 200 and len(r.content) > 1200:
                ext = ".png" if "png" in ct else (".webp" if "webp" in ct else ".jpg")
                fn = hashlib.md5(u.encode()).hexdigest()[:16] + ext
                (folder / fn).write_bytes(r.content)
                return u, fn
        except Exception:
            pass
        return u, None

    with TE(max_workers=concurrency) as ex:
        for u, fn in ex.map(one, urls):
            if fn:
                mapping[u] = fn
    return mapping


# ══════════════════════════════════════════════════════════════
# Amazon
# ══════════════════════════════════════════════════════════════
def _amz_repo():
    return Path(os.environ.get("AMZ_REPO", str(ROOT / "vendor" / "amazon-scraper")))


def scrape_amazon(keyword: str, limit: int = 20, download_images: bool = True,
                  workers: int = 6):
    """Amazon 采集：关键词 -> 详情全字段 -> 图片。逐条 yield。"""
    repo = _amz_repo()
    if not repo.exists():
        raise RuntimeError(
            f"未找到 amazon-scraper：{repo}\n请先跑 `python3 setup.py` 安装依赖")

    sys.path.insert(0, str(repo))
    # 清代理（WorkBuddy 内部代理会导致 502）
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        os.environ.pop(k, None)

    from amazon import products as amz_products, search as amz_search  # noqa: E402

    # 1) 搜索（翻页直到够 limit；遇限流自动退避重试）
    items, seen, empty_streak = [], set(), 0
    blocked_msg = ""
    for p in range(1, 13):
        d = None
        for attempt in range(4):          # 限流时退避重试
            try:
                d = amz_search.search(keyword, country="US", page=p)
                break
            except TypeError:
                try:
                    d = amz_search.search(keyword, page=p)
                    break
                except Exception as e:
                    d = None; blocked_msg = str(e)[:200]; time.sleep(3 + attempt * 4)
            except Exception as e:
                # AmazonBlocked 等：退避后重试
                blocked_msg = str(e)[:200]
                if "Blocked" in type(e).__name__ or "503" in blocked_msg:
                    time.sleep(8 + attempt * 8)     # 8s, 16s, 24s
                    continue
                break
        if d is None:
            if items:
                break                          # 已经抓到一些了，够用
            raise RuntimeError(
                f"Amazon 搜索失败：{blocked_msg}\n"
                f"提示：Amazon 对高频请求会临时限流（503），等几分钟再试，"
                f"或调低数量 / 减少并发。")
        res = (d or {}).get("results") or []
        if not res:
            empty_streak += 1
            if empty_streak >= 3:
                break
            continue
        empty_streak = 0
        for it in res:
            a = it.get("asin")
            if a and a not in seen:
                seen.add(a); items.append(it)
        if len(items) >= limit:
            break
    items = items[:limit]
    if not items:
        raise RuntimeError(f"Amazon 搜索无结果：{keyword}"
                           + (f"（{blocked_msg}）" if blocked_msg else ""))

    yield {"_phase": "search", "message": f"搜索到 {len(items)} 个商品，开始抓详情"}

    # 2) 详情（并发）
    def _one(it):
        a = it.get("asin")
        try:
            return a, amz_products.details(a)
        except Exception as e:
            return a, {"asin": a, "error": str(e)[:120]}

    fetched = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_one, it): it for it in items}
        done = 0
        for f in as_completed(futs):
            it = futs[f]
            try:
                a, d = f.result()
                fetched[a] = d
            except Exception as e:
                fetched[it.get("asin")] = {"asin": it.get("asin"), "error": str(e)[:120]}
            done += 1
            yield {"_phase": "progress", "message": f"详情 {done}/{len(items)}",
                   "current": done, "total": len(items)}

    # 3) 逐条输出（先给数据，图片随后在后台补 —— 用户不用干等）
    for it in items:
        asin = it.get("asin")
        d = fetched.get(asin) or {}
        imgs = []
        for im in (d.get("images") or []):
            if isinstance(im, dict):
                u = im.get("link") or im.get("large")
                if u: imgs.append(u)
            elif isinstance(im, str):
                imgs.append(im)
        imgs = list(dict.fromkeys(imgs))

        bullets = d.get("bullets") or []
        if isinstance(bullets, str): bullets = [bullets]
        pr = d.get("price") or {}
        rt = d.get("rating") or {}
        ov = d.get("overview") or {}

        rec = _norm(
            platform="amazon", rec_id=asin,
            title=d.get("title") or it.get("title") or "",
            price=pr.get("amount") if isinstance(pr, dict) else pr,
            currency=pr.get("currency") if isinstance(pr, dict) else "USD",
            rating=rt.get("average") if isinstance(rt, dict) else None,
            review_count=rt.get("count") if isinstance(rt, dict) else None,
            sold=d.get("bought_past_month"),
            brand=(d.get("brand") or {}).get("name") if isinstance(d.get("brand"), dict) else None,
            seller=((d.get("buybox") or {}).get("seller") or {}).get("name")
                   if isinstance(d.get("buybox"), dict) else None,
            in_stock=(d.get("availability") or {}).get("is_in_stock")
                      if isinstance(d.get("availability"), dict) else None,
            images=imgs, bullets=bullets,
            specs=ov or (d.get("details") or {}),
            variations=d.get("variations") or {},
            url=f"{AMZ_BASE}/dp/{asin}",
            error=d.get("error", "") or ("残缺响应(缺图/评分)" if d.get("_partial") else ""),
        )
        yield {"_phase": "item", "record": rec}




# ══════════════════════════════════════════════════════════════
# Temu · api 模式（免登录，只拿列表页字段）
# ══════════════════════════════════════════════════════════════
def scrape_temu_api(limit: int = 40, download_images: bool = True):
    """Temu 免登录模式：首页 goods_list API。逐条 yield。"""
    from playwright.sync_api import sync_playwright
    from curl_cffi import requests

    prof = ROOT / ".browser_profile"
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(prof), headless=True, channel="chrome",
            viewport={"width": 1500, "height": 950}, locale="en-US",
            timezone_id="America/New_York", user_agent=MUA,
            args=["--disable-blink-features=AutomationControlled"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(BASE + "/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(10000)

        r = page.evaluate("""async () => {
          const res = await fetch('/api/alexa/homepage/goods_list', {method:'POST',
            credentials:'include', headers:{'Content-Type':'application/json;charset=UTF-8'},
            body: JSON.stringify({offset:0,count:120,list_id:'',opt_id:null,listId:'',
                                  scene:'home',page_list_id:'',extend_fields:{}})});
          return {status: res.status, text: await res.text()};
        }""")
        try:
            j = json.loads(r["text"])
        except Exception:
            raise RuntimeError(f"Temu API 返回异常: {str(r)[:200]}")

        items = []
        def walk(o):
            if isinstance(o, dict):
                if "goods_id" in o and "price_info" in o: items.append(o)
                else:
                    for v in o.values(): walk(v)
            elif isinstance(o, list):
                for v in o: walk(v)
        walk(j)
        ctx.close()

    items = items[:limit]
    yield {"_phase": "search", "message": f"取到 {len(items)} 个商品"}

    for it in items:
        gi = it.get("image") or {}
        pi = it.get("price_info") or {}
        gid = str(it.get("goods_id", ""))
        title = re.sub(r"<[^>]+>", "", it.get("title") or "").strip()
        imgs = [gi["url"]] if isinstance(gi, dict) and gi.get("url") else []
        link = it.get("link_url") or ""
        if link.startswith("goods.html"):
            link = BASE + "/" + link
        rec = _norm(platform="temu", rec_id=gid, title=title,
                    price=pi.get("price_str") if isinstance(pi, dict) else None,
                    currency=pi.get("currency") if isinstance(pi, dict) else "",
                    images=imgs, url=link or f"{BASE}/goods.html?goods_id={gid}")
        yield {"_phase": "item", "record": rec}


# ══════════════════════════════════════════════════════════════
# Temu · browser 模式（需登录/过验证码，抓全字段）
# ══════════════════════════════════════════════════════════════
def scrape_temu_browser(keyword: str, limit: int = 80, download_images: bool = True,
                        headless: bool = False):
    """Temu 浏览器模式：走真实页面，登录后抓关键词搜索结果 + 详情。逐条 yield。

    ⚠️ 需在有图形界面的机器上跑；headless=True 时遇验证码会跳过该商品。
    """
    from playwright.sync_api import sync_playwright
    from curl_cffi import requests

    # 入口参数：让服务端不强制跳登录
    Q = (f"search_key={quote(keyword)}&search_method=shade&refer_page_el_sn=200010"
         f"&srch_enter_source=top_search_entrance_10005&refer_page_name=home"
         f"&refer_page_sn=10005&filter_items=1%3A1")

    prof = ROOT / ".browser_profile"
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(prof), headless=headless, channel="chrome",
            viewport={"width": 1500, "height": 950}, locale="en-US",
            timezone_id="America/New_York", user_agent=MUA,
            args=["--disable-blink-features=AutomationControlled"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        yield {"_phase": "search", "message": f"打开搜索页：{keyword}"}
        page.goto(f"{BASE}/search_result.html?{Q}", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(12000)

        if "/login" in page.url:
            yield {"_phase": "login",
                   "message": "需要登录：请在浏览器窗口完成登录/验证（headed 模式）",
                   "need_login": True}
            if headless:
                ctx.close()
                raise RuntimeError("需要登录态。请用有图形界面的机器跑 headed 模式完成登录，"
                                   "或改用 --mode apify")
            input("   登录完成后回车继续: ")

        # 滚动收集商品链接
        urls = []
        for _ in range(14):
            links = page.evaluate(
                "() => [...new Set([...document.querySelectorAll(\"a[href*='-g-']\")]"
                ".map(e => e.href.split('?')[0]))])")
            urls = links
            if len(urls) >= limit: break
            page.mouse.wheel(0, 2500); page.wait_for_timeout(1600)
        urls = urls[:limit]
        yield {"_phase": "search", "message": f"搜索到 {len(urls)} 个商品"}

        for i, u in enumerate(urls, 1):
            yield {"_phase": "progress", "message": f"抓详情 {i}/{len(urls)}",
                   "current": i, "total": len(urls)}
            try:
                page.goto(u, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(4000)
                if "/login" in page.url:
                    yield {"_phase": "item", "record": _norm(
                        platform="temu", rec_id="", title="", url=u,
                        error="被重定向到登录页")}
                    continue
                txt = page.evaluate("document.body.innerText") or ""
                title = (page.evaluate(
                    "() => { const e=document.querySelector('h1,[class*=goodsTitle]');"
                    "return e?e.innerText.trim():''; }") or "").strip()
                ptxt = (page.evaluate(
                    "() => { const els=[...document.querySelectorAll('[class*=price]')]"
                    ".map(e=>e.innerText.trim()).filter(t=>t&&/\\\\d/.test(t)); return els[0]||''; }") or "")
                bullets = (page.evaluate("""() => {
                    for (const s of ['[class*=goodsProperty]','[class*=property]','[class*=desc]',
                                     '[class*=bullet]','[class*=feature]','[class*=highlight]']) {
                      const e=document.querySelector(s); if(!e) continue;
                      const it=[...e.querySelectorAll('li,p,div')].map(x=>(x.innerText||'').trim())
                        .filter(t=>t.length>12&&t.length<300&&!/\\n\\n/.test(t));
                      if(it.length>=3) return [...new Set(it)];
                    }
                    return []; }""") or [])[:12]
                imgs = (page.evaluate("""() => {
                    const o=[]; document.querySelectorAll('img').forEach(i=>{
                      const s=i.currentSrc||i.src||''; if(!/kwcdn/.test(s))return;
                      if(/upload_aimg\\/(basic_pic|account|login|m-image|message|web|pc|dawn|temu)/.test(s))return;
                      if(/\\/w\\d+\\//.test(s))return; o.push(s); });
                    return [...new Set(o)]; }""") or [])[:30]
                gid = (re.search(r"-g-(\d{10,})", u) or re.search(r"goods_id=(\d+)", u))
                rec = _norm(platform="temu", rec_id=gid.group(1) if gid else "",
                            title=title, price=re.sub(r"\s+", " ", ptxt),
                            currency="$" if "$" in ptxt else "",
                            images=imgs, bullets=bullets, url=u)
                yield {"_phase": "item", "record": rec}
            except Exception as e:
                yield {"_phase": "item", "record": _norm(platform="temu", rec_id="",
                                                         url=u, error=str(e)[:100])}
            time.sleep(1.0 + random_delay())

        if download_images:
            yield {"_phase": "images", "message": "开始下载图片…"}
        ctx.close()


def random_delay():
    import random
    return random.random()


# ══════════════════════════════════════════════════════════════
# Temu · apify 模式（托管服务，无需代理/登录）
# ══════════════════════════════════════════════════════════════
def scrape_temu_apify(keyword: str, limit: int = 80, token: str = "",
                       actor: str = "crw~temu-products-scraper",
                       download_images: bool = True):
    """Apify 托管采集。逐条 yield。"""
    from curl_cffi import requests

    if not token:
        raise RuntimeError("需要 Apify token（export APIFY_TOKEN=xxx）")

    url = (f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
           f"?token={token}&format=json")
    payloads = [
        {"searchKeyword": keyword, "maxItems": limit, "sortBy": "relevance"},
        {"searchKeyword": keyword, "maxItems": limit},
        {"query": keyword, "maxItems": limit},
        {"keyword": keyword, "maxItems": limit},
    ]
    items = []
    last_err = ""
    for pl in payloads:
        try:
            r = requests.post(url, json=pl, impersonate="chrome124", timeout=300)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict): data = data.get("items", [])
                if data:
                    items = data
                    break
                last_err = f"返回 0 条（输入形态 {list(pl)[0]} 可能不对）"
            else:
                last_err = f"HTTP {r.status_code}: {r.text[:150]}"
        except Exception as e:
            last_err = str(e)[:150]
    if not items:
        raise RuntimeError(f"Apify 调用失败：{last_err}")

    yield {"_phase": "search", "message": f"Apify 取到 {len(items)} 条"}
    for it in items[:limit]:
        gi = it.get("image") or it.get("images") or {}
        if isinstance(gi, list): gi = gi[0] if gi else {}
        if isinstance(gi, dict):
            imgs = [gi.get("url") or gi.get("link") or gi.get("image")] if (
                gi.get("url") or gi.get("link") or gi.get("image")) else []
        else:
            imgs = []
        for key in ("gallery", "imageUrls", "images"):
            v = it.get(key)
            if isinstance(v, list):
                imgs += [x if isinstance(x, str) else (x.get("url") or x.get("link"))
                         for x in v if x]
        imgs = [x for x in dict.fromkeys(imgs) if x][:30]
        rec = _norm(
            platform="temu", rec_id=str(it.get("goods_id") or it.get("goodsId") or ""),
            title=re.sub(r"<[^>]+>", "", it.get("title") or it.get("goodsName") or ""),
            price=it.get("price") or it.get("price_str") or it.get("salePrice"),
            currency=it.get("currency") or "USD",
            rating=it.get("rating") or it.get("goodsScore"),
            review_count=it.get("reviewCount") or it.get("reviewsCount"),
            sold=it.get("soldCount") or it.get("sold") or it.get("salesTip"),
            brand=it.get("brand") or it.get("brandName"),
            images=imgs,
            bullets=[b for b in (it.get("bullets") or it.get("features") or
                                 it.get("description") or []) if b][:12]
                   if isinstance(it.get("bullets") or it.get("features") or
                                it.get("description") or [], list) else [],
            specs=it.get("goodsProperty") or it.get("specs") or {},
            url=it.get("url") or it.get("link_url") or "",
        )
        yield {"_phase": "item", "record": rec}

    # 图片（数据已推送，后台补图）
    if download_images:
        yield {"_phase": "images", "message": "开始下载图片…"}
        total = 0
        for it in items:
            gi = it.get("image") or {}
            if isinstance(gi, dict) and gi.get("url"):
                m = _save_images([gi["url"]], OUT_TEMU / "images" / str(it.get("goods_id")))
                total += len(m)
        yield {"_phase": "images_done", "message": f"图片下载 {total} 张"}

    # 图片（数据已推送，这里在后台补图）
    if download_images:
        yield {"_phase": "images", "message": "开始下载图片…"}
        total = 0
        for it in items:
            asin = it.get("asin")
            d = fetched.get(asin) or {}
            imgs = []
            for im in (d.get("images") or []):
                if isinstance(im, dict):
                    u = im.get("link") or im.get("large")
                    if u: imgs.append(u)
                elif isinstance(im, str):
                    imgs.append(im)
            imgs = list(dict.fromkeys(imgs))
            if imgs:
                m = _save_images(imgs, OUT_AMZ / "images" / (asin or "x"))
                total += len(m)
        yield {"_phase": "images_done", "message": f"图片下载 {total} 张"}


# ══════════════════════════════════════════════════════════════
# 分发
# ══════════════════════════════════════════════════════════════
COLLECTORS = {
    "amazon": scrape_amazon,
    "temu_api": scrape_temu_api,
    "temu_browser": scrape_temu_browser,
    "temu_apify": scrape_temu_apify,
}


def run(platform: str, keyword: str = "", limit: int = 20, **kw):
    """按平台名分发，返回生成器"""
    fn = COLLECTORS.get(platform)
    if not fn:
        raise ValueError(f"未知平台: {platform}（可选 {list(COLLECTORS)}）")
    if platform == "amazon":
        return fn(keyword, limit=limit, **kw)
    if platform == "temu_api":
        return fn(limit=limit, **kw)
    return fn(keyword, limit=limit, **kw)


if __name__ == "__main__":
    # CLI 用法： python3 collectors.py amazon "laundry bag" 20
    p = sys.argv[1] if len(sys.argv) > 1 else "amazon"
    kw = sys.argv[2] if len(sys.argv) > 2 else "laundry bag"
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    for ev in run(p, kw, n):
        if ev.get("_phase") == "item":
            r = ev["record"]
            print(f"  {r['id']:<14} {r['title'][:44]:<46} {str(r['price'])[:8]:<9} "
                  f"图{r['image_count']} 五点{r['bullet_count']}")
        else:
            print("  ·", ev.get("message", ev))
