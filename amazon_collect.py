#!/usr/bin/env python3
"""
Amazon 全链路端到端验证：
  1) 关键词搜索 -> ASIN 列表 + 价格 + 评分 + 图片
  2) 逐个商品详情 -> 五点描述(bullets) + 全部附图 + 规格 + 变体
  3) 图片下载 + CSV/JSON 导出
依赖：本地 amazon-scraper 服务 (bottle, :8768)
"""
import csv, hashlib, json, os, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote

import urllib.request

PORT = int(os.environ.get("AMZ_PORT", "8771"))
BASE = f"http://127.0.0.1:{PORT}"
REPO = os.environ.get("AMZ_REPO", str(Path(__file__).parent / "vendor" / "amazon-scraper"))
OUT = Path(__file__).parent / "output_amazon"
KEYWORD = os.environ.get("AMZ_KEYWORD", "laundry bag")
LIMIT = int(os.environ.get("AMZ_LIMIT", "20"))

# 关键：清掉环境代理，否则 curl_cffi 会走 WorkBuddy 内部代理导致 502
_CLEAN_ENV = {k: v for k, v in os.environ.items()
              if k.lower() not in ("http_proxy", "https_proxy", "all_proxy")}


def start_server():
    """在同进程内起 bottle 服务（避免后台进程被回收）"""
    os.chdir(REPO)
    sys.path.insert(0, REPO)
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        os.environ.pop(k, None)
    import bottle
    import routes  # noqa: F401  挂载 21 个端点
    from cheroot import wsgi
    bottle.default_app().config["server"] = "cheroot"
    srv = wsgi.Server(("127.0.0.1", PORT), bottle.default_app(),
                      server_name="amz", numthreads=16)
    import threading
    t = threading.Thread(target=srv.start, daemon=True)
    t.start()
    time.sleep(2)
    return srv


def api(path, timeout=120):
    # 关键：必须绕过环境代理（urllib 默认读 HTTP_PROXY）
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(BASE + path, timeout=timeout) as r:
        return json.loads(r.read().decode())


def search(keyword, pages=1, per=48):
    items = []
    for p in range(1, pages + 1):
        u = f"/search?query={quote(keyword)}&country=US&page={p}"
        try:
            d = api(u)
        except Exception as e:
            print(f"  搜索页{p} 失败: {str(e)[:80]}")
            break
        res = d.get("results", [])
        print(f"  搜索页{p}: {len(res)} 条 (共{d.get('count')} 结果)")
        items += res
    return items


def details(asin, retries=3):
    """抓详情，失败自动重试（Amazon 偶发反爬）"""
    last = None
    for i in range(retries):
        try:
            d = api(f"/products/details?product={asin}", timeout=120)
            if d and d.get("title"):
                return d
            last = d
        except Exception as e:
            last = {"asin": asin, "error": str(e)[:120]}
        time.sleep(2 + i * 2)
    return last or {"asin": asin, "error": "unknown"}


