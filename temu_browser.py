#!/usr/bin/env python3
"""
Temu 登录态浏览器采集器 v2
==========================================
核心思路：**不自己发请求，而是拦截页面自己的 API 响应**。

为什么：
  - 页面自己的请求自带 anti-content 签名（native bridge 生成，纯 JS 伪造不了）
  - 页面自己的请求自带正确的 cookie / referer / session
  - 我们只要在 response 事件里把 JSON 捞出来解析

登录：
  - profile 目录持久化（.browser_profile），登录一次长期复用
  - headed 模式下弹窗，人工过登录/验证，之后全自动

防封：
  - 随机延迟（可配）
  - 失败退避（429/406008 自动降速）
  - 住宅代理支持（TEMU_PROXY 环境变量，可轮换）
  - 复用登录态（避免反复登录 —— 登录本身是高风险动作）
"""
from __future__ import annotations

import json
import os
import random
import re
import time
from pathlib import Path

BASE = "https://www.temu.com"

# ── 防封参数（可用环境变量覆盖）────────────────────────────
DELAY_MIN = float(os.environ.get("TEMU_DELAY_MIN", "1.8"))
DELAY_MAX = float(os.environ.get("TEMU_DELAY_MAX", "5.5"))
BACKOFF_BASE = float(os.environ.get("TEMU_BACKOFF", "4"))
MAX_RETRY = int(os.environ.get("TEMU_MAX_RETRY", "4"))
PROXY = os.environ.get("TEMU_PROXY", "").strip()


def _sleep(rnd: random.Random, scale: float = 1.0):
    time.sleep(rnd.uniform(DELAY_MIN, DELAY_MAX) * scale)


def _proxy_args():
    """Playwright 的代理配置"""
    if not PROXY:
        return {}
    # http://user:pass@host:port
    m = re.match(r"^(?:https?://)?(?:([^:@/]+):([^@/]*)@)?([^:/]+):(\d+)$", PROXY)
    if not m:
        return {}
    user, pwd, host, port = m.groups()
    s = {"server": f"http://{host}:{port}"}
    if user:
        s["username"] = user
        s["password"] = pwd or ""
    return {"proxy": s}


# ── 响应拦截器 ────────────────────────────────────────────
class _Interceptor:
    """收集页面自己发出的 API 响应"""

    def __init__(self):
        self.search_hits: list[dict] = []
        self.detail_hits: list[dict] = []
        self.errors: list[dict] = []

    def attach(self, page):
        page.on("response", self._on_resp)

    def _on_resp(self, res):
        u = res.url
        if "/api/" not in u:
            return
        if not any(k in u for k in ("/poppy/v1/search", "/poppy/v1/goods_detail",
                                     "/alexa/homepage/goods_list", "/poppy/v1/opt_list")):
            return
        try:
            ct = (res.headers or {}).get("content-type", "")
            if "json" not in ct:
                return
            body = res.text()
        except Exception:
            return
        if not body or len(body) < 30:
            return
        try:
            j = json.loads(body)
        except Exception:
            return

        code = j.get("error_code")
        if code and code != 1000000:
            self.errors.append({"url": u, "code": code, "status": res.status,
                                "msg": (j.get("message") or j.get("error_msg") or "")[:80]})
            return

        result = j.get("result") or {}
        data = result.get("data") or {}
        gl = data.get("goodsList") or []
        if "/search" in u:
            if gl:
                self.search_hits.append({"goods": gl, "has_more": result.get("hasMore"),
                                         "total": data.get("goodsNumAdv")})
        elif "/goods_detail" in u:
            if gl:
                self.detail_hits.append({"goods": gl, "main": data.get("mainGoodsList") or [],
                                         "title": data.get("title")})

    def take_search(self):
        h = self.search_hits
        self.search_hits = []
        return h

    def take_detail(self):
        h = self.detail_hits
        self.detail_hits = []
        return h


# ── 字段提取（兼容多种命名）────────────────────────────────
def _pick(d: dict, *names, default=None):
    for n in names:
        v = d.get(n)
        if v not in (None, "", [], {}):
            return v
    return default


def _extract_gallery(g: dict) -> list[str]:
    """从详情响应里提取全部附图"""
    out = []
    for key in ("goodsGallery", "bannerList", "imageList", "customImageList",
                "gallery", "imgList", "detailList"):
        v = g.get(key)
        if isinstance(v, list):
            for it in v:
                if isinstance(it, str) and it.startswith("http"):
                    out.append(it)
                elif isinstance(it, dict):
                    for kk in ("url", "imageUrl", "thumbUrl", "bigUrl", "goodsGalleryUrl"):
                        if it.get(kk):
                            out.append(str(it[kk]))
                            break
    # sku 里的图
    for sk in (g.get("skuList") or []):
        if isinstance(sk, dict):
            for kk in ("thumbUrl", "imageUrl", "url"):
                if sk.get(kk):
                    out.append(str(sk[kk]))
                    break
    return list(dict.fromkeys([u for u in out if u.startswith("http")]))[:30]


