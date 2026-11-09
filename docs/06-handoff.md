<div align="center">

**[← 返回目录](index.md)** · [01-status-overview](01-status-overview.md) · [02-temu-antibot](02-temu-antibot.md) · [03-temu-api-reverse](03-temu-api-reverse.md) · [04-amazon-practice](04-amazon-practice.md) · [05-pitfalls](05-pitfalls.md) · [06-handoff](06-handoff.md) · [07-GitHub项目调研](07-GitHub项目调研.md)

</div>

---
# 06 · 换机续作指南

> 目标：在另一台电脑上从零复现，或直接继续未完成的工作。

---

## 一、最快路径（3 条命令）

```bash
# 方式 A：从 GitHub clone（推荐，代码与文档同步更新）
git clone https://github.com/tom982346-ctrl/temu-amazon-scraper.git
cd temu-amazon-scraper
python3 setup.py
AMZ_KEYWORD="laundry bag" AMZ_LIMIT=80 vendor/amazon-scraper/.venv/bin/python amazon_collect.py

# 方式 B：用离线包（zip 含实测样本与全部图片）
cd ~/Downloads && unzip temu-amazon-scraper.zip && cd temu_scraper
python3 setup.py
AMZ_KEYWORD="laundry bag" AMZ_LIMIT=80 vendor/amazon-scraper/.venv/bin/python amazon_collect.py
```

> `setup.py` 会把 amazon-scraper clone 到包内 `vendor/amazon-scraper`，不污染系统。

---

## 二、环境要求

| 项 | 要求 | 检查 |
|---|---|---|
| Python | ≥ 3.10（实测 3.13.12） | `python3 -V` |
| Git | 任意版本 | `git --version` |
| Chrome | **仅 Temu browser 模式需要** | `/Applications/Google Chrome.app` |
| 网络 | 能访问 amazon.com / temu.com | — |
| 代理 | **注意**：如果新机器有 `HTTP_PROXY` 环境变量，必须清掉 | `echo $HTTP_PROXY` |

自检：
```bash
python3 setup.py --check
```

---

## 三、包里有什么

```
temu-amazon-scraper/
├── README.md                  ← 主文档（先读这个）
├── 选品抓取方案.md             ← 方案 + GitHub 开源项目调研
├── setup.sh                   ← 一键环境重建
├── requirements.txt
├── amazon_collect.py          ← Amazon 采集器（已跑通）
├── temu_collect.py            ← Temu 采集器（3 模式）
├── temu_parse.py              ← rawData 解析工具
├── diagnose_captcha.py        ← 验证码诊断脚本
├── wiki/                      ← 逆向成果 + 踩坑记录（6 页）
│   ├── 00-索引.md
│   ├── 01-现状总览.md
│   ├── 02-Temu-反爬拆解.md
│   ├── 03-Temu-API-逆向.md
│   ├── 04-Amazon-实战.md
│   ├── 05-踩坑清单.md
│   └── 06-换机续作.md
├── output/                    ← Temu 实测样本（40 条 + 40 图）
│   ├── products.csv
│   ├── products.json
│   └── images/<goods_id>/*.jpg
└── output_amazon/             ← Amazon 实测样本（20 条 + 185 图）
    ├── products.csv
    ├── products.json
    └── images/<asin>/*.jpg
```

**不含**：`.venv/`、`node_modules/`、`.browser_profile/`（体积大且可重建），
`setup.sh` 会重新拉取。

---

## 四、继续 Temu 的三个待办

按优先级：

### 待办 1：找到商品详情 API 端点（收益最大）

详情页五点描述/附图都在这个接口里。

**已排除**（全部 403/429，见 wiki 03）：
```
/api/alexa/goods/detail  /api/alexa/goods/detail_v2
/api/goods/detail        /api/poppy/v2/goods/detail
/api/bg-bff-api/goods/detail  /api/alexa/odin/goods/detail
/api/alexa/pc/goods/detail    /api/phantom/xg/goods/detail
/api/goods/goods_detail  /api/alexa/goods/goods_detail
/api/poppy/v2/goods/detail_v2 /api/bg-barbera-api/goods/detail/pc
```

**下一步**：
1. 取商品页的 JS bundle 列表（方法见 wiki 03）
2. 找 `goods` 相关的 chunk
3. grep `/api/` 路径 + `goodsGallery` / `goodsProperty` / `bulletDesc`

```bash
# 商品页 bundle（带入口参数避免跳登录）
curl -s 'https://www.temu.com/goods.html?goods_id=601100218100590&refer_page_sn=10032' \
  -H 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36' \
  -o /tmp/goods.html
grep -oE '"https://static\.kwcdn\.com/m-assets/assets/modernjs/[^"]+\.js"' /tmp/goods.html | sort -u
```

### 待办 2：找到搜索页的预取请求

搜索页 rawData 里有 `usePrefetchGoods: true` + `fsGoodsCount: 14`，
说明前端会预取 14 个商品。找到那个请求 = 搜索打通。

**思路**：在**能渲染搜索页的环境**里拦截 XHR。
当前 headless 会被踢登录，但 `curl_cffi` 层不跳 —— 可以试：
用 curl_cffi 拿到的 SSR HTML，在浏览器里 `document.write` 进去，让前端 JS 接管，
这样 JS 环境的 cookie 与 curl_cffi 拿到的页面一致（region=37 等），可能不触发 isRobot。

### 待办 3：Apify 通路（最省事，5 分钟）

```bash
export APIFY_TOKEN=你的token
.venv/bin/python temu_collect.py --mode apify --keyword "laundry bag" --limit 80 --images
```
80 条约 $0.8。字段由 actor 提供，含图集与描述。

---

## 五、继续 Amazon（随时可跑）

Amazon 已经通了，随时换关键词跑：

```bash
AMZ_KEYWORD="shoe bag" AMZ_LIMIT=80 \
  $PWD/vendor/amazon-scraper/.venv/bin/python amazon_collect.py
```

支持的其它端点（`amazon_collect.py` 里只用了一个，其余可直接调）：
```
http://127.0.0.1:PORT/best-sellers?category=...
http://127.0.0.1:PORT/deals?...
http://127.0.0.1:PORT/categories?...
http://127.0.0.1:PORT/sellers/details?...
```

---

## 六、下一步建议（按 ROI 排序）

| 优先级 | 动作 | 产出 |
|---|---|---|
| ⭐⭐⭐ | Amazon 换 5 个类目关键词各跑 80 条 | 跨类目选品对比表 |
| ⭐⭐⭐ | 申请 Apify token，跑 Temu 80 条 | Temu 全字段数据 |
| ⭐⭐ | 找 Temu 详情 API 端点 | 自建 Temu 详情抓取 |
| ⭐ | 配住宅代理 | Temu 自建全自动 |
| ⭐ | 找搜索预取请求 | Temu 关键词搜索自建 |

---

## 七、已知限制备忘

- **Temu 搜索页在浏览器层必被踢登录**（服务端 302），已验证 10+ 种绕过方式全部失败
- **Temu 详情接口需 anti-token 签名**，纯 JS 无法伪造
- **Amazon 偶发空返回**，已加 3 次重试；批量跑时建议保留重试逻辑
- **新机器若设了 HTTP_PROXY**，`curl_cffi`/`urllib` 会走代理导致 502 —— `setup.sh` 会清
