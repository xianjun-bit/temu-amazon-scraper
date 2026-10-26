# Wiki · 索引

> 本项目所有逆向成果与踩坑记录的入口。
>
> 仓库：https://github.com/tom982346-ctrl/temu-amazon-scraper**这些内容全部来自 2026-10-26 的实际抓取**，不是推测。

## 页面

| 页面 | 内容 |
|---|---|
| [01-现状总览](01-status-overview.md) | 哪些能跑通、哪些被锁、结论 |
| [02-Temu-反爬拆解](02-temu-antibot.md) | 4 道门、错误码语义、完整对抗方案 |
| [03-Temu-API-逆向](03-temu-api-reverse.md) | 端点、参数、JS bundle 挖掘方法 |
| [04-Amazon-实战](04-amazon-practice.md) | 采用项目、21 端点、字段结构、踩坑 |
| [05-踩坑清单](05-pitfalls.md) | 环境代理、端口冲突、验证码死循环… |
| [06-换机续作](06-handoff.md) | 在另一台电脑上继续的完整步骤 |

## 一句话现状

- **Amazon**：完全跑通，关键词 → 80 商品 → 五点描述 + 全部附图 + 规格 + 变体 + 销量，免费
- **Temu**：列表页（标题/价格/主图）能拿；详情页（五点/附图）被服务端登录墙 + anti-token 签名锁住，需住宅代理或 Apify
