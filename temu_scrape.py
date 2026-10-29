#!/usr/bin/env python3
"""
Temu 选品数据抓取器 —— 自建方案（已验证可行路径）

已验证的关键事实（2026-10 实测）：
  1. curl / requests 直连 → 被 Temu 的 JS challenge 拦截（返回 ~3KB 混淆脚本）
  2. curl_cffi (TLS 指纹伪装) → 100% 稳定通过 challenge，拿到完整 SSR 页面（实测 26/26）
  3. 但 SSR 是空壳：商品数据（图片/价格/五点描述）不在 HTML 里，走 XHR
  4. XHR 直连 API → 429 (IP 级风控) + 需要 anti-token 签名
  5. 浏览器渲染 → 会触发滑块/点选验证码（当前 IP 已被标记）
  ⇒ 结论：纯自建需要「住宅代理 + 持久化登录态」；否则走 Apify 现成 actor

用法：
  python temu_scrape.py search  "laundry bag"  --limit 80
  python temu_scrape.py urls    urls.txt --limit 80
"""
import argparse, csv, json, os, random, re, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from curl_cffi import requests

BASE = "https://www.temu.com"
OUT = Path(__file__).parent / "output"

# Temu 的 JS Challenge 对 TLS 指纹是**动态判定**的：
# 同一 IP 下 chrome124 上一轮 26/26 全过，下一轮却只有 chrome131 能过。
# 所以不能固定某一个指纹 —— 每次请求轮换，失败就换下一个。
IMPERSONATES = [
    "chrome131", "chrome124", "chrome120", "chrome119", "chrome136",
    "safari17_0", "safari15_3", "safari18_0", "edge101", "edge99",
]

# 实测过 challenge 的指纹会被优先复用（首次探测后缓存）
_GOOD_FINGERPRINTS: list[str] = []


def probe_fingerprint(session, url="https://www.temu.com/"):
    """探测当前哪些指纹能过 challenge，结果缓存复用"""
    global _GOOD_FINGERPRINTS
    if _GOOD_FINGERPRINTS:
        return _GOOD_FINGERPRINTS
    for imp in IMPERSONATES:
        try:
            r = session.get(url, impersonate=imp, timeout=25)
            if len(r.text) > 10000 and "window.challenge" not in r.text[:4000]:
                _GOOD_FINGERPRINTS.append(imp)
        except Exception:
            pass
    if not _GOOD_FINGERPRINTS:
        _GOOD_FINGERPRINTS = IMPERSONATES[:]
    return _GOOD_FINGERPRINTS



# ---------------------------------------------------------------- 工具
def new_session(region="37"):
    s = requests.Session()
    s.headers.update({
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Sec-Ch-Ua": '"Chromium";v="131", "Not_A Brand";v="24"',
        "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none", "Sec-Fetch-User": "?1",
    })
    return s


def fetch(s, url, imp=None, retries=6):
    """带重试 + 指纹轮换的抓取，返回 HTML（失败返回 None）

    实测：Temu 的 challenge 判定会随时间变化，同一指纹上一轮能过下一轮就废。
    所以这里先探测可用指纹，再逐个尝试，且每次失败都换指纹。
    """
    cands = probe_fingerprint(s) if not imp else [imp]
    for i in range(retries):
        use = imp or cands[i % len(cands)]
        try:
            r = s.get(url, impersonate=use, timeout=35, allow_redirects=True)
            t = r.text
            # 判定：足够长 且 不是 challenge 壳
            if len(t) > 20000 and "window.challenge" not in t[:4000]:
                return t
        except Exception:
            pass
        time.sleep(1.2 + random.random() * 2)
    return None


def extract_json_after(text, marker):
    i = text.find(marker)
    if i < 0:
        return None
    j = text.find('{', i)
    if j < 0:
        return None
    depth, in_str, esc = 0, False, False
    for k in range(j, len(text)):
        ch = text[k]
        if in_str:
            if esc: esc = False
            elif ch == '\\': esc = True
            elif ch == '"': in_str = False
            continue
        if ch == '"': in_str = True
        elif ch == '{': depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                try: return json.loads(text[j:k + 1])
                except Exception: return None
    return None


def get_rawdata(html):
    return extract_json_after(html, 'window.rawData=')


