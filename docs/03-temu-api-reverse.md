<div align="center">

**[← 返回目录](index.md)** · [现状总览](01-status-overview.md) · [Temu 反爬](02-temu-antibot.md) · [API 逆向](03-temu-api-reverse.md) · [Amazon 实战](04-amazon-practice.md) · [踩坑清单](05-pitfalls.md) · [换机续作](06-handoff.md)

</div>

---
# 03 · Temu API 逆向

> 方法论 + 已确认的端点与参数。**逆向方法本身比结论更重要** —— Temu 改版后按方法重做即可。

## 逆向方法：挖 JS bundle

Temu 的 HTML 里没有 `<script src>`，资源由 `__XRenderResourcesLoader__` 注入。
但资源 URL 明文写在 HTML 里：

```bash
curl -s --max-time 30 'https://www.temu.com/search_result.html?search_key=laundry+bag' \
  -H 'User-Agent: Mozilla/5.0 ...' -o /tmp/s.html

grep -oE '"https://static\.kwcdn\.com/m-assets/assets/modernjs/[^"]+\.js"' /tmp/s.html | sort -u
```

得到的关键 bundle：
```
https://static.kwcdn.com/m-assets/assets/modernjs/w/search_result_42feb8aacdac801f.js
https://static.kwcdn.com/m-assets/assets/modernjs/2027_ae8d50f894417364a534.js   ← 1.5MB，含请求封装
https://static.kwcdn.com/m-assets/assets/modernjs/8226_61d012e62a14388190b5.js   ← 含搜索逻辑
```

**地址规律**：
```
https://static.kwcdn.com/m-assets/assets/modernjs/{w/}search_result_{hash}.js
https://static.kwcdn.com/m-assets/assets/modernjs/{chunkId}_{hash}.js
```

下载后 grep API 路径：
```bash
grep -oE '"/api/[a-zA-Z0-9_/-]{4,80}"' bundle.js | sort -u
```

从 `8226_*.js` 挖到：
```
/api/poppy/v1/search
/api/poppy/v1/search_suggest
/api/poppy/v1/opt_list
/api/bg/epiktetos/common/footprint/list
/api/promotion/open/recommend/promotion/goods/list
```

从 `2027_*.js`（module 55303）挖到 URL 构造与请求封装：

```javascript
// module 55303 —— wU 只是在 URL 后拼 ?scene=
let i = function(e="", t) {
  return e && t && t.scene ? `${e}${e.includes("?")?"&":"?"}scene=${t.scene}` : e;
};

// module 19999 —— 请求是 GET + params（不是 body）
let A = e => { let {url:n, params:r={}, config:o} = e||{};
               return t.get(n, {params:r, ...y(o)||{}}) ... }
```

## 已确认端点

### 1. 首页商品列表 —— ✅ 实测可用

```
POST /api/alexa/homepage/goods_list
Content-Type: application/json;charset=UTF-8

body: {
  "offset": 0, "count": 120,
  "list_id": "", "opt_id": null, "listId": "",
  "scene": "home", "page_list_id": "", "extend_fields": {}
}
```

**响应**：
```
result.home_goods_list[]           # 40 个模块
  .data.goods_list[]               # 商品数组
    .goods_id                      # "601099702825429"
    .title                         # "4/7/8/9-drawer Home Display Cabinet..."（含 HTML 标签，需 strip）
    .price_info.price_str          # "$23.56"
    .price_info.price              # 2356（分）
    .price_info.currency           # "USD"
    .image.url                     # "https://img.kwcdn.com/product/fancy/xxx.jpg"
    .image.width / .height         # 1024
    .link_url                      # "goods.html?_bg_fs=1&goods_id=...&top_gallery_url=..."
```

⚠️ **注意**：传 `scene:"search"` 会被忽略，返回的仍是首页推荐商品（标题与关键词无关）。实测确认过。

### 2. 搜索 —— ⚠️ 参数已逆向，需 anti-token

```
GET /api/poppy/v1/search?scene=search
    &query=<关键词>
    &offset=0&pageSize=60
    &listId=<搜索页 rawData.store.listId>
    &pageSn=10009
    &pageElSn=200010
    &srchEnterSource=10037212883
    &filterItems=1:1
    &searchMethod=shade
```

**响应结构**（从 bundle 的 format 函数反推）：
```
result.hasMore
result.data.goodsList[]      # 商品数组
result.data.title
result.data.optList[]        # 筛选列表
result.data.filterRegion.rankColumFilter[]   # 排序项
result.data.goodsNumAdv
result.data.pSearch
result.data.recList[]
result.data.recommendWords[]
result.data.shieldAll
```