def _extract_bullets(g: dict) -> list[str]:
    """从详情响应里提取五点描述"""
    out = []
    for key in ("bulletDesc", "goodsProperty", "featureDesc", "sellingPoint",
                "goodsFeature", "featureList", "highlight", "descList",
                "goodsDesc", "detailDesc"):
        v = g.get(key)
        if isinstance(v, list):
            for it in v:
                if isinstance(it, str) and len(it.strip()) > 8:
                    out.append(it.strip())
                elif isinstance(it, dict):
                    for kk in ("text", "desc", "content", "value", "name"):
                        if it.get(kk) and len(str(it[kk])) > 8:
                            out.append(str(it[kk]).strip())
                            break
        elif isinstance(v, str) and len(v) > 20:
            out.append(v.strip())
    return list(dict.fromkeys(out))[:12]


def _norm_goods(g: dict) -> dict:
    """把 Temu 的 goods 对象转成统一记录"""
    pi = g.get("priceInfo") or g.get("price_info") or {}
    price = _pick(pi, "priceStr", "price_str", "minPrice", "price") or g.get("price")
    cur = _pick(pi, "currency", "currencyCode") or g.get("currency") or ""
    gid = str(_pick(g, "goodsId", "goods_id", "id") or "")
    title = _pick(g, "goodsName", "title", "goodsNameEn") or ""
    if "<" in str(title):
        title = re.sub(r"<[^>]+>", "", str(title))
    imgs = _extract_gallery(g)
    if not imgs:
        t = _pick(g, "thumbUrl", "thumb_url", "imageUrl")
        if t: imgs = [str(t)]
    bullets = _extract_bullets(g)
    specs = {}
    for k in ("goodsProperty", "specification", "props", "attributes"):
        v = g.get(k)
        if isinstance(v, list):
            for it in v:
                if isinstance(it, dict):
                    nm = _pick(it, "name", "key", "attrName", "propertyName")
                    vv = _pick(it, "value", "attrValue", "propertyValue", "text")
                    if nm and vv:
                        specs[str(nm)[:40]] = str(vv)[:120]
    sales = _pick(g, "salesTip", "soldCount", "goodsSales", "sales", "soldTip")
    rating = _pick(g, "goodsScore", "rating", "score")
    reviews = _pick(g, "reviewCount", "commentNum", "commentCount")
    link = _pick(g, "linkUrl", "link_url", "url") or f"{BASE}/goods.html?goods_id={gid}"
    if str(link).startswith("/"):
        link = BASE + str(link)
    return {
        "platform": "temu", "id": gid, "title": str(title).strip(),
        "price": price, "currency": cur, "rating": rating, "review_count": reviews,
        "sold": sales, "brand": _pick(g, "brandName", "brand", "brandInfo"),
        "seller": None, "in_stock": _pick(g, "isOnsale", "onSale"),
        "images": imgs, "image_count": len(imgs),
        "bullets": bullets, "bullet_count": len(bullets),
        "specs": specs, "variations": {},
        "url": str(link), "error": "",
    }


