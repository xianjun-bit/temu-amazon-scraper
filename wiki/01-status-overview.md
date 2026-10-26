# 01 · 现状总览

> 实测日期：2026-10-26 · 环境：macOS Apple Silicon (arm64) · Python 3.13.12

## 能力矩阵

| 能力 | Amazon | Temu |
|---|---|---|
| 绕过 JS Challenge | ✅ curl_cffi | ✅ curl_cffi（26/26） |
| 关键词搜索 | ✅ 30000 结果/关键词 | ⚠️ 需 anti-token 签名 |
| 商品列表（标题/价格/主图） | ✅ | ✅（首页推荐位可拿） |
| 商品详情（五点/附图/规格） | ✅ 20/20 | ❌ 服务端强制登录 |
| 图片下载 | ✅ 185 张实测 | ✅ CDN 无鉴权 |
| 评分/销量/变体 | ✅ | ❌（在详情接口里） |
| 是否需要登录 | ❌ | ✅（region 211 policy_one） |
| 是否需要代理 | ❌ | ✅（IP 已被标记） |
| 成本 | 免费 | 免费但受限 / Apify $0.01/条 |

## 实测数据

### Amazon（关键词 "laundry bag"，20 条）

```
字段完整度：
  title / price / rating / review_count / brand / seller / in_stock    20/20
  bullet_count（五点描述）                                             20/20
  image_count（附图）                                                  18/20
  bought_past_month / overview / details / variations / customers_say  19/20
  categories / videos_count                                            20/20
图片下载 185 张
```

### Temu（首页 goods_list API，40 条）

```
goods_id / title / price / currency / images / url    40/40
价格区间 $2.71 – $379.86
图片 40 张（2222×2222 JPEG 原图）
```

## 结论

**优先用 Amazon 满足选品需求**（免费、全字段、无限量）。
**Temu 作为补充**：要么用 Apify（$0.8/80条），要么配住宅代理走 browser 模式。

## 各方案成本对比

| 方案 | 80 个商品成本 | 字段完整度 | 稳定度 |
|---|---|---|---|
| Amazon 自建（已实现） | $0 | 100% | 高 |
| Temu + Apify `crw~temu-products-scraper` | $0.8 | 高 | 高 |
| Temu + Apify `selleraim.com~temu-product-scraper` | ~$0.5 | 高 | 高 |
| Temu 自建 + 住宅代理 | 代理月费 | 100% | 中（IP 敏感） |
| Temu 自建纯免费 | $0 | 仅列表页字段 | 低 |
