#!/usr/bin/env python3
"""
web_server.py —— 可视化选品控制台

用法：
    .venv/bin/python web_server.py            # 默认 http://127.0.0.1:8899
    PORT=9000 .venv/bin/python web_server.py

接口：
    GET  /                        前端页面
    GET  /api/jobs                任务列表
    POST /api/jobs                创建采集任务 {platform, keyword, limit, download_images}
    GET  /api/jobs/{id}/stream    SSE 实时进度 + 逐条推送商品
    GET  /api/jobs/{id}           任务快照
    GET  /api/jobs/{id}/download  导出 CSV
    GET  /api/jobs/{id}/images/{asin}/{file}  本地图片
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import sys
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import (FileResponse, HTMLResponse, StreamingResponse,
                               Response)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).parent
STATIC = ROOT / "static"
OUT = ROOT / "output"

app = FastAPI(title="选品数据采集控制台", version="1.0")

# ───────────────────────── 任务存储
JOBS: dict[str, dict] = {}


class JobReq(BaseModel):
    platform: str = "amazon"          # amazon | temu_api | temu_browser | temu_apify
    keyword: str = ""
    limit: int = 20
    download_images: bool = True
    token: str = ""


def _new_job(req: JobReq) -> dict:
    jid = uuid.uuid4().hex[:12]
    job = {
        "id": jid, "platform": req.platform, "keyword": req.keyword,
        "limit": req.limit, "status": "pending", "phase": "",
        "message": "排队中…", "current": 0, "total": 0,
        "records": [], "images": 0, "started_at": time.time(),
        "finished_at": None, "error": "", "need_login": False,
        "log": [],
    }
    JOBS[jid] = job
    return job


def _log(job, msg):
    job["log"].append({"t": time.strftime("%H:%M:%S"), "msg": msg})
    job["message"] = msg


async def _run_job(job: dict, req: JobReq):
    """在后台线程里跑采集器，把事件推到 job['queue']"""
    import collectors

    queue: asyncio.Queue = asyncio.Queue()
    job["queue"] = queue

    def producer():
        """用**子进程**跑采集器。

        为什么不用线程：Playwright 的 sync API 只能在主线程跑，
        放在 threading.Thread 里会报
        `Connection closed while reading from the driver`。
        子进程能让 Playwright 独占主线程，同时天然隔离崩溃。
        """
        import subprocess
        cmd = [sys.executable, str(ROOT / "collectors.py"), "--json",
               req.platform, req.keyword, str(req.limit)]
        if not req.download_images:
            cmd.append("--no-images")
        env = {k: v for k, v in os.environ.items()
               if k.lower() not in ("http_proxy", "https_proxy", "all_proxy")}
        if req.platform == "temu_apify" and req.token:
            env["APIFY_TOKEN"] = req.token

        try:
            job["status"] = "running"
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True,
                                    bufsize=1, env=env, cwd=str(ROOT))
            job["_proc"] = proc
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                loop.call_soon_threadsafe(queue.put_nowait, ev)
            proc.wait()
            if proc.returncode != 0 and job["status"] == "running":
                err = (proc.stderr.read() or "")[-600:]
                raise RuntimeError(f"采集进程退出（code {proc.returncode}）\n{err}")
        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e)[:800]
            loop.call_soon_threadsafe(queue.put_nowait,
                                      {"_phase": "error", "message": str(e)[:800]})
        finally:
            job["finished_at"] = time.time()
            if job["status"] == "running":
                job["status"] = "done"
            loop.call_soon_threadsafe(queue.put_nowait, {"_phase": "end"})

    loop = asyncio.get_running_loop()
    import threading
    threading.Thread(target=producer, daemon=True).start()

    while True:
        ev = await queue.get()
        ph = ev.get("_phase")
        if ph == "item":
            rec = ev["record"]
            job["records"].append(rec)
            job["current"] = len(job["records"])
            job["phase"] = "item"
            _log(job, f"[{job['current']}/{job['total'] or job['limit']}] "
                      f"{rec.get('title','')[:40]}")
        elif ph == "progress":
            job["current"] = ev.get("current", job["current"])
            job["total"] = ev.get("total", job["total"])
            job["phase"] = "progress"
            _log(job, ev.get("message", ""))
        elif ph == "search":
            job["phase"] = "search"
            job["total"] = job.get("total") or req.limit
            _log(job, ev.get("message", ""))
        elif ph == "images":
            job["phase"] = "images"
            _log(job, ev.get("message", ""))
        elif ph == "images_done":
            job["phase"] = "images"
            _log(job, ev.get("message", ""))
        elif ph == "login":
            job["need_login"] = True
            _log(job, ev.get("message", ""))
        elif ph == "error":
            job["status"] = "error"
            job["error"] = ev.get("message", "")
            _log(job, "❌ " + ev.get("message", ""))
        elif ph == "end":
            break
        # 推给所有 SSE 订阅者
        job["_ev"] = ev


@app.post("/api/jobs")
async def create_job(req: JobReq):
    job = _new_job(req)
    asyncio.create_task(_run_job(job, req))
    return {"id": job["id"], "status": job["status"]}


@app.get("/api/jobs")
async def list_jobs():
    return [{
        "id": j["id"], "platform": j["platform"], "keyword": j["keyword"],
        "status": j["status"], "phase": j["phase"], "message": j["message"],
        "current": j["current"], "total": j["total"], "count": len(j["records"]),
        "error": j.get("error", ""),
    } for j in reversed(list(JOBS.values()))]


@app.get("/api/jobs/{jid}")
async def get_job(jid: str):
    j = JOBS.get(jid)
    if not j:
        raise HTTPException(404, "任务不存在")
    return {k: v for k, v in j.items() if not k.startswith("_") and k != "queue"}


@app.get("/api/jobs/{jid}/stream")
async def stream_job(jid: str):
    j = JOBS.get(jid)
    if not j:
        raise HTTPException(404, "任务不存在")

    async def gen():
        # 断线重连：先补发已有数据
        yield f"data: {json.dumps({'type':'snapshot','job':_snapshot(j)}, ensure_ascii=False)}\n\n"
        last = len(j["records"])
        while True:
            if j.get("status") in ("done", "error") and len(j["records"]) == last:
                yield f"data: {json.dumps({'type':'end','job':_snapshot(j)}, ensure_ascii=False)}\n\n"
                break
            if len(j["records"]) > last:
                for rec in j["records"][last:]:
                    yield f"data: {json.dumps({'type':'item','record':rec}, ensure_ascii=False)}\n\n"
                last = len(j["records"])
            yield f"data: {json.dumps({'type':'status','job':_snapshot(j)}, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.6)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


def _snapshot(j):
    return {
        "id": j["id"], "status": j["status"], "phase": j["phase"],
        "message": j["message"], "current": j["current"], "total": j["total"],
        "count": len(j["records"]), "error": j.get("error", ""),
        "need_login": j.get("need_login", False),
        "log": j["log"][-40:],
    }


@app.get("/api/jobs/{jid}/download")
async def download(jid: str, fmt: str = "csv"):
    j = JOBS.get(jid)
    if not j:
        raise HTTPException(404, "任务不存在")
    recs = j["records"]
    if not recs:
        raise HTTPException(404, "暂无数据")

    if fmt == "json":
        return Response(json.dumps(recs, ensure_ascii=False, indent=2),
                        media_type="application/json",
                        headers={"Content-Disposition":
                                 f'attachment; filename="products_{jid}.json"'})

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["platform", "id", "title", "price", "currency", "rating",
                "review_count", "sold", "brand", "seller", "in_stock",
                "image_count", "image_urls", "bullet_count", "bullets",
                "specs", "url", "error"])
    for r in recs:
        w.writerow([r.get("platform"), r.get("id"), r.get("title"), r.get("price"),
                    r.get("currency"), r.get("rating"), r.get("review_count"),
                    r.get("sold"), r.get("brand"), r.get("seller"), r.get("in_stock"),
                    r.get("image_count"), " | ".join(r.get("images", [])[:20]),
                    r.get("bullet_count"), " | ".join(map(str, r.get("bullets", [])[:10])),
                    json.dumps(r.get("specs", {}), ensure_ascii=False),
                    r.get("url"), r.get("error")])
    return Response(buf.getvalue().encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition":
                             f'attachment; filename="products_{jid}.csv"'})


@app.get("/img/{platform}/{ident}/{fname}")
async def serve_img(platform: str, ident: str, fname: str):
    base = OUT / ("amazon" if platform == "amazon" else "temu") / "images" / ident
    p = base / fname
    if not p.exists():
        raise HTTPException(404, "图片不存在")
    return FileResponse(p, headers={"Cache-Control": "public, max-age=86400"})


@app.get("/favicon.ico")
async def favicon():
    f = STATIC / "favicon.svg"
    if f.exists():
        return FileResponse(f, media_type="image/svg+xml")
    raise HTTPException(404)


@app.get("/", response_class=HTMLResponse)
async def index():
    f = STATIC / "index.html"
    if not f.exists():
        return HTMLResponse("<h1>缺少 static/index.html</h1>", status_code=500)
    return HTMLResponse(f.read_text(encoding="utf-8"))


if STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8899"))
    print(f"\n🛒 选品数据采集控制台  http://127.0.0.1:{port}\n")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
