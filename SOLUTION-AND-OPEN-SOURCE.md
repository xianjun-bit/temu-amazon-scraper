# Temu / Amazon 跨平台选品数据抓取方案

> 实测日期：2026-10-26 · 环境：macOS Apple Silicon · 目标：输入关键词 → 找出 80 个商品 → 逐个抓取主图/附图/五点描述/价格

---

## 一、先说结论（实测踩坑结果）

我把你给的那个商品页从头到尾实测了一遍，核心发现是 **Temu 的反爬有 4 道门**，纯 HTTP 请求全被挡死：

| 尝试路径 | 结果 | 原因 |
|---|---|---|
| `curl` / `requests` 直连 | ❌ 3KB 混淆 JS 页 | **门1：JS Challenge**（注入 `window.challenge`，加载 `static.kwcdn.com/.../fea85011-*.js`） |
| 换 UA（Googlebot / bingbot / Android / 移动端） | ❌ 照样 challenge | UA 伪装无效，challenge 看 TLS + JS 指纹 |
| `curl_cffi`（TLS 指纹伪装） | ✅ **26/26 稳定通过** | 绕过门1，拿到 396KB 完整 SSR 页面 |
| 解析 SSR HTML 找商品数据 | ❌ **空壳** | **门2**：SSR 只有骨架，`store.goods = {}`，数据全走 XHR |
| 直连 XHR API | ❌ 429 (`error_code:406008`) | **门3**：IP 级风控 + anti-token 签名，连首页已知可用 API 都被拦 |
| Playwright 浏览器渲染 | ⚠️ 触发**滑块 / 点选验证码** | **门4**：真实风控，需要住宅代理 + 登录态 |
| 浏览器 headed 模式 | ❌ 被踢 `login.html` | 美国区 `region=211` 强制登录（`login.policy_one`） |

**因此：纯自建方案在当前 IP 下不可行**，必须解决「住宅代理 + 登录态」或「用现成的托管服务」。

---

## 二、GitHub 开源项目调研（已 clone 实读代码）

### Temu 方向

