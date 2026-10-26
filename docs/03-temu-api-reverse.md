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
