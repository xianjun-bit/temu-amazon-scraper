# 05 · 踩坑清单

> 都是这次实际踩到的，附复现和解法。

## ⭐ 1. 环境代理导致全部 502（最坑）

**症状**：
```
{"error":"upstream connect failed: Connection refused (os error 61)"}
```
或 curl 直接 404。看起来像"服务没起"，其实是走了代理。

**根因**：WorkBuddy 环境注入了
```
HTTP_PROXY=http://127.0.0.1:50734
HTTPS_PROXY=http://127.0.0.1:50734
http_proxy=...  https_proxy=...
```
`curl_cffi` 和 `urllib` 都默认读环境变量 → 所有请求走这个内部代理 → 代理拒绝连接。

**解法 A（启动服务时清）**：
```bash
cd /tmp/amz/amazon-scraper
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy
PORT=8770 .venv/bin/python run.py
```

**解法 B（Python 调用时绕过）**：
```python
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with opener.open(url, timeout=30) as r:
    ...
```

**解法 C（代码里全局清）**：
```python
for k in ("http_proxy","https_proxy","HTTP_PROXY","HTTPS_PROXY","all_proxy","ALL_PROXY"):
    os.environ.pop(k, None)
```

> `amazon_collect.py` 三种都用上了。

---

## ⭐ 2. 端口 8000 被占用

**症状**：起服务后访问返回 `{"detail":"Not Found"}`（FastAPI 格式，不是 bottle 格式）。

**根因**：8000 已经被用户自己的 Replenishment 后端（FastAPI）占用。
我起 bottle 服务时它绑不上，但我误以为是路由问题排查了半天。

**解法**：Amazon scraper 用 8770+。`amazon_collect.py` 里 `AMZ_PORT` 可配。

---

## ⭐ 3. 后台进程活不过一次 Bash 调用

**症状**：`nohup ... &` 起服务，下一条命令访问就 "Connection refused"。

**解法**：不要依赖后台进程。在采集脚本里**同进程起服务**：

```python
import threading
from cheroot import wsgi
srv = wsgi.Server(("127.0.0.1", PORT), bottle.default_app(), numthreads=16)
threading.Thread(target=srv.start, daemon=True).start()
```

---

## 4. headless 验证码死循环（我自己的 bug）

**症状**：脚本卡住 29 分钟，Exit 137（SIGTERM）。

**根因**：我的 `collect_one()` 里，遇到验证码就 `while True: wait` 等人工处理。
headless 模式下没人能过 → 死等。

**解法**：headless 时检测到验证码就**跳过并记录**，不阻塞：

```python
if re.search(r"Slide to complete|Security Verification|puzzle", body, re.I):
    if headless:
        rec["error"] = "触发验证码（headless 无法人工通过）"
        return rec
    # headed: 提示用户手动完成
    while True:
        page.wait_for_timeout(2500)
        body = page.evaluate("document.body.innerText") or ""
        if not re.search(r"Slide to complete|Security Verification|puzzle", body, re.I):
            break
```

---

## 5. Playwright Python API 是属性不是方法

**症状**：`TypeError: 'str' object is not callable`

**根因**：Node 版是 `page.title()`，**Python 版是 `page.title`**（无括号）。
同理 `res.url` / `res.request.post_data` / `page.url`。

```python
# ❌ Node 写法
print(page.title())
# ✅ Python 写法
print(page.title)
```

---

## 6. Playwright 版本与本地 Chromium 不匹配

**症状**：
```
browserType.launch: Executable doesn't exist at
  ~/Library/Caches/ms-playwright/chromium_headless_shell-1194/...
```

**根因**：本地装的是 chromium-1243，playwright 1.56 要 1194，1.64 要 1248。

**解法（推荐）**：用系统已装的 Chrome，**不用下载**：
```python
chromium.launch(channel="chrome")
```

**或**：`pip install playwright && playwright install chromium`（会下 ~150MB）。

---

## 7. Playwright 事件回调里不能 await

**症状**：`TypeError: 'str' object is not callable` 出现在 response handler 里。

**根因**：Python 版 Playwright 的 `page.on("response", handler)` 是**同步**回调，
里面不能用 `await res.text()`；而 `res.text()` 在 Python 里是**方法**要加括号，
`res.url` 是**属性**不加括号。混用就报错。

**解法**：
```python
def on_resp(res):
    u = res.url                      # 属性
    b = res.text()                   # 方法
```

---

## 8. rawData 用非贪婪正则提取会截断

**症状**：`json.loads` 报 JSONDecodeError，或提取出的 dict 只有几个 key。

**根因**：`window.rawData={"store":{"a":1,...},"b":2}` 用 `\{.*?\}` 会在第一层 `}` 就停。

**解法**：括号平衡法（已实现于 `temu_parse.py`）：
```python
def extract_json_after(text, marker):
    i = text.find(marker); j = text.find('{', i)
    depth, in_str, esc = 0, False, False
    for k in range(j, len(text)):
        ch = text[k]
        if in_str:
            if esc: esc = False
            elif ch == '\\': esc = True
            elif ch == '"': in_str = False
            continue
        if ch == '"': in_str = True
        elif ch == '{': depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return json.loads(text[j:k+1])
```

