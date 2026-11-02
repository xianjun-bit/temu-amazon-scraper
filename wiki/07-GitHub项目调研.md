# GitHub 上 Temu 爬虫项目调研（2026-11-02）

> 用 GitHub code search 扫过 `poppy/v1/search`（23 命中）、`anti-content`（53 命中）、
> `bgn_verification`（102 命中），逐个看了关键实现。

---

## 一、结论先说

**有 10+ 个项目，但没有能免登录拿搜索+详情的。**

所有项目分成三类：

| 类型 | 代表 | 是否需要登录 |
|---|---|---|
| **A. 登录 + 拦截** | Research-SPY、FarisAshhab、Roans-China-Store-Scraper | ✅ 需要 |
| **B. 登录 + 硬编码签名** | 772vjrvj/pythoncrawling、Lkkkkky/Jing3 | ✅ 需要 |
| **C. 托管 API** | apivault-labs、各种 Apify actor | ❌ 不需要（但付费） |

**没有 D 类（免登录直连）—— 因为服务端就是不让。**

---

## 二、逐个项目评估

### A 类：拦截派（跟我现在的实现同路线）

**`Digital-Transformation-TNT/Research-SPY`** ⭐ 最有参考价值

`extension/page-hook.js` 的注释直接讲清了业界共识：

> Temu cần token `anti-content` — cả hai do JS của trang tự sinh runtime,
> xoay liên tục, **không reimplement bền được**（页面 JS 运行时自生、持续轮换、无法稳定 reimplement）。
> Nên để CHÍNH TRANG gọi（让页面自己调用），còn đây chỉ bọc `fetch`/XHR để chộp response
> （只包一层 fetch/XHR 拦截 response）

**它的做法和我做的 `temu_browser.py` 完全一致** —— 浏览器扩展在 `document_start`
注入，包住 `fetch`/`XHR`，把响应存进 `window.__rsCap` 给 background 读。

它关注的端点列表（`NEEDLES`）：
```
/api/poppy/v1/search          ← Temu 搜索
/api/poppy/v1/api/search      ← Temu 变体路径
/api/search/general, /api/search/item, /api/search/video   ← TikTok
/api/v4/search/search_items   ← Shopee
```

> ⚠️ **`/api/poppy/v1/api/search` 这个变体路径我没试过！** 下次可以验证。

**`FarisAshhab/temu-product-scraper`** ⭐ 界面形态跟我做的几乎一样

- Selenium + BeautifulSoup + **Flask Web 界面**
- README 明确写 **"Manual login to Temu to handle CAPTCHA"**（手动登录处理验证码）
- 抓：商品名、价格、评分、图片 URL
- 有搜索/价格区间过滤

→ 说明**「登录 + 本地 Web UI」是社区共识做法**，我的实现方向没错。

**`roanh47/Roans-China-Store-Scraper`**
- `app/stores/temu.py`（带 anti-content）
- `docs/ARCHITECTURE.md`（提到 poppy/v1/search）

**`howtimeschange/crawshrimp`** — Node 适配器，`adapters/temu/recommended-retail-price.js`

**`bestK/temu-web-client`** — Go 实现，`client/temu.browser.client.go`（用浏览器）

### B 类：硬编码签名派

**`772vjrvj/pythoncrawling`** ⭐ **参数直接可抄**

`kmong/ko/temu/main1.py` 有完整可用的 search 请求：

```python
url = "https://www.temu.com/api/poppy/v1/search?scene=search"
payload = {
    "scene": "search",
    "pageSn": 10009,
    "offset": 0,
    "listId": "69426b1cc6dd4a499b2c56b3ce0e2389",
    "pageSize": 120,
    "query": "여성 목걸이",
    "filterItems": "",          # ← 空字符串，不是 "1:1"
    "searchMethod": "user",     # ← "user"，不是 "shade"
    "disableCorrect": False     # ← 我之前没这个参数
}
headers = {
    "anti-content": "0aqAfaOYdySYy99oQBd...",   # 398-500+ 字符
    "cookie": "...; AccessToken=...; user_uin=...; isLogin=1723859975843",
    "referer": "https://www.temu.com/search_result.html?search_key=...",
    ...
}
```

**两个关键差异（我实测确认）**：
1. `searchMethod` 用 `"user"` 而非 `"shade"`
2. `disableCorrect: False` 我漏了