**失败态**：直连返回 `500`（GET 路由不匹配）或 `40002`（缺 anti-token）。

### 3. search_activation —— ⚠️ 40002

```
POST /api/poppy/v2/search_activation
body: {
  "scene": "search_activation",
  "listId": "<listId>",
  "pageSn": 10009,
  "moduleCustomReqMap": {"200254": {"page_size": 50},
                         "200256": {"pageSize": 10, "offset": 0, "wordsBlackList": [...]}}
}
```
首页版本能 200（这个 body 是从首页真实请求抓的），搜索页版本返 `40002`。
推测搜索页需要不同的模块号（`refer_page_el_sn=200010` 是页面元素号，不是模块号）。

### 4. 商品详情 —— ❌ 端点未确认

试过并全部返回 403 (`40003`) 或 429 (`406008`)：

```
/api/alexa/goods/detail          /api/alexa/goods/detail_v2
/api/goods/detail                /api/poppy/v2/goods/detail
/api/bg-bff-api/goods/detail     /api/alexa/odin/goods/detail
/api/alexa/pc/goods/detail       /api/phantom/xg/goods/detail
/api/goods/goods_detail          /api/alexa/goods/goods_detail
/api/poppy/v2/goods/detail_v2    /api/bg-barbera-api/goods/detail/pc
```

body 试过 `{"goods_id": "..."}` / `{"goodsId": "..."}` / `{"goods_id": 601100...}` /
加 `scene`/`page_sn` / `{"keyword":...}` 等变体。

**下一步线索**：详情页 JS bundle（`goods_*` chunk）里应该有真实端点，
在 `https://static.kwcdn.com/m-assets/assets/modernjs/` 下按 `goods` 关键字找。

### 5. 其它已确认端点（200 但非商品数据）

```
GET  /api/static/config/get_front_end_page_config?client=PC&useAntiToken=true   # 25250B
POST /api/phantom/xg/pfb/l1        body {"version":"2.20.1"}   # 7148B，风控 token
POST /api/bg/huygens/setting/query body {}                     # 区域/货币配置
POST /api/bg-barbera-api/home/footer/pc
POST /api/alexa/pc/homepage/activity
POST /api/phantom/obtain_captcha   # 验证码题面（需要 verifyAuthToken cookie）
```

## 搜索页 rawData 可用字段

```javascript
window.rawData.store = {
  searchKey: "laundry bag",
  pageSize: 120,
  currentPage: 0,
  listId: "938ffd732e134888882f432fa4b15d0a",   // 每次请求都变
  realSearchKey: "",
  searchMethod: "shade",
  usePrefetchGoods: true,      // ← 会预取商品
  fsGoodsCount: 14,            // ← 预取数量
  hasSearchResults: null,
  hasMore: true,
  totalPage: 1,
  pattern: 0,
  isRobot: false,
  isLogin: false,
  hasOneLogin: false,
  dr: "us",
  pageSn: 10009,
  localInfo: {region: "37", language: "en", currency: "CAD"},
  query: {search_key, search_method, refer_page_el_sn, srch_enter_source,
          refer_page_name, refer_page_sn, filter_items},
  searchEventInfo: {op, sub_op:"search", query, p_search, is_nres:1,
                     list_id, is_banner:0, srch_page_type:"search_result",
                     srch_enter_source, srch_scene_type:"main", search_method},
  filtersStore: {filterItems:"1:1", sortList, sortBy, actFilterList,
                 innerFiltersData, filterRegionPSearch, cacheOptions, ...},
}
```

`usePrefetchGoods: true` + `fsGoodsCount: 14` 说明**搜索页会预取 14 个商品**，
预取请求应该就是拿到 `goodsList` 的那个 —— 找到它就能解决搜索。

## 工具

`temu_parse.py` 提供 `get_rawdata(html)`：用**括号平衡法**提取 `window.rawData=` 后的完整 JSON。

⚠️ 不能用 `\{.*?\}` 非贪婪正则 —— 嵌套对象会在第一层就截断（我踩过这个坑）。

---

## 【专题】API 模式到底是怎么跑通的？（2026-10-29 实验结论）

`--mode api` 走的是 `POST /api/alexa/homepage/goods_list`。为了搞清楚"为什么浏览器内 fetch 能过、
curl_cffi 怎么都不行"，做了 6 组对照实验，结论如下。

### 实测数据