def walk_find(obj, pred, path="", depth=0, out=None):
    """递归查找满足 pred 的节点"""
    if out is None: out = []
    if depth > 8 or not isinstance(obj, (dict, list)): return out
    if pred(obj):
        out.append((path, obj))
    if isinstance(obj, list):
        for i, v in enumerate(obj[:100]):
            walk_find(v, pred, f"{path}[{i}]", depth + 1, out)
    else:
        for k, v in obj.items():
            walk_find(v, pred, f"{path}.{k}", depth + 1, out)
    return out


# ---------------------------------------------------------------- 搜索
def search_urls(keyword, limit=80, region="37"):
    """搜索关键词，返回商品 URL 列表"""
    s = new_session(region)
    urls, seen = [], set()
    # Temu 搜索走 XHR，SSR 只给 listId；这里从 SSR 抽 link，
    # 并支持翻页参数。SSR 无商品时回退到 SEO 页面形式。
    for page_no in range(1, (limit // 60) + 3):
        url = (f"{BASE}/search_result.html?search_key={keyword}"
               f"&page_num={page_no}&refer_page_sn=10005&search_method=shade")
        html = fetch(s, url)
        if not html:
            continue
        found = re.findall(r'href="(/[^"]*-g-\d{10,}\.html)', html)
        found += re.findall(r'"(/[^"]*-g-\d{10,}\.html)"', html)
        for f in found:
            full = BASE + f
            if full not in seen:
                seen.add(full); urls.append(full)
        if len(urls) >= limit:
            break
        time.sleep(1 + random.random())
    return urls[:limit]


def search_urls_google(keyword, limit=80):
    """回退方案：用搜索引擎定位 temu 商品链接（无需 Temu 会话）"""
    found, seen = [], set()
    for q in [f"site:temu.com {keyword}", f"temu.com {keyword} -g-"]:
        try:
            r = requests.get(f"https://www.bing.com/search?q={requests.utils.quote(q)}",
                             impersonate=IMPERSONATES[i % len(IMPERSONATES)], timeout=25)
            hits = re.findall(r'https?://(?:www\.)?temu\.com/[^\s"\'<>]*?-g-\d{10,}\.html', r.text)
            for h in hits:
                h = h.split('?')[0]
                if h not in seen:
                    seen.add(h); found.append(h)
        except Exception:
            pass
        if len(found) >= limit:
            break
    return found[:limit]


# ---------------------------------------------------------------- 商品详情
def parse_product(html, url):
    """从 SSR HTML 提取商品数据（SSR 有骨架数据时有效）"""
    out = {"url": url, "title": "", "price": "", "currency": "", "images": [],
           "bullet_points": [], "props": {}, "goods_id": "", "sold": "", "rating": ""}
    m = re.search(r'-g-(\d{10,})', url)
    if m: out["goods_id"] = m.group(1)
    if not out["goods_id"]:
        m = re.search(r'goods_id=(\d+)', url)
        if m: out["goods_id"] = m.group(1)

    raw = get_rawdata(html)
    if raw:
        st = raw.get("store", {})
        g = st.get("goods")
        if isinstance(g, dict) and g:
            out["title"] = g.get("goodsName") or g.get("title") or ""
            pi = g.get("priceInfo") or g.get("price") or {}
            if isinstance(pi, dict):
                out["price"] = pi.get("price") or pi.get("minPrice") or ""
                out["currency"] = pi.get("currencySymbol") or ""
            gal = g.get("goodsGallery") or g.get("gallery") or []
            if isinstance(gal, list):
                for it in gal:
                    u = it.get("goodsGalleryUrl") or it.get("url") or it.get("thumbUrl") if isinstance(it, dict) else it
                    if u: out["images"].append(u)
            props = g.get("goodsProperty") or []
            if isinstance(props, list):
                for p in props:
                    if isinstance(p, dict):
                        out["props"][p.get("key", "")] = p.get("value", "")
            bl = g.get("bulletDesc") or g.get("goodsDesc") or []
            if isinstance(bl, list):
                out["bullet_points"] = [b if isinstance(b, str) else b.get("content", "") for b in bl]
            out["sold"] = g.get("soldCount") or g.get("salesTip") or ""
            out["rating"] = g.get("goodsScore") or ""

    # ld+json（部分页面/镜像站可用）
    for ld in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S):
        try: j = json.loads(ld)
        except Exception: continue
        if j.get("@type") == "Product":
            out["title"] = out["title"] or j.get("name", "")
            off = j.get("offers") or {}
            if isinstance(off, dict):
                out["price"] = out["price"] or str(off.get("price", ""))
            imgs = j.get("image")
            if isinstance(imgs, list):
                out["images"] += [i if isinstance(i, str) else i.get("contentUrl", "") for i in imgs]
            desc = j.get("description")
            if desc: out["bullet_points"] = out["bullet_points"] or [desc]
    out["images"] = [i for i in dict.fromkeys(out["images"]) if i]
    return out


def download_images(urls, folder, concurrency=8):
    """并发下载图片到本地"""
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    ok = 0
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = {ex.submit(download_one, u, folder): u for u in urls}
        for f in as_completed(futs):
            if f.result(): ok += 1
    return ok


def download_one(url, folder):
    try:
        r = requests.get(url, impersonate=IMPERSONATES[hash(url) % len(IMPERSONATES)], timeout=30)
        if r.status_code == 200 and len(r.content) > 1000:
            ext = ".jpg"
            if "png" in r.headers.get("content-type", ""): ext = ".png"
            if "webp" in r.headers.get("content-type", ""): ext = ".webp"
            name = hashlib_md5(url) + ext
            (Path(folder) / name).write_bytes(r.content)
            return True
    except Exception:
        pass
    return False


def hashlib_md5(s):
    import hashlib
    return hashlib.md5(s.encode()).hexdigest()[:16]


# ---------------------------------------------------------------- 主流程
def run(urls, limit, outdir, dl_images):
    OUT.mkdir(exist_ok=True)
    rows = []
    s = new_session()
    for i, u in enumerate(urls[:limit], 1):
        html = fetch(s, u)
        if not html:
            print(f"  [{i}/{min(len(urls),limit)}] ❌ 取页失败 {u[:70]}")
            continue
        rec = parse_product(html, u)
        rows.append(rec)
        print(f"  [{i}/{min(len(urls),limit)}] {'✅' if rec['title'] else '⚠️ '} "
              f"{rec['goods_id']} {(rec['title'] or '(SSR无标题)')[:52]} "
              f"图{len(rec['images'])} 五点{len(rec['bullet_points'])} ${rec['price']}")
        if dl_images and rec["images"]:
            download_images(rec["images"], OUT / "images" / (rec["goods_id"] or f"item{i}"))
        time.sleep(0.6 + random.random() * 0.8)

    # 导出
    csv_path = OUT / "products.csv"
    if rows:
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["goods_id", "title", "price", "currency", "sold", "rating",
                        "image_count", "image_urls", "bullet_points", "props", "url"])
            for r in rows:
                w.writerow([r["goods_id"], r["title"], r["price"], r["currency"], r["sold"],
                            r["rating"], len(r["images"]), " | ".join(r["images"]),
                            " | ".join(r["bullet_points"]),
                            json.dumps(r["props"], ensure_ascii=False), r["url"]])
        (OUT / "products.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    print(f"\n✅ 已导出 {len(rows)} 条 -> {csv_path}")
    print(f"   JSON -> {OUT/'products.json'}")
    if dl_images:
        print(f"   图片 -> {OUT/'images'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["search", "urls"])
    ap.add_argument("target", help="关键词 或 URL 文件")
    ap.add_argument("--limit", type=int, default=80)
    ap.add_argument("--images", action="store_true", help="同时下载图片")
    a = ap.parse_args()

    if a.mode == "search":
        print(f">>> 搜索: {a.target}")
        urls = search_urls(a.target, a.limit)
        if len(urls) < a.limit:
            print(f"    SSR 仅取到 {len(urls)} 条，启用搜索引擎回退")
            urls = search_urls_google(a.target, a.limit - len(urls)) + urls
        urls = urls[:a.limit]
        print(f">>> 命中 {len(urls)} 个商品 URL")
        Path(OUT / "urls.txt").write_text("\n".join(urls))
    else:
        urls = [l.strip() for l in Path(a.target).read_text().splitlines() if l.strip().startswith("http")]
        print(f">>> 读取 {len(urls)} 个 URL")

    run(urls, a.limit, OUT, a.images)


if __name__ == "__main__":
    main()
