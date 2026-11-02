# Temu 登录 + 防封 IP 完整方案

> 2026-11-02 · 基于实测（浏览器内拦截 + 错误码对照）

---

## 一、先回答两个问题

### Q：给你账号登录能干什么？

**能拿到 Temu 关键词搜索 + 商品详情全字段**（五点描述 / 全部附图 / 规格 / 销量）。

技术上已经验证清楚了：

| 能力 | 免登录 | 登录后 |
|---|---|---|
| 关键词搜索（`poppy/v1/search`） | ❌ `40001 needLogin` | ✅ |
| 商品详情（`poppy/v1/goods_detail`） | ❌ `40001 needLogin` | ✅ |
| 五点描述 / 全部附图 / 销量 | ❌ | ✅ |
| 首页推荐流（`homepage/goods_list`） | ✅ | ✅ |

**关键实现思路变了**：不再是「自己伪造请求」，而是**拦截页面自己的 API 响应**。

```python
# 页面自己发请求 -> 自带 anti-content 签名（native bridge 生成，纯 JS 伪造不了）
# 我们只在 response 事件里把 JSON 捞出来
page.on("response", on_resp)
```

这样登录后：
- 不需要猜参数（页面自己知道该传什么）
- 不需要伪造签名（页面自己会带）
- 不需要模拟 cookie（浏览器自己维护）

实现见 `temu_browser.py`。

### Q：怎么避免封 IP？

见下面第三节，那里有具体参数和推荐配置。

---

## 二、登录怎么走

### 步骤

```bash
cd /Users/liuxianjun/WorkBuddy/2026-10-26-15-03-19/temu_scraper

# ① 有图形界面的机器上跑（必须 headed，headless 过不了登录/验证码）
.venv/bin/python collectors.py temu_browser "laundry bag" 80

# ② 浏览器窗口会弹出来
#    - 跳登录页 -> 手动登录一次（账号密码 + 可能的验证码）
#    - 跳 bgn_verification -> 手动点选验证
#    - 登录态会存进 .browser_profile/ 目录

# ③ 之后跑就自动带登录态，不用再登
```

### 登录态复用

`.browser_profile/` 是 Playwright 的持久化 profile，登录 cookie 存在里面。

**重要**：登录本身是风控权重最高的动作。**别反复登录** —— 复用 profile 能大幅降低风险。

```bash
# 换机器时，把整个 .browser_profile/ 拷过去就能复用（cookie 有效期通常几周）
rsync -av .browser_profile/ other-pc:/path/to/temu_scraper/
```

### 命令行参数

```bash
.venv/bin/python collectors.py temu_browser "关键词" 80 --no-images   # 不下图
TEMU_PROFILE=/tmp/other_profile .venv/bin/python collectors.py temu_browser "kw" 80  # 指定 profile
```

---

## 三、防封 IP：六层防护

按**性价比**排序，前三层免费且立刻见效。

### 🥇 第 1 层：控制频率（最重要，免费）

实测证据：**Amazon 一次跑 100 条就触发了 503 限流**（`AmazonBlocked: search: 503 dogs page`）。
Temu 的风控阈值类似 —— 突发高频请求会被标记。

已内置的默认参数（`temu_browser.py` 顶部）：

```python
DELAY_MIN = 1.8      # 每条之间最小间隔（秒）
DELAY_MAX = 5.5      # 最大间隔
BACKOFF_BASE = 4     # 失败退避基数
MAX_RETRY = 4
```

**调参建议**：

| 场景 | DELAY_MIN | DELAY_MAX | 说明 |
|---|---|---|---|
| 少量试水（<20 条） | 1.5 | 4 | 快 |
| 日常（50-100 条） | 2.5 | 7 | **推荐** |
| 大量（200+ 条） | 5 | 14 | 慢但安全 |
| 已被限流后 | 15 | 30 | 冷却 |

环境变量覆盖，不用改代码：
```bash
TEMU_DELAY_MIN=5 TEMU_DELAY_MAX=14 .venv/bin/python collectors.py temu_browser "kw" 200
```

### 🥇 第 2 层：住宅代理（最有效）

**数据中心 IP 必被封**。Temu 对 ASN 判定很严，AWS/DigitalOcean/阿里云这类段位基本一抓一个准。

```bash
# 环境变量即可，代码已支持
export TEMU_PROXY="http://user:pass@host:port"
.venv/bin/python collectors.py temu_browser "kw" 80
```

**代理类型选择**（重要）：

| 类型 | 推荐度 | 说明 |
|---|---|---|
| **住宅 ISP 静态** | ⭐⭐⭐⭐⭐ | 最稳，一个 IP 用久点，风控信任度高 |
| **住宅 ISP 轮换**（sticky 10-30 分钟） | ⭐⭐⭐⭐ | 兼顾稳定与分散 |
| **住宅 datacenter 混合** | ⭐⭐ | 一般 |
| **纯 datacenter** | ⭐ | ❌ 基本必封 |
| **免费代理** | ❌ | ❌ 绝对不要 |