| 组 | 做法 | 结果 |
|---|---|---|
| A | 浏览器内 `fetch()`（基线） | ✅ 200, 64KB, 40 商品 |
| D | 浏览器内 `fetch(credentials:'omit')`（不带 cookie） | ✅ **200**（63852B） |
| B | curl_cffi + 浏览器全部 cookie + 全部请求头 | ❌ 429 |
| C | curl_cffi + 浏览器 cookie，去掉 anti-content | ❌ 429 |
| B2 | curl_cffi + 仅 anti-content 头，无 cookie | ❌ 429 |
| B3 | curl_cffi 无 cookie 无头 | ❌ 429 |
| F | curl_cffi × 9 种指纹 × HTTP/1.1&2（18 组） | ❌ **全部 429** |
| — | 浏览器内连发 5 次 | ✅ 5/5 全 200，每次 40 商品 |

### 结论一：不是 cookie 也不是 anti-content

D 组去掉 cookie 照样 200；B/C/B2/B3 各种 cookie 组合全 429。
**服务端根本不靠 cookie 或 anti-content 判这个接口**。

### 结论二：不是 TLS 指纹

F 组 18 种组合（chrome119/120/124/131/136 + safari17_0/safari15_3 + edge101 + firefox133，
各测 HTTP/1.1 与 HTTP/2）**全部 429**，而浏览器内 fetch 稳定 200。

⇒ 判定依据比 TLS 指纹更深：**浏览器进程内的真实行为轨迹**（JS 运行时、Cookie 写入顺序、
请求时序、真实网络栈特征等），curl_cffi 无论如何仿造都过不去。

### 结论三：`verifyAuthToken` 就是 verifyCode

浏览器加载首页时的导航链：

```
https://www.temu.com/
  → https://www.temu.com/?is_back=1
  → https://www.temu.com/bgn_verification.html?verifyCode=<40位随机码>&from=...
```

而 cookie 里：

```
verifyAuthToken = MbV14d3xtOpH-HYsNVOL7g39695b7429e6e01a3   ← 与 URL 的 verifyCode 完全一致
```

**`verifyAuthToken` cookie 值 == URL 上的 `verifyCode`** —— 这就是风控通关凭据。
`bgn_verification.html` 页本身是**不需要人工过验证码的**（124KB 直接 200），
说明风控在服务端已经给这次会话发了通行证。

但把浏览器的 verifyAuthToken + 全部 cookie 搬给 curl_cffi **依然 429**，
说明这个 token 是与「发起请求的客户端环境」绑定的，单独搬过去无效。

### 结论四：curl_cffi 的 challenge 是不稳定的

同一份代码、同一个 IP，不同时间的指纹表现会变：

```
chrome124   len=2889      ← challenge 页（本次被挡）
chrome131   len=376978    ← ✅ 真实首页
chrome120   len=2889      ← challenge
safari17_0  len=2889      ← challenge
```

之前测「chrome124 稳定 26/26」是那个时间窗的结论。
**实测建议：curl_cffi 用于抓页面 HTML 时要准备多个指纹轮换 + 重试**，
不能假定某个指纹永远有效。

### 最终实践形态

既然只有浏览器进程内能过，就老老实实用浏览器：

```python
ctx = chromium.launch_persistent_context(profile, headless=True, channel="chrome", ...)
page.goto("https://www.temu.com/", wait_until="domcontentloaded")   # 建立真会话
page.wait_for_timeout(10000)                                        # 等 JS 跑完写 cookie

result = page.evaluate("""async (body) => {
  const res = await fetch('/api/alexa/homepage/goods_list', {
    method: 'POST', credentials: 'include',
    headers: {'Content-Type': 'application/json;charset=UTF-8'},
    body: JSON.stringify(body)
  });
  return {status: res.status, text: await res.text()};
}""", {"offset":0,"count":120,"list_id":"","opt_id":None,"listId":"",
       "scene":"home","page_list_id":"","extend_fields":{}})
```

**关键点**：

1. 必须先 `goto` 首页让 JS 执行、写好 cookie（直接在 about:blank 上 fetch 会 `Failed to fetch`）
2. fetch 必须在**页面上下文**里（`page.evaluate`），不能是 Node 侧的 HTTP 请求
3. `credentials:'include'` 或 `'omit'` 都行（服务端不看 cookie）
4. 首页 `bgn_verification` 跳转是**正常流程**，不是被拦 —— 页面自动带上 verifyCode 通过

---

## 【专题】Temu 搜索/详情接口的登录墙（2026-11-02 逆向结论）

