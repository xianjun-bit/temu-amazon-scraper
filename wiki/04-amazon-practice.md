# 04 · Amazon 实战

## 采用项目

**`omkarcloud/amazon-scraper`** — ★258 · MIT · 2026-10 仍在更新 · 无需 API key · 无需代理 · 21 个端点

```bash
git clone --depth 1 https://github.com/omkarcloud/amazon-scraper /tmp/amz/amazon-scraper
cd /tmp/amz/amazon-scraper && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

依赖：`bottle` `cheroot` `curl_cffi` `beautifulsoup4` `lxml` `marshmallow`

**为什么选它**：字段最全（含 bullets / variations / customers_say / videos / top_reviews），
且不用代理、不用 key、不用登录。README 自称"validated 2026-09-22 from direct Indian egress
and residential proxy"，实测直连完全可用。

## 21 个端点

```
/products/details     /search                /search/autocomplete
/products/reviews     /products/offers       /products/variations
/products/bulk        /products/lookup       /best-sellers
/best-sellers/categories                      /deals
/categories           /categories/tree        /categories/products
/sellers/details      /sellers/feedback      /sellers/products
/influencers/details  /influencers/posts     /influencers/posts/products
/scrape               /health                /
```
每个都有 `/amazon` 前缀变体（如 `/amazon/products/details`）。

## 用法

```bash
# 起服务（注意：必须清代理环境变量）
cd /tmp/amz/amazon-scraper
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy
PORT=8770 .venv/bin/python run.py

# 调用
curl "http://127.0.0.1:8770/products/details?product=B07QSFHT27"
curl "http://127.0.0.1:8770/search?query=laundry+bag&country=US&page=1"
```

`amazon_collect.py` 已经把这些包成**同进程内起服务**（不用手动开），直接跑即可。

## 详情接口返回结构（顶层 34 个字段）

```json
{
  "asin": "B00IJES7W2",
  "title": "Nylon XL Laundry Bag, Large Capacity with Locking Drawstring...",
  "link": "https://www.amazon.com/dp/B00IJES7W2",
  "brand": {"name": "Handy Laundry", "byline": "...", "link": "...", "store_link": "..."},
  "authors": null,
  "price": {"amount": 6.99, "currency": "USD", "list_price": null,
            "savings_percent": null, "savings_amount": null, "unit_price": null},
  "deal_badge": null,
  "coupon": null,
  "availability": {"text": "In Stock", "is_in_stock": true, "quantity_left": null},
  "buybox": {"seller": {"name": "...", "id": "...", "link": "..."},
             "ships_from": null, "is_fulfilled_by_amazon": false, "is_sold_by_amazon": false},
  "delivery": {"text": "...", "fastest_text": "..."},
  "is_prime": false,
  "rating": {"average": 4.6, "count": 14305,
             "histogram": {"5_star": 80, "4_star": 12, "4_star": 4, "2_star": 1, "1_star": 3}},
  "bought_past_month": 4000,
  "badges": {"is_best_seller": false, "is_amazons_choice": true, ...},
  "categories": [{"name": "Home & Kitchen", "link": "...", "node_id": "1055398"}],
  "best_sellers_rank": [{"rank": 1714, "category": "Home & Kitchen", "link": "..."}],
  "bullets": ["EXCEPTIONAL DURABILITY - ...", "GENEROUS SIZE - ...", "..."],   ← 五点描述
  "overview": {"brand": "Handy Laundry", "material": "Nylon", "color": "Black",
               "product_dimensions": "40\"L x 30\"W x 40\"H",
               "special_feature": "Durable,Portable,Resistant",
               "load_capacity": "60 pounds", "closure_type": "Drawstring",
               "shape": "Oblong", "number_of_items": "1"},
  "description": null,
  "aplus_description": "Product description ...",
  "details": {"item_weight": "6.72 ounces", "size": "30\" x 40\"", ...},
  "identifiers": {"upc": "021455050051", "model_number": "HL30X40Black-F"},
  "images": [{"link": "https://m.media-amazon.com/images/I/xxx._AC_SL1500_.jpg",   ← 主图 1500px
              "thumbnail": "...", "large": "...", "variant": "MAIN"}, ...],       ← 30 张
  "videos": [{"title": "...", "link": "...m3u8", "thumbnail": "...", "duration_seconds": 39}],
  "videos_count": 7,
  "variations": {"parent_asin": "B0CQRNJQ3G", "current_asin": "B00IJES7W2",
                 "dimensions": [{"key": "color_name", "name": "Color", "values": [13种]},
                                {"key": "size_name", "name": "Size", "values": [...]}]},
  "customers_say": {"summary": "AI 总结的用户评价..."},
  "top_reviews": [{"id": "...", "title": "...", "rating": 5.0, "date": "2026-09-02",
                   "text": "...", "country": "United States"}],
  "has_inline_reviews": true,
  "important_information": null,
  "warranty": null,
  "country": "US",
  "domain": "www.amazon.com"
}
```

### 字段名要点（我踩过）

| 想拿 | 正确字段名 | 踩过的错 |
|---|---|---|
| 五点描述 | `bullets`（数组） | 试过 `features`/`bullet_points`/`description` 都 null |
| 附图 | `images`（**数组**，每项含 link/thumbnail/large/variant） | 试过当 dict 取 `primary`/`hi_res` → 0 张 |
| 规格 | `overview`（结构化）+ `details`（字典） | — |
| 月销量 | `bought_past_month` | — |
| 变体 | `variations.dimensions[].values` | — |

## 搜索接口

```
GET /search?query=laundry+bag&country=US&page=1
```
响应：
```json
{"count": 30000, "per_page": 48, "current_page": 1, "total_pages": 7,
 "next": "...page=2", "previous": null,
 "query": "laundry bag", "country": "US", "domain": "www.amazon.com",
 "results": [ {...}, ... ]}
```

支持 23 个 marketplace（com/co.uk/de/fr/it/es/ca/jp/...）。
`amazon.co.jp` 和 `amazon.com.au` 只接受本国 IP，其它站点直连都行。

## 图片下载

`m.media-amazon.com` 直链可下，无需鉴权。`images[].link` 是 `_AC_SL1500_`（1500px 高清），
`large` 是原尺寸。实测 185 张全部落地。

## 稳定性的两个坑

**① 偶发空返回** —— 某个 ASIN 详情第一次返回空（无 title）。
解决：`details()` 加 3 次重试 + 递增 sleep。20/20 全部补齐。

**② 环境代理** —— 见 [05-踩坑清单](05-踩坑清单.md)。