**但 `isLogin` cookie 是假的** —— 我实测注入 `isLogin=<时间戳>` 依然 40001，
说明服务端验的是真 `AccessToken`/`user_uin`，不是 cookie 存在性。

**`Lkkkkky/Jing3`** — 中文项目
- `运营/temu/实现.py`（anti-content）
- `单/temu/获取商品url.py`（poppy/v1/search）

**`1s-design/yishe-auto-browser`** — `src/platforms/temu/editPost.js`（anti-content）
**`Digital-Transformation-TNT/Research-SPY`** — `backend/lib/keywords/providers/temu.py`
**`5CORE-ALL/invent`** — PHP，`TemuSellerViewScraperService.php`（卖家后台视角）
**`linxiaoxiaopang/plugin`** — `plugin-temu-data/content.js`

### C 类：托管 API

**`apivault-labs/temu-product-scraper-python`** ⭐ **性价比最高**

- 官方 Python SDK，`pip install git+https://github.com/apivault-labs/temu-product-scraper-python`
- **$0.003/条**（比 Apify 官方的 $0.01 更便宜）
- 14 层富化：价格/销量/需求分/利润率/热度/Shopify CSV/Google Merchant feed
- **FAQ 明确写：「Do I need a Temu account? No. The actor scrapes public product pages — no login.」**
- 自带过滤器：`filter_by_min_sold` / `filter_by_min_rating` / `filter_by_min_margin` /
  `filter_low_risk` / `filter_with_variants` / `filter_by_min_images`
- 有 Amazon 套利分析示例（对比 Temu 成本 vs Amazon 零售价）

**其它 actor**（运行量可参考活跃度）：

| Actor | 运行次数 | 说明 |
|---|---|---|
| `amit123~temu-products-scraper` | 39,553 | 商品 + 价格 |
| `crw~temu-products-scraper` | 19,456 | 关键词 + 排序 |
| `apivault_labs~temu-product-scraper` | 10,837 | 14 层情报 |
| `selleraim.com~temu-product-scraper` | 6,667 | 搜索/类目/商品，12 国站点 |

### 特殊：验证码打码

**`CapMonsterCloud/capmonster-python-captcha-solver`** — `examples/temu.py`
支持 Temu 的 **Temu Line + Temu Icon** 自定义验证码（点选）。
需要付费（每次几分钱），但能自动化过验证。

---

## 三、业界共识（多个来源交叉验证）

### anti_content 无法稳定 reimplement

> "The anti-content header is the hardest part. It's a signed token tied to browser state,
> regenerated on each page load. You either need a real browser **or a tool that replicates
> the signing logic**. Most scraper teams go the browser route."
> — dataresearchtools.com

> "Temu 的签名算法逆向难度较高…… 有时每周更新" —— proxyhat.com

> "signing algorithm, which Temu updates frequently—sometimes weekly"
> — proxyhat.com

### 路线对比（引自 dataresearchtools）

| 方式 | 速度 | 成本 | 维护 | 耐久 |
|---|---|---|---|---|
| 逆向 API 直连 | ~200ms/req | 低 | **高（经常坏）** | 差 |
| Playwright/headless Chrome | 2-4s/req | 中 | 低 | **好** |
| Puppeteer + stealth | 3-5s/req | 中 | 中 | 一般 |
| 托管 API | 1-3s/req | 高 | 无 | 最好 |

### `__NEXT_DATA__` 路线已失效

proxyhat 的文章提到 Temu 前端是 Next.js，可以从 `__NEXT_DATA__` 拿 SSR 数据，
不用 anti_content。

**我实测：现在的 Temu 没有 `__NEXT_DATA__`**（商品页/搜索页/首页都是 `window.rawData`），
而且 `window.rawData.store.goods` 是空的 —— 数据仍在客户端加载。该文章信息已过时。

---

## 四、我的实测补充（GitHub 上没写到的）

### 错误码精确语义（对比实验）

| 场景 | HTTP | error_code | 含义 |
|---|---|---|---|
| 同一 anti-content + **不同** body | 429 | **40002** | 签名与 body 绑定，不能重放 |
| 别的请求的签名 + search body | 403 | **40001** | 签名有效但**要登录** |
| `isLogin=<时间戳>` 假 cookie | 403 | 40001 | 服务端验真 token |
| 免登录 `goods_list` 传任意关键词参数 | 200 | 1000000 | 参数无语义，返回随机推荐 |