从 JS bundle 里挖出了 Temu 搜索和商品详情的**真实端点与参数**，
并用错误码对照确认了「能不能免登录调用」。

### 挖到的端点

**搜索**（`8226_*.js` / `6304_*.js`）：
```js
class au extends k.dD {
  search(e, t) {
    let a = e?.scene || eb.qr.SEARCH;
    let r = (0, ac.w)("/api/poppy/v1/search", {scene: a});
    return this.postRisk({url: r, params: {scene: a, pageSn: 10009, ...e}, ...});
  }
}
```
- 端点：`POST /api/poppy/v1/search`
- 参数：`{scene, pageSn:10009, offset, pageSize, listId, query, ...}`
- 响应：`result.data.goodsList[]`（字段是 camelCase：`goodsId` / `goodsName` / `thumbUrl` / `priceInfo{priceStr,currency}` / `salesTip` / `skuList` / `linkUrl` / `optId`）

**商品详情**（`2027_*.js` / `goods_*.js`）：
```js
{scene:"goods_detail_like", url:"/api/poppy/v1/goods_detail",
 apiParams:{pageSn:10032, pageElSn:207307, mainGoodsIds:[goodsId]}, mainGoodsId: goodsId}

// 另一个调用点
this.postRiskNew({url:"/api/poppy/v1/goods_detail", params: e})
```
- 端点：`POST /api/poppy/v1/goods_detail`
- 参数：`{pageSn:10032, pageElSn:207307, mainGoodsIds:[gid], mainGoodsId: gid, scene}`
- 响应：`result.data.goodsList[]` + `result.data.mainGoodsList[]` + `title` + `optList`

**其它已挖到的 poppy 端点**：
```
/api/poppy/v1/opt_list
/api/poppy/v1/title_bar_list
/api/poppy/v1/search_suggest
/api/poppy/v1/search_hot_query
/api/poppy/v2/search_activation
/api/poppy/v1/static/opt_list_all/en/100
```

### 错误码对照实验（决定性）

在**浏览器上下文**里逐个调接口（带真实 cookie / 真实会话）：

| 端点 | HTTP | error_code | 结果 |
|---|---|---|---|
| `/api/alexa/homepage/goods_list` | 200 | 1000000 | ✅ **免登录**，返回真实商品 |
| `/api/poppy/v1/search` scene=search | 403 | **40001** | 🔒 needLogin |
| `/api/poppy/v1/goods_detail` | 403 | **40001** | 🔒 needLogin |
| `/api/poppy/v1/search` scene=xxx（错 scene） | 200 | 403 "request illegal" | 参数非法（路径对） |
| `/api/poppy/v1/opt_list` | 200 | 403 "request illegal" | 参数非法 |
| `/api/poppy/v1/title_bar_list` | 200 | 403 "request illegal" | 参数非法 |

**关键区分**：
- `40001` = **needLogin** → 端点识别了、参数大致对，但**要求登录**
- `403 request illegal` = 参数错误（可试出来）
- `40002` = 缺 anti-token 签名
- `406008` = IP 风控

### 结论

**Temu 的关键词搜索与商品详情是「登录墙」保护的产品设计，不是可以靠伪造头绕过的技术门槛。**

免登录能用的只有 `/api/alexa/homepage/goods_list`（首页推荐位），
它**不接受关键词参数**（传 `scene:"search"` 会被忽略，返回的仍是首页商品 —— 实测确认）。

### 可行路径

| 方式 | 关键词 | 全字段 | 成本 |
|---|---|---|---|
| Apify actor | ✅ | ✅ | $0.01/条 |
| 本机浏览器 + 人工登录一次 | ✅ | ✅ | 免费 |
| 住宅代理 + 自建 | ✅ | ✅ | 代理月费 |

### 附：商品页在浏览器里**不跳登录**的条件

```
https://www.temu.com/goods.html?goods_id=601100218100590     ← 短 URL，不跳登录 ✅
https://www.temu.com/<超长SEO标题>-g-601100218100590.html    ← 长 URL，会跳登录 ❌
```
加上 `refer_page_sn=10032` / `refer_page_el_sn=207307` 等参数更稳。
即使用短 URL，页面仍会触发 `obtain_captcha`（点选验证码），因为**详情数据要登录才能取**。

---

## 【专题】为什么 Temu 免登录只能拿到「推荐页」？（2026-11-02 完整验证）

这是被问了好几次的问题，这里把**所有可能的绕过路径都试完了**，给出穷尽性结论。