**IP 轮换策略**（比代理类型更重要）：
- **不要每个请求换 IP** —— 一个账号 1 分钟内换 10 个 IP 反而更像机器人
- **推荐**：一个 IP 连续用 20-30 条，然后换下一个（sticky session）
- 账号和 IP 要**绑定**：一个账号固定用 1-2 个 IP，别到处跑

### 🥈 第 3 层：行为拟真

已内置：
- 真实 Chrome（`channel="chrome"`，TLS 指纹真）
- 真实 UA / 时区 / 语言 / 视口
- 滚动加载（不是一次性拉完）
- 随机鼠标滚动距离（2200px ± 随机）
- 随机等待（1.4-2.4s 不等）
- `ignore_default_args=["--enable-automation"]` + 反自动化检测脚本

**还没做但值得加的**（量大时）：
- 鼠标真实移动轨迹（`page.mouse.move` 带贝塞尔曲线）
- 偶尔的页面停留时长随机化
- 模拟 Tab 切换 / 页面停留

### 🥈 第 4 层：处理验证码，而不是硬刚

遇到 `bgn_verification` 或点选验证码时：

**正确做法**：停下 → 人工过一次 → 继续。
程序会 `wait_for_timeout` 等你处理，**不要试图自动破验证码**（那是自找封号）。

代码逻辑：
```python
if "bgn_verification" in cur:
    yield {"_phase": "login", "need_login": True,
           "message": "遇到风控验证页，请在浏览器窗口完成验证"}
    page.wait_for_timeout(5000)   # 等你处理
    continue
```

**注意**：验证码出现的频率本身就是信号。频繁弹 = IP 已经被盯上了，换 IP。

### 🥉 第 5 层：错误码识别与降速

| 错误码 | 含义 | 该做什么 |
|---|---|---|
| `40001` | needLogin | 登录（或用 Apify） |
| `40002` | 缺 anti-token | 签名问题（拦截模式不会遇到） |
| `406008` | IP 风控 | **立刻停**，换 IP 或等 30 分钟 |
| `429` | 限流 | 退避重试（`BACKOFF_BASE * 2^n`） |
| `503` | Amazon 限流 | 同上 |

**黄金规则：遇到 406008 立刻停手。** 继续重试只会让风控把你的账号/IP 标记得更死。

### 🥉 第 6 层：账号卫生

- **一个账号不要多 IP 乱跑** —— 账号是关联的
- **不要用新号大量抓** —— 新号权重低，风控更狠
- **避开高峰**（欧美晚间 = Temu 活跃期，风控也最严）
- **控制单账号总量** —— 建议每天几百条以内

---

## 四、现成的替代方案（更省心）

如果你的目标是「批量拿 Temu 数据」，**这两个比自建更稳**：

### Apify（$0.01/条）

托管服务有自己的 IP 池和养熟的环境，**你完全不用操心防封**。

```bash
export APIFY_TOKEN=xxx
.venv/bin/python collectors.py temu_apify "laundry bag" 80
```

已验证的 actor（2026-10 活跃）：

| Actor | 运行次数 | 说明 |
|---|---|---|
| `crw~temu-products-scraper` | 19,456 | 关键词 + 排序 |
| `selleraim.com~temu-product-scraper` | 6,667 | 搜索/类目/商品三合一，12 国站点 |
| `amit123~temu-products-scraper` | 39,553 | 商品 + 价格 |
| `apivault_labs~temu-product-scraper` | 10,837 | 14 层选品情报 |

**80 条 ≈ $0.8**，比买住宅代理便宜（代理月费通常 $20-50）。

### Amazon（免费且完全无风险）

如果你的选品需求不限定 Temu 平台，**Amazon 是最优解**：
- 免登录、无反爬、无需代理
- 字段比 Temu 更全（五点 + 附图 + 规格 + 变体 + 销量 + 评分）
- 实测 100 条 8.5 分钟，五点描述 99/100

---

## 五、决策树

```
需要 Temu 关键词数据
  │
  ├─ 量小（<50 条/天）且愿意登录
  │    → 自建 browser 模式 + 住宅代理 + 慢速
  │      成本：代理月费
  │
  ├─ 量中等（50-500 条/天）
  │    → Apify（$0.01/条 = $15-150/月）
  │      成本低、不用操心防封
  │
  └─ 只是想要「大量真实商品」不按关键词
       → 免登录累积模式（完全免费，已集成）
         实测 100 条 2 轮凑齐
```

---

## 六、代码位置

```
temu_browser.py     浏览器模式 v2（响应拦截 + 登录复用 + 防封）
collectors.py       统一采集接口（browser 模式转发到上面）
wiki/05-pitfalls.md 踩坑记录（含 503 限流的实测数据）
```

**环境变量**（全部可选）：

```bash
TEMU_PROFILE=/path/to/profile   # 登录态目录（默认 .browser_profile）
TEMU_PROXY=http://u:p@h:port    # 住宅代理
TEMU_DELAY_MIN=2.5              # 最小间隔
TEMU_DELAY_MAX=7                # 最大间隔
TEMU_BACKOFF=4                  # 退避基数
TEMU_MAX_RETRY=4                # 最大重试
```