---

## 9. goods_id 是 int 不是 str

**症状**：`TypeError: unsupported operand type(s) for /: 'PosixPath' and 'int'`

**解法**：`gid = str(r.get("goods_id") or "unknown")`

---

## 10. mkdir 报 FileExistsError

**症状**：`FileExistsError: [Errno 17] EEXIST: file already exists, mkdir '/tmp/xxx'`

**根因**：WorkBuddy 的路径代理层，`mkdir(exist_ok=True)` 仍可能抛。
**解法**：先 `rm -rf` 目标目录，或 `mkdir(parents=True, exist_ok=True)`。

---

## 11. Temu `scene` 参数不生效

**症状**：`goods_list` 传 `scene:"search"` 以为能搜关键词，结果返回的还是首页推荐商品。

**实测**：传 `scene:"search"` / `"search_result"` / `"category"` / `"goods"` 全部返回首页商品。
该端点只服务首页 feed。搜索必须走 `/api/poppy/v1/search`（需 anti-token）。

---

## 12. `impersonate="chrome131"` 反而失败

Temu challenge 对指纹版本敏感：chrome131 返回 3KB challenge，chrome124 返回 396KB 完整页。
**用 chrome124**。

---

## 13. Amazon 详情接口返回 200 但内容残缺

**症状**：详情接口 HTTP 200，有 `title`、有 `bullets`，但 `images` / `rating` / `variations` 是空的。
`error` 字段也为空，看起来"成功"了。

**根因**：Amazon 触发了**降级渲染**（部分区块不渲染），返回的是不完整页面。

**解法**：判定"完整"不能只看 `title`，要同时检查关键字段：

```python
complete = bool(d.get("images")) and (d.get("rating") is not None)
if complete or i == retries - 1:
    if not complete:
        d["_partial"] = True      # 标记出来，别静默丢数据
    return d
```

实测：改之前 rating 9/10、bought_past_month 9/10；改之后补齐到 10/10。

---

## 14. 图片下载被 [:12] 截断

**症状**：10 个商品 `image_count` 加起来 185，但实际只下了 90 张。

**根因**：`for u in r["images"][:12]:` 每条只取前 12 个 URL。

**解法**：去掉截断，全量下载；同时按 URL 去重（同一张图的 link/large/thumbnail 是不同尺寸，
只取 `link` 高清版即可）：

```python
imgs = list(dict.fromkeys(imgs))   # 去重
for u in r["images"]:               # 不截断
    futs.append(ex.submit(dl, u, d))
```

实测：90 张 -> 188 张。

---

## 【专题】Playwright 多实例冲突（2026-11-02）

### 症状

Web 控制台跑 Temu 模式时报：

```
采集进程退出（code 1）
  File ".../playwright/_impl/_connection.py", line 78, in send_return
    await self._connection.wrap_api_call(
  File ".../playwright/_impl/_connection.py", line 636, in wrap_api_call
    raise rewrite_error(error, f"**{parsed_st['apiName']}:{error}")
Exception: Connection.init: Connection closed while reading from the driver
```

**关键**：错误信息里的 "driver" 指 **Playwright**，不是 curl_cffi。

### 三个不同的坑，同一个报错

| # | 原因 | 症状 | 修法 |
|---|---|---|---|
| 1 | Playwright sync API 只能在**主线程**跑 | Web 里报、CLI 正常 | Web 用**子进程**跑采集器（`collectors.py --json`） |
| 2 | 两个 Playwright 实例**共用同一个 profile 目录** | 同时跑两个任务，其中一个挂 | 每个进程用**独立临时 profile**（`tempfile.mkdtemp()`） |
| 3 | browser 模式 profile 是固定的（要留登录态） | 两个 browser 任务互相踢 | 用 `fcntl.flock` **文件锁**串行化，冲突时给可读提示 |

### 定位方法（可复用）

1. **先确认是谁的错**：看 traceback 里的路径是 `playwright/_impl/_connection.py` → Playwright；
   `curl_cffi/requests/exceptions.py` → curl_cffi
2. **对比 CLI 与 Web**：同一份代码 CLI 能跑、Web 不能跑 → 怀疑线程模型（坑 1）
3. **模拟并发**：起两个服务同时跑同一模式 → 复现坑 2
4. **`_launch_browser()` 统一入口**：把启动逻辑收进一个函数，失败时给「① 是否有别的任务在跑
   ② Chrome 是否正常 ③ 直接试跑命令」三条排查建议，而不是甩 traceback

### 顺带发现

`sync_playwright().start()` 返回的对象**不支持 `with` 协议**（只有 `sync_playwright()` 上下文管理器支持）。
写 `with sync_playwright().start():` 会报
`TypeError: 'Playwright' object does not support the context manager protocol`。

正确写法：

```python
pw = sync_playwright().start()
try:
    ctx = pw.chromium.launch_persistent_context(...)
    ...
finally:
    ctx.close()
    pw.stop()
```