### 结论一句话

**Temu 把「搜索 / 详情 / 筛选 / 推荐」四个能力全放在登录墙后面（`error_code=40001` needLogin），
只留了「首页推荐流」一个端点给未登录用户。而推荐流的设计目标就是「给你看点什么」，
不是「给你搜什么」——所以传任何关键词参数都没用。**

### 全部端点实测表（浏览器内、带真实会话）

| 端点 | HTTP | error_code | 能否用 |
|---|---|---|---|
| `/api/alexa/homepage/goods_list` | 200 | 1000000 | ✅ **唯一免登录** |
| `/api/seo/homepage_rec_goods_list` | 403 | 40002 | ❌ 缺 anti-token 签名 |
| `/api/poppy/v1/search` | 403 | **40001** | ❌ needLogin |
| `/api/poppy/v1/goods_detail` | 403 | **40001** | ❌ needLogin |
| `/api/poppy/v1/mall_home_recommend` | 403 | **40001** | ❌ needLogin |
| `/api/poppy/v1/opt_list` | 403/200 | 40001 / 500 | ❌ |
| `/api/promotion/open/recommend/promotion/goods/list` | 200 | — | ⚠️ 返回空（购物车场景） |

### 证据一：端点名自己就写着「推荐」

从 bundle（`1561_b110d62e3e0215246aee.js`）挖到：

```js
queryHomeGoodsList(e) {
  let {isUseSeoApi: t, ...r} = e || {};
  return this.postRisk({
    url: t ? "/api/seo/homepage_rec_goods_list" : "/api/alexa/homepage/goods_list",
    params: r, format: a, config: {useRawResponse: !0}
  })
}
```

`homepage_rec_goods_list` —— **rec = recommendation**。
同一 bundle 里的变量名也全是 rec：`this.recGoodsList` / `getRecGoodsList()` /
`isRecGoodsRequesting` / `reloadRecGoodsList()`。

**这个接口的语义就是「首页推荐位」，不是搜索。**

### 证据二：传关键词参数 → 内容变了，但与关键词无关

同一浏览器会话，连续调用同一接口：

| 调用 | 商品数 | 与基线重叠 | 标题含 `laundry`/`bag` |
|---|---|---|---|
| 基线（无关键词参数） | 40 | — | 1/40 |
| `extend_fields.search_key='laundry bag'` | 40 | 7/40 | **0/40** |
| 顶层 `keyword='laundry bag'` | 40 | 2/40 | 1/40 |
| `scene='search'` | 40 | 7/40 | 1/40 |

⇒ 参数**会**改变返回内容（个性化轮换），但**没有一条与关键词相关**。
说明 `search_key`/`keyword`/`scene` 这些字段在该端点上**无语义**，只是扰动了推荐流。

### 证据三：`opt_id` / `list_id` 也不是搜索入口

```
opt_id=None    → 40 条，与其它组合重叠仅 1%
opt_id=1       → 40 条，与 opt_id=2/3/10007/20016/30032 内容完全相同
```
说明：`opt_id` **传任意非空值都会走另一个推荐分支**，但具体值无效（走默认）。
真实首页请求的参数是：
```json
{"offset":0,"count":120,
 "list_id":"0029b340b4384b3c93898c7629b93332",   // 32位 hash，首页推荐位标识
 "listId":"0029b340b4384b3c93898c7629b93332",
 "scene":"home",
 "page_list_id":"cca57035becc48919fa63840059f0fc3",
 "extend_fields":{},
 "page_el_sn":200024,"page_sn":10005}
```
用真实 hash / 随机 hash / 换 page_sn 各种组合实测，**两两重叠率都是 1-8%** ——
无论怎么拼，返回的都是随机推荐，没有一组与关键词相关。

### 证据四：类目页也不行

```
/category-shoes.html        200  len=378074  rawData=True
/category-home-supplies.html 200  len=378103  rawData=True
/c-10007.html               200  len=378074  rawData=True
```
三个不同类目 URL **返回几乎相同长度的页面**（SEO 兜底到首页），
且 `optList`/`optId`/`categoryId` 在 SSR 里**出现 0 次**（类目数据全是客户端运行时加载）。

### 证据五：搜索页 SSR 里没有搜索结果

搜索页 HTML 368KB，`window.rawData` 存在，但：
- `optList` 出现 **0** 次
- `optId` 出现 **0** 次
- `categoryId` 出现 **0** 次
- `goodsList` 为空数组

搜索结果必须由前端运行时调 `/api/poppy/v1/search` 拉 —— 而那个要登录。