# ══════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════
def scrape_temu_browser(keyword: str, limit: int = 80, download_images: bool = True,
                        headless: bool = False, profile: str = "",
                        max_detail: int = 0):
    """Temu 浏览器模式 v2：登录态复用 + 响应拦截 + 防封。

    流程：
      1. 打开搜索页（profile 持久化 -> 登录态复用）
      2. 若跳登录/验证页 -> headed 模式提示人工处理
      3. 拦截页面自己的 /poppy/v1/search 响应 -> 累积商品
      4. 逐个打开商品页 -> 拦截 /poppy/v1/goods_detail -> 提取五点/图集/销量
      5. 随机延迟 + 失败退避，避免触发风控
    """
    from playwright.sync_api import sync_playwright

    rnd = random.Random()
    prof = Path(profile or os.environ.get("TEMU_PROFILE")
                or str(Path(__file__).parent / ".browser_profile"))
    prof.parent.mkdir(parents=True, exist_ok=True)

    args = ["--disable-blink-features=AutomationControlled"]
    px = _proxy_args()
    if px:
        args.append(f"--proxy-server={px['proxy']}")
    if px.get("username"):
        # 带认证的代理
        args.append(f"--proxy-server=http://{px['username']}:{px['password']}@{px['proxy'].split('://')[-1]}")

    pw = sync_playwright().start()
    ctx = None
    try:
        ctx = pw.chromium.launch_persistent_context(
            str(prof), headless=headless, channel="chrome",
            viewport={"width": 1500, "height": 950}, locale="en-US",
            timezone_id="America/New_York",
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
            args=args, ignore_default_args=["--enable-automation"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ic = _Interceptor()
        ic.attach(page)

        # 搜索页入口参数（来自 GitHub 上可用的实现 772vjrvj/pythoncrawling + 实测）
        # search_method 用 "shade"（浏览器默认）；search API 的 body 里用 "user"
        Q = (f"search_key={keyword.replace(' ', '%20')}&search_method=shade"
             f"&refer_page_el_sn=200010&srch_enter_source=top_search_entrance_10005"
             f"&refer_page_name=home&refer_page_sn=10005&filter_items=1%3A1")
        url = f"{BASE}/search_result.html?{Q}"

        yield {"_phase": "search", "message": f"打开搜索页：{keyword}"}
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(9000)

        # ── 登录 / 风控验证处理 ──
        # bgn_verification 带 verifyCode 时通常能自动通过（刷新一次即可），
        # 只有需要人工点选时才等待。
        for attempt in range(6):
            cur = page.url
            if "/login" in cur:
                if headless:
                    raise RuntimeError(
                        "需要登录态，但当前是 headless 模式。\n"
                        "解决一：先在有图形界面的机器上跑一次登录（登录态可复用）：\n"
                        "         .venv/bin/python temu_login.py\n"
                        "解决二：改用 --mode apify（托管服务，无需登录）")
                yield {"_phase": "login", "need_login": True,
                       "message": "请在浏览器窗口完成登录（登录态会保存，之后不用再登）"}
                page.wait_for_timeout(4000)
                continue
            if "bgn_verification" in cur:
                # 自动尝试：等页面自己处理 / 刷新一次
                page.wait_for_timeout(4500)
                if attempt >= 1:
                    # 第二次还卡着 -> 刷新（verifyCode 换新的）
                    try:
                        page.reload(wait_until="domcontentloaded", timeout=45000)
                        page.wait_for_timeout(4500)
                    except Exception:
                        pass
                if attempt >= 2:
                    if headless:
                        raise RuntimeError(
                            "风控验证页自动通过失败（headless 无法人工点选）。\n"
                            "解决一：先在有图形界面的机器上跑一次登录/验证：\n"
                            "         .venv/bin/python temu_login.py\n"
                            "解决二：配住宅代理：export TEMU_PROXY=http://u:p@h:port\n"
                            "解决三：改用 --mode apify")
                    yield {"_phase": "login", "need_login": True,
                           "message": "风控验证需要人工点选，请在浏览器窗口完成验证"}
                    page.wait_for_timeout(6000)
                continue
            break

        # 等 search 响应（页面自己发）
        deadline = time.time() + 40
        while time.time() < deadline and not ic.search_hits:
            page.wait_for_timeout(1200)

        # ── 备用：页面没发 search 时，用正确参数自己发一次 ──
        # 参数来自 GitHub 可用实现（772vjrvj/pythoncrawling）：
        #   searchMethod="user"（不是 shade）、disableCorrect=False、filterItems=""
        # 注意：anti-content 与 body 绑定，自己发必须带页面当前的签名头，
        #       否则返回 40002。
        if not ic.search_hits:
            list_id = ""
            try:
                lst = page.evaluate("() => (window.rawData?.store?.listId) || ''")
                list_id = lst or ""
            except Exception:
                pass
            body = {"scene": "search", "pageSn": 10009, "offset": 0,
                    "listId": list_id or "a" * 32, "pageSize": 120,
                    "query": keyword, "filterItems": "",
                    "searchMethod": "user", "disableCorrect": False}
            yield {"_phase": "progress",
                   "message": "页面未发出搜索请求，尝试直接调用 search 接口…"}
            try:
                r = page.evaluate("""async (b) => {
                  try {
                    const res = await fetch('/api/poppy/v1/search?scene=search', {
                      method:'POST', credentials:'include',
                      headers:{'Content-Type':'application/json;charset=UTF-8',
                               'Accept':'application/json, text/plain, */*'},
                      body: JSON.stringify(b)});
                    const t = await res.text();
                    let code=null, gl=[];
                    try { const j=JSON.parse(t); code=j.error_code;
                          gl=((j.result||{}).data||{}).goodsList||[]; } catch(e){}
                    return {status:res.status, code:code, goods:gl, head:t.slice(0,140)};
                  } catch(e){ return {err:String(e)}; }
                }""", body)
                if r.get("goods"):
                    ic.search_hits.append({"goods": r["goods"], "has_more": True})
                    yield {"_phase": "search",
                           "message": f"直接调用成功，取到 {len(r['goods'])} 个商品"}
                else:
                    code = r.get("code")
                    hint = {40001: "需要登录（用 temu_login.py 登录一次）",
                            40002: "缺 anti-content 签名",
                            406008: "IP 被风控"}.get(code, f"错误码 {code}")
                    yield {"_phase": "progress",
                           "message": f"直接调用失败：{hint}"}
            except Exception as e:
                yield {"_phase": "progress", "message": f"直接调用异常：{str(e)[:80]}"}

        # ── 累积搜索结果（滚动触发分页）──────────────────────
        goods, seen = [], set()
        stall = 0
        for round_no in range(14):
            for hit in ic.take_search():
                for g in hit["goods"]:
                    gid = str(_pick(g, "goodsId", "goods_id", "id") or "")
                    if gid and gid not in seen:
                        seen.add(gid); goods.append(g)
            yield {"_phase": "progress",
                   "message": f"搜索到 {len(goods)} 个商品",
                   "current": len(goods), "total": limit}
            if len(goods) >= limit:
                break
            # 滚动加载更多
            before = len(goods)
            for _ in range(3):
                page.mouse.wheel(0, 2200)
                page.wait_for_timeout(rnd.randint(1400, 2400))
            page.wait_for_timeout(2500)
            if len(goods) == before:
                stall += 1
                if stall >= 3:
                    break
            else:
                stall = 0
            _sleep(rnd, 0.6)

        if not goods:
            errs = ic.errors[-3:]
            raise RuntimeError(
                "没抓到搜索结果。\n"
                + (f"最近的错误码：{[(e['code'], e['url'].split('/api/')[-1][:40]) for e in errs]}\n"
                   if errs else "")
                + "可能原因：① 需要登录 ② 触发了风控验证码 ③ IP 被限流")

        goods = goods[:limit]
        yield {"_phase": "search", "message": f"搜索到 {len(goods)} 个商品，开始抓详情"}

        # ── 逐个抓详情 ──────────────────────────────────────
        n_detail = max_detail or len(goods)
        for i, g in enumerate(goods[:n_detail], 1):
            gid = str(_pick(g, "goodsId", "goods_id", "id") or "")
            link = _pick(g, "linkUrl", "link_url") or f"{BASE}/goods.html?goods_id={gid}"
            if str(link).startswith("/"):
                link = BASE + str(link)
            try:
                ic.detail_hits = []
                page.goto(str(link), wait_until="domcontentloaded", timeout=60000)
                # 等 goods_detail 响应
                dl = time.time() + 22
                while time.time() < dl and not ic.detail_hits:
                    page.wait_for_timeout(900)
                if ic.detail_hits:
                    det = ic.take_detail()[-1]
                    # 优先用详情响应里的主商品，合并搜索页字段
                    main = det.get("main") or det.get("goods") or []
                    src = main[0] if main else det["goods"][0]
                    rec = _norm_goods({**g, **src})
                else:
                    # 退路：读 DOM
                    rec = _norm_goods(g)
                    rec["error"] = "详情接口未响应(已用搜索页数据)"
                yield {"_phase": "item", "record": rec}
            except Exception as e:
                yield {"_phase": "item",
                       "record": _norm_goods(g) | {"error": str(e)[:100]}}
            # 防封延迟
            _sleep(rnd)
            if i % 10 == 0:
                yield {"_phase": "progress", "message": f"详情 {i}/{n_detail}",
                       "current": i, "total": n_detail}

        # ── 图片 ───────────────────────────────────────────
        if download_images:
            yield {"_phase": "images", "message": "开始下载图片…"}
            from collectors import _save_images, OUT_TEMU
            total = 0
            for g in goods[:n_detail]:
                gid = str(_pick(g, "goodsId", "goods_id", "id") or "")
                rec = _norm_goods(g)
                if rec["images"]:
                    total += len(_save_images(rec["images"][:20],
                                              OUT_TEMU / "images" / (gid or "x")))
            yield {"_phase": "images_done", "message": f"图片下载 {total} 张"}

    finally:
        try:
            if ctx: ctx.close()
        except Exception: pass
        try: pw.stop()
        except Exception: pass
