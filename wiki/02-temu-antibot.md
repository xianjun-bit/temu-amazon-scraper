# 02 · Temu 反爬拆解

> 全部结论来自实测，每条都有复现方式。

## 4 道门

```
请求 ──▶ 门1 JS Challenge ──▶ 门2 SSR 空壳 ──▶ 门3 IP 风控 ──▶ 门4 登录墙/验证码
         ✅已破              ✅已破            ❌需代理          ❌需登录
```

### 门 1：JS Challenge ✅ 已破

**症状**：`curl` / `requests` 直连返回 ~3KB 混淆 JS，注入 `window.challenge`，动态加载
`https://static.kwcdn.com/upload-static/assets/chl/js/fea85011-2193-411a-82f6-2fcd40e00205.js`

**无效的尝试**（都试过）：
- 换 UA：Googlebot / bingbot / ClaudeBot / GPTBot / Android UA / iPhone 移动端 UA → 全部照样 challenge
- 加 `Referer` / `Accept-Language` → 无效

**有效方案**：`curl_cffi` TLS 指纹伪装

```python
from curl_cffi import requests
r = requests.get(url, impersonate="chrome124", timeout=30)   # ✅ 396KB 完整页面
```

**稳定性实测**：26/26 全通过（连续请求 + 轮换 6 种 impersonate：chrome124/131/120/119/safari17_0/safari15_3）

**关键**：`impersonate="chrome131"` 反而失败（返回 3KB challenge），**`chrome124` 稳定**。
可用值：`chrome124`（首选）、`chrome120`、`chrome119`、`safari17_0`、`safari15_3`。

### 门 2：SSR 空壳 ✅ 已破

**症状**：拿到 396KB 页面，但商品数据不在 HTML 里：

```javascript
window.rawData.store.goods = {}          // 商品对象是空的
window.rawData.store.goodsList = []       // 搜索页商品列表也是空的
window.rawData.store.goodsProperty = []   // 规格是空的
```

**搜索页还有 `is_nres: 1`** —— 服务端故意在 SSR 阶段不返回结果。

**突破**：数据由前端 XHR 加载。用浏览器上下文内 `fetch()` 直调 API 即可拿到真数据：

```javascript
await fetch('/api/alexa/homepage/goods_list', {
  method: 'POST', credentials: 'include',
  headers: {'Content-Type': 'application/json;charset=UTF-8'},
  body: JSON.stringify({offset:0, count:120, list_id:"", opt_id:null, listId:"",
                        scene:"home", page_list_id:"", extend_fields:{}})
})
// → 200, result.home_goods_list[].data.goods_list[] 真实商品数组
```

### 门 3：IP 风控 ❌ 需代理

**症状**：直连任何 API → `429 {"error_code":406008,"error_msg":""}`
连首页**已知可用**的 `goods_list` 端点也被拦。

**错误码语义（重要）**：

| 错误码 | 含义 |
|---|---|
| `40001` | 需要登录（needLogin） |
| `40002` | **缺 anti-token 签名** |
| `40003` | 参数错误 / 端点不接受该 body |
| `406008` | **IP 级风控 / 限流** |

区分 40002 和 40003 很关键：40003 说明路径对了只是参数不对，可以试出来；
40002 说明签名缺失，穷举参数没用。

**anti-token 机制**：所有 API 请求要带 `anti-content` header，由页面 native bridge
（`window.pinbridge.callNative("JSNetwork","request",{...,force_anti_token:!0})`）生成，
**纯 JS 环境无法伪造**。

抓到过的一次真实签名（供理解格式，长度约 120 字符）：
```
anti-content: 0GWs03c5pyvThOdKidU9o7UGGZLZOJn_OG0joW-oJlk_gtx1cNj1YKDFj51e_Heo_RZbdRZx1ijbWRex_RBzWRZT8iex8Gcx1RemmhCrmchXU22KOQj98nR9
```

即使照抄这个 header + 全部 cookies + postData 去 curl_cffi 重放，**仍然 429** ——
说明 `anti-content` 是**请求相关**（随 body/时间变化），且服务端同时校验 TLS 指纹。

### 门 4：登录墙 + 验证码 ❌ 需登录

**症状 A —— 服务端强制登录**：商品页 / 搜索页一律 302 到 `login.html`

```
https://www.temu.com/goods.html?goods_id=601100218100590
  → https://www.temu.com/login.html?from=...&login_scene=2&...
```

**症状 B —— 点选验证码**（headless 专有）：

```
"Security Verification
 Please click on the type of electronic device that appears most frequently"
```
接口：`POST /api/phantom/obtain_captcha`（返回 188–211KB 题面数据）

**症状 C —— headed 模式被踢登录**：`login.policy_one` 只对 `region=211`（美国）生效。

**尝试过的绕过（全部失败）**：

| 尝试 | 结果 |
|---|---|
| 改 `region` cookie = 37（加拿大） | cookie 保持 37，但**仍跳登录** |
| 区域路径 `/uk/` `/ca/` `/de/` `/fr/` `/jp/` `/kr/`… | 全部 302 登录 |
| `refer_page_sn=10005` 等入口参数 | curl_cffi 层**不跳登录**（367KB 完整页），但**浏览器层照跳** |
| stealth 补丁（webdriver/chrome/plugins/WebGL/permissions…） | `navigator.webdriver=null` 生效，**仍跳登录** |
| `share_token` 分享链接 | title 正确，**仍跳登录** + 滑块 |
| Googlebot/Bingbot/ClaudeBot/GPTBot UA | 反而**直接触发 challenge** |
| `m.temu.com` / `mobile.temu.com` / `h5.temu.com` | `m.temu.com` 302 回 www，其余无响应 |
| `sitemap-index.xml` | 403 |
| 移动 UA + `goods.html?goods_id=` | 246KB 页面但仍是骨架（`goodsName` 只是 CSS class 名） |

**结论**：判定在 **JS 层的 `isRobot` / 风控逻辑**，不是 UA 指纹，也不是服务端 cookie。
最有效的两个杠杆是：**① 住宅代理换 IP ② 人工过一次验证码 / 登录态**。

## 有用的旁路

**curl_cffi 层搜索页不跳登录的入口参数**（来源：Temu-Item-Scraper 历史可用 URL）：

```
&search_method=shade
&refer_page_el_sn=200010
&srch_enter_source=top_search_entrance_10005
&refer_page_name=home
&refer_page_sn=10005
&filter_items=1%3A1
```

实测：`curl_cffi` + 这套参数 → 367KB 完整搜索页，`login=False`，
`rawData.store` 里 `hasOneLogin: false` / `isRobot: false` / `isLogin: false` / `dr: "us"`。
可用它拿到搜索页的 `listId`、`query`、`searchEventInfo` 等参数（虽然 goodsList 是空的）。

## robots.txt 实测

```
User-agent: Googlebot / ClaudeBot / GPTBot / PerplexityBot / Bingbot ...
Sitemap: https://www.temu.com/sitemap-index.xml
```
Temu **明确允许**主流 AI 爬虫抓取，但 sitemap 返回 403。
禁抓的都是账户/订单类路径（`/bgp_*` `/bgt_*` `/shopping_cart.html` 等）。