### 所以怎么办

| 想要 | 方案 | 成本 |
|---|---|---|
| Temu 关键词搜索 + 详情 | Apify actor | $0.01/条 |
| Temu 关键词搜索 + 详情 | 本机浏览器模式，人工过一次登录 | 免费 |
| 只要**大量真实商品**（不按关键词） | **免登录累积模式**（见下） | 免费 |
| Amazon 关键词 + 全字段 | 直接用 Amazon 模式 | 免费 |

### 增量：免登录累积模式（本次新增）

既然每次调用返回的推荐都不同（重叠仅 1-8%），**多轮累积去重就能拿到远超单轮的量**：

```python
while len(items) < limit and round_no < 12:
    body = {...}
    if round_no > 1:
        body["list_id"] = md5(f"{pid}-{round}-{time}")   # 换推荐源
        body["listId"]  = 同一个 hash
    ...累积去重...
```

实测：**100 个不重复商品，2 轮凑齐**（40 + 76 → 去重 100），图片 99 张。

已集成进 `collectors.py` 的 `temu_api` 模式，界面上直接填数量即可（上限 12 轮 × 40 条 ≈ 480）。
---

## 【专题】Temu 登录 + 防封 IP（2026-11-02）

### 登录后能拿到什么

| 能力 | 免登录 | 登录后 |
|---|---|---|
| 关键词搜索 `poppy/v1/search` | ❌ 40001 | ✅ |
| 商品详情 `poppy/v1/goods_detail` | ❌ 40001 | ✅ |
| 五点描述 / 全部附图 / 销量 | ❌ | ✅ |
| 首页推荐流 | ✅ | ✅ |

**关键实测**：未登录时打开搜索页，页面卡在 `bgn_verification.html`，
**前端 JS 根本不发 `/poppy/v1/search` 请求**（21 个 API 响应里没有它），
其中 `/api/passport/token/touch` 返回 40001 —— 说明服务端在检查登录态，
前端判断未登录后直接不请求数据。

### 关键实现思路：拦截页面自己的响应

不去猜参数、不去伪造 anti-token（native bridge 生成的，纯 JS 伪造不了），
而是让**页面自己去发请求**，我们只在 `response` 事件里捞 JSON：

```python
page.on("response", on_resp)   # 只关心 /poppy/v1/search 和 /poppy/v1/goods_detail
```

好处：
- 签名、cookie、referer、session 全由浏览器维护
- 参数由页面自己决定（不用逆向猜）
- 登录后立刻就能拿到完整数据

实现见 `temu_browser.py`（`_Interceptor` 类）。

### 登录态复用

profile 目录持久化（默认 `.browser_profile/`），登录一次长期复用。

**登录是风控权重最高的动作 —— 必须尽量少做。**
换机器时把整个 profile 目录拷过去即可：

```bash
rsync -av .browser_profile/ other-pc:/path/to/temu_scraper/
```

### 防封 IP：六层防护

| 层 | 措施 | 成本 |
|---|---|---|
| 1 | **控制频率**（随机延迟 1.5-30s 可配） | 免费 |
| 2 | **住宅代理**（`TEMU_PROXY`） | 代理月费 |
| 3 | 行为拟真（真实 Chrome / 滚动 / 随机等待） | 免费 |
| 4 | 遇验证码停下人工过，不硬刚 | 免费 |
| 5 | 错误码识别与降速（406008 立刻停） | 免费 |
| 6 | 账号卫生（账号↔IP 绑定，不多 IP 乱跑） | 免费 |

**实测数据点**：Amazon 一次跑 100 条就触发 `AmazonBlocked: 503` ——
突发高频必被标记。Temu 同理。

**代理轮换策略**：不要每个请求换 IP（更像机器人），
建议一个 IP 连续用 20-30 条再换（sticky session），且账号固定 1-2 个 IP。

### 环境变量

```bash
TEMU_PROFILE=/path/to/profile   # 登录态目录
TEMU_PROXY=http://u:p@h:port    # 住宅代理
TEMU_DELAY_MIN=2.5              # 最小间隔
TEMU_DELAY_MAX=7                # 最大间隔
```

### 重要提醒

**给账号不如用 Apify**：
- Apify $0.01/条（80 条 $0.8），比住宅代理月费（$20-50）便宜
- 不用登录、不用代理、不用操心风控
- 账号被风控标记 = 账号废了，这个风险不该由你承担

完整方案见项目根目录 `防封IP与登录方案.md`。