| 项目 | ★ | 语言 | 实读结论 |
|---|---|---|---|
| [`n1ceh4t/Temu-Item-Scraper`](https://github.com/n1ceh4t/Temu-Item-Scraper) | 17 | Python | **思路值得抄**：解析 `application/ld+json`（Schema.org Product，含 name/price/image/description）+ 从搜索页 `a[aria-label=""]` 提取商品链接。但 2024-08 后未更新，走的还是 `requests` + Android UA，**现在必然被 challenge 挡死** |
| [`yancyfeng999-star/cross-border-ecommerce-scraper`](https://github.com/yancyfeng999-star/cross-border-ecommerce-scraper) | 8 | Python | **架构最适合你**：统一 `BaseScraper` 接口，支持 10 平台（Amazon/Shopee/Lazada/eBay/AliExpress/Temu/Walmart/Etsy/TikTok Shop/MercadoLibre），CLI 调用，代理池已接。**但 Temu 的 selector 是硬编码的老 class 名（`_2L_OG`/`_2de0t`），已失效** |
| [`littleyellowbicycle/temu-scraper`](https://github.com/littleyellowbicycle/temu-scraper) | 3 | Python | 1183 行，用 **CloakBrowser**（真人行为模拟）绕过检测，含图片/价格/规格解析。**依赖 CloakBrowser 这个商业闭源库**，且未跑通当前风控 |
| [`apivault-labs/n8n-nodes-apivault-temu`](https://github.com/apivault-labs/n8n-nodes-apivault-temu) | 3 | TS | n8n 节点，**本质是 Apify actor 的封装**（`apivault_labs~temu-product-scraper`），$3/1000 产品 |

### Amazon 方向（★数最高的都在这）

| 项目 | ★ | 结论 |
|---|---|---|
| [`oxylabs/amazon-scraper`](https://github.com/oxylabs/amazon-scraper) | 3412 | 官方可读代码库，配套 3 个教程仓库（how-to-scrape-amazon-prices 2093★、how-to-handle-amazon-captcha 1764★、amazon-asin-scraper 244★）。**免费 API 是试用引流，重点看它怎么处理 captcha** |
| [`tducret/amazon-scraper-python`](https://github.com/tducret/amazon-scraper-python) | 878 | 非官方客户端，纯 requests，最简洁的参考实现 |
| [`drawrowfly/amazon-product-api`](https://github.com/drawrowfly/amazon-product-api) | 778 | 搜索结果 + 评论抓取 |
| [`omkarcloud/amazon-scraper`](https://github.com/omkarcloud/amazon-scraper) | 258 | **MIT 协议 + 2026-10 还在更新**，号称无 API key 无代理无限量，宣称支持商品详情/价格/评论/畅销榜。**最值得先试的一个** |
| [`scrapehero-code/amazon-scraper`](https://github.com/scrapehero-code/amazon-scraper) | 444 | 简洁的 Scrapy 商品+价格抽取 |
| [`geekan/scrapy-examples`](https://github.com/geekan/scrapy-examples) | 3258 | Scrapy 官方示例集，含 Amazon spider |
| [`dynamohuang/amazon-scrapy`](https://github.com/dynamohuang/amazon-scrapy) | 297 | 畅销榜详情 + 最低价追踪 |

### 通用爬虫基建（强烈推荐，比自己写反检测靠谱）

| 项目 | ★ | 为什么值得看 |
|---|---|---|
| [`unclecode/crawl4ai`](https://github.com/unclecode/crawl4ai) | **86k** | Apache-2.0，为 LLM/Agent 设计的爬虫，**内置 stealth 模式**，能输出结构化 Markdown/JSON，天然适合喂给 AI 做选品分析 |
| [`nanobrowser/nanobrowser`](https://github.com/nanobrowser/nanobrowser) | 14k | Apache-2.0，**复用你自己的已登录浏览器 profile**，正好解决 Temu 的登录态问题 |
| [`oxylabs/how-to-handle-amazon-captcha`](https://github.com/oxylabs/how-to-handle-amazon-captcha) | 1764 | Amazon captcha 处理方法论 |

---

## 三、三套落地方案（按推荐度排序）

### 方案 A：Apify 现成 actor（最快，强烈推荐先跑）

Apify Store 上有 **19 个 Temu actor**，活跃度极高（2026-10 仍在跑），且明确**支持关键词搜索**：

| Actor | ID | 运行次数 | 能力 |
|---|---|---|---|
| **`crw/temu-products-scraper`** ⭐ | `dXoeNAkKt3ZRfOKvx` | 19,244 | **按搜索关键词抓**，支持排序（relevance/销量/最新/价格），价格/折扣/评分/销量/图片 |
| `amit123/temu-products-scraper` | `LTBzVVq592mKgR6lU` | 39,553 | 商品数据+价格 |
| `selleraim.com/temu-product-scraper` | `H6eXzUL6u9mTPYhYC` | 6,667 | **搜索/类目/商品页三合一，12 国站点，无登录无 cookie，代理已含**，最多 1500 结果/关键词 |
| `apivault_labs/temu-product-scraper` | `4kqabNhJmz8CRgV5z` | 10,837 | 14 层选品情报：价格、需求分、利润测算、变体、热销分、Shopify CSV 导出 |
| `scrapeunblocker/temu-product-scraper` | `uLfBoeF5Hb68huKPf` | 637 | $3/1000，反封禁 |

**成本估算**：80 个商品 × $0.003 = **$0.24**，Apify 免费额度足够（每月 $5 试用金）。

**调用方式**（无需登录、只等结果）：
```bash
curl -X POST "https://api.apify.com/v2/acts/crw~temu-products-scraper/runs?token=$APIFY_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"searchKeyword":"laundry bag","maxItems":80,"sortBy":"relevance"}' \
  -X POST "https://api.apify.com/v2/acts/crw~temu-products-scraper/run-sync-get-dataset-items?token=$APIFY_TOKEN" \
  -H 'Content-Type: application/json' -d '{"searchKeyword":"laundry bag","maxItems":80}' > temu_80.json
```

### 方案 B：自建（curl_cffi + 住宅代理 + 登录态）

已验证可用的组件拼装：
1. **URL 列表**：`curl_cffi` + `chrome124` 指纹 → 100% 过 challenge（实测 26/26）
2. **数据渲染**：住宅代理 + Playwright `launchPersistentContext`（复用登录态 cookie）+ 人工过一次验证码
3. **图片下载**：`img.kwcdn.com` CDN **无鉴权可直接下**（实测 200），本地并发下载按 goods_id 分目录

已写好的脚手架在 `temu_scraper/temu_scrape.py`：
```bash
cd temu_scraper
.venv/bin/python temu_scrape.py search "laundry bag" --limit 80 --images
.venv/bin/python temu_scrape.py urls urls.txt --limit 80 --images
```
输出：`output/products.csv`（含 goods_id/标题/价格/销量/评分/图片URL/五点描述/规格）、`output/products.json`、`output/images/<goods_id>/`。

**还缺的两块**：① 住宅代理（Bright Data / ScraperAPI 之类）② 一个 Temu 账号的登录态（`login.policy_one` 对 region 211 是强制的）。

### 方案 C：Crawl4AI / Nanobrowser 通用方案

- **Crawl4AI**：86k★，Apache-2.0，内置 stealth，`AsyncWebCrawler` 直接出结构化结果。可以当"能爬到什么就爬什么"的通用底座，配合 LLM 做选品分析。
- **Nanobrowser**：14k★，**直接复用你本机 Chrome 的已登录 profile**——这是解决 Temu 登录墙最优雅的思路。

---

## 四、针对 Amazon 的建议

Amazon 的开源方案成熟得多（`oxylabs` 系列 3.4k★、8 个 Scrapy 项目可选），但注意：
- **`omkarcloud/amazon-scraper`**（MIT，2026-10 更新，无 API key 无代理）建议第一个试
- Amazon 的 **Product Advertising API (PA-API)** 走官方授权最稳，但要联盟账号 + 申请，且 2026 年 PA-API 已基本被 Amazon 弃用/限流，实操上大家还是走爬虫或 Apify
- Amazon 有 Product Advertising API 之外还有 **Amazon Selling Partner API (SP-API)**，但那是给卖家管自己店铺的，不适合选品
- Apify 上 Amazon actor 数量是 Temu 的几十倍，`apify/amazon-crawler` 等是标准选择

---

## 五、给你的一句话建议

**先花 2 分钟跑 Apify 方案 A**（80 个商品不到 $0.25，无需代理无需登录，30 秒出结构化 JSON，含主图/附图/价格/销量/评分），确认数据字段满足选品需求后，再决定要不要为长期批量抓取投入住宅代理 + 登录态去自建。

如果要走自建，告诉我你手头有没有：① 住宅代理（Bright Data / Oxylabs / ScraperAPI 都行）② Temu 账号，我把这套脚手架补完成生产可用的版本。

---

## 附：本目录文件说明

```
temu_scraper/
├── temu_scrape.py      # 主抓取器（curl_cffi 突破 challenge + 解析 + 图片下载 + CSV/JSON 导出）
├── temu_parse.py       # rawData 括号平衡解析工具（SSR 数据提取）
├── probe*.js / probe*.py # 14 个探针脚本，记录了本次全部实测过程
├── test_curl_cffi.py   # curl_cffi 指纹伪装对比测试
├── probe_stability.py  # 反爬命中率稳定性测试（26/26 通过）
└── .venv/              # Python 环境（curl_cffi 0.17.0）
```