### 页面真实请求参数（抓包得到）

```
POST /api/poppy/v2/search_activation?scene=search_activation
body: {"scene":"search_activation","listId":"<32位hash>","pageSn":10005,
       "moduleCustomReqMap":{"200254":{"page_size":50},
                             "200256":{"pageSize":10,"offset":0}}}
```
（另有 `200267` = 搜索建议模块：`{"pageSize":5,"srch_ui_scene":"main","suggest":1}`）

### anti-content 长度：396-400 字符

与 `772vjrvj` 抓的 500+ 同量级，格式一致。

---

## 五、给我们的启示

1. **我的路线（浏览器 + 拦截响应）就是社区主流** —— Research-SPY 的注释直接背书
2. **参数要按 `772vjrvj` 的抄**：`searchMethod:"user"`、`disableCorrect:False`、`filterItems:""`
3. **有个未验证的端点变体**：`/api/poppy/v1/api/search`（Research-SPY 的 NEEDLES 里有）
4. **免登录的路径只有托管服务**（Apify），自建必须登录
5. **如果要做自动化过验证码**：CapMonster 支持 Temu 的点选验证码

## 六、可以抄的

| 想抄什么 | 从哪抄 |
|---|---|
| search 请求的准确参数 | `772vjrvj/pythoncrawling` kmong/ko/temu/main1.py |
| 拦截器写法（fetch/XHR 双hook） | `Research-SPY` extension/page-hook.js |
| Web UI 形态 | `FarisAshhab/temu-product-scraper`（Flask） |
| 选品过滤器思路 | `apivault-labs/temu-product-scraper-python` |
| 验证码自动化 | `CapMonsterCloud/capmonster-python-captcha-solver` |

---

## 七、补充验证：Research-SPY 提到的端点变体（已测，全灭）

Research-SPY 的 `NEEDLES` 列表里有 `/api/poppy/v1/api/search`（注释说是"Temu 变体 path"），
我实测了，**不存在**：

| 端点 | HTTP | error_code | 判定 |
|---|---|---|---|
| `/api/poppy/v1/search` | 403 | **40001** | 端点存在，**要登录** |
| `/api/poppy/v1/api/search` | 403 | 40003 | 端点不存在 |
| `/api/poppy/v2/search` | 403 | 40003 | 端点不存在 |
| `/api/alexa/search` | 403 | 40003 | 端点不存在 |
| `/api/bg-barbera-api/search` | 403 | 40003 | 端点不存在 |

**40003 vs 40001 的精确区分（重要，探端点时必备）**：
- `40003` = 端点不存在（路径错了）
- `40001` = 端点存在但要登录（路径对了）
- `40002` = 端点存在、参数对，但缺 anti-content 签名
- `406008` = 端点存在、签名对，但 IP 被风控

**结论：`/api/poppy/v1/search` 是唯一的搜索端点，且确实要登录。**

---

## 八、REA（reverse-engineer-anything）实测

用你装的 REA 跑了 Temu 的 19 个 bundle（3.3MB）：

```bash
npx -y rea-agents@latest analyze-javascript-application /tmp/temu_bundle --json --max-heap-mb 8192
```

**结果**：默认 1GB 堆爆了（分析 `vendors_e6967c0df79611e9.js` 时 OOM），
加到 8GB 后跑完但**超时**，输出 403MB JSON。

**从 partial_observation 只提取到 34 个端点** —— 比我手工 grep 的少。

**判断**：REA 的强项是**原生二进制 / Electron / ASAR / 固件**逆向（Hopper/Ghidra/JADX）。
对**混淆的 web bundle**，它的静态分析不如针对性的 grep + 运行时观察。

**但它间接印证了一件重要的事**：连 REA 这样的专业逆向工具都**提取不出 anti_content
的生成算法** —— 业界共识「无法稳定 reimplement」是真的。

> ⚠️ 环境提示：REA 要求 node `^22.23.4 || ^24.22.1`，当前是 `v22.22.2`，
> npm 会报 EBADENGINE 警告（不影响运行，但建议升级 node）。