def dl(url, folder):
    try:
        req = urllib.request.Request(url, headers={"User-Agent":
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=40) as r:
            data = r.read()
        if len(data) > 1200:
            ext = ".jpg"
            if b"\x89PNG" in data[:8]: ext = ".png"
            elif b"RIFF" in data[:4]: ext = ".webp"
            (folder / (hashlib.md5(url.encode()).hexdigest()[:16] + ext)).write_bytes(data)
            return 1
    except Exception:
        pass
    return 0


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print(f">>> 启动 amazon-scraper 服务 :{PORT}")
    srv = start_server()
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                f"{BASE}/health", timeout=15) as r:
            print(f">>> health: {r.status}")
    except Exception as e:
        print(f"❌ 服务启动失败: {str(e)[:100]}")
        return

    print(f">>> 搜索: {KEYWORD}")
    items = search(KEYWORD, pages=2)
    items = items[:LIMIT]
    print(f">>> 命中 {len(items)} 个商品，开始抓详情")

    rows = []
    for i, it in enumerate(items, 1):
        asin = it.get("asin")
        d = details(asin)
        # images: [{link, thumbnail, large, variant}] —— 取所有尺寸，主图用 link
        imgs, thumbs = [], []
        for im in (d.get("images") or []):
            if isinstance(im, dict):
                if im.get("link"): imgs.append(im["link"])
                elif im.get("large"): imgs.append(im["large"])
                if im.get("thumbnail"): thumbs.append(im["thumbnail"])
            elif isinstance(im, str):
                imgs.append(im)
        bullets = d.get("bullets") or []
        if isinstance(bullets, str): bullets = [bullets]
        pr = d.get("price") or {}
        rt = d.get("rating") or {}
        rows.append({
            "asin": asin,
            "title": d.get("title") or it.get("title") or "",
            "price": pr.get("amount") if isinstance(pr, dict) else pr,
            "list_price": pr.get("list_price") if isinstance(pr, dict) else None,
            "currency": pr.get("currency") if isinstance(pr, dict) else "USD",
            "rating": rt.get("average") if isinstance(rt, dict) else None,
            "review_count": rt.get("count") if isinstance(rt, dict) else None,
            "bought_past_month": d.get("bought_past_month"),
            "in_stock": (d.get("availability") or {}).get("is_in_stock") if isinstance(d.get("availability"), dict) else None,
            "brand": (d.get("brand") or {}).get("name") if isinstance(d.get("brand"), dict) else None,
            "seller": ((d.get("buybox") or {}).get("seller") or {}).get("name") if isinstance(d.get("buybox"), dict) else None,
            "image_count": len(imgs),
            "images": imgs,
            "bullet_count": len(bullets),
            "bullets": bullets,
            "overview": d.get("overview") or {},
            "details": d.get("details") or {},
            "variations": d.get("variations") or {},
            "categories": d.get("categories") or [],
            "bsr": d.get("best_sellers_rank") or [],
            "videos_count": d.get("videos_count"),
            "customers_say": (d.get("customers_say") or {}).get("summary") if isinstance(d.get("customers_say"), dict) else None,
            "url": f"https://www.amazon.com/dp/{asin}",
            "error": d.get("error", ""),
        })
        r = rows[-1]
        print(f"  [{i}/{len(items)}] {asin} {'✅' if r['title'] else '❌'} "
              f"{(r['title'] or '')[:44]} | ${r['price']} | 图{r['image_count']} | "
              f"五点{r['bullet_count']} | ★{r['rating']}")

    # 图片下载
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = []
        for r in rows:
            d = OUT / "images" / (r["asin"] or "x")
            d.mkdir(parents=True, exist_ok=True)
            for u in r["images"][:12]:
                futs.append(ex.submit(dl, u, d))
        n = sum(bool(f.result()) for f in as_completed(futs))
    print(f"\n>>> 图片下载 {n} 张")

    # 导出
    cp = OUT / "products.csv"
    with open(cp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["asin","title","price","list_price","currency","rating","review_count",
                    "bought_past_month","in_stock","brand","seller","image_count","image_urls",
                    "bullet_count","bullets","overview","details","variations","categories",
                    "videos_count","customers_say","url","error"])
        for r in rows:
            w.writerow([r["asin"], r["title"], r["price"], r["list_price"], r["currency"],
                        r["rating"], r["review_count"], r["bought_past_month"], r["in_stock"],
                        r["brand"], r["seller"], r["image_count"], " | ".join(r["images"]),
                        r["bullet_count"], " | ".join(map(str, r["bullets"][:8])),
                        json.dumps(r["overview"], ensure_ascii=False),
                        json.dumps(r["details"], ensure_ascii=False),
                        json.dumps(r["variations"], ensure_ascii=False),
                        json.dumps(r["categories"], ensure_ascii=False),
                        r["videos_count"], r["customers_say"], r["url"], r["error"]])
    (OUT / "products.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    print(f">>> 导出 -> {cp}")
    print(f">>> JSON -> {OUT/'products.json'}")
    print(f">>> 图片 -> {OUT/'images'}")

    # 完整度
    print("\n=== 字段完整度 ===")
    for f in ["title","price","rating","review_count","bought_past_month","brand","seller",
              "in_stock","image_count","bullet_count","overview","details","variations",
              "customers_say","categories"]:
        print(f"  {f:<20} {sum(1 for r in rows if r.get(f))}/{len(rows)}")


if __name__ == "__main__":
    main()
