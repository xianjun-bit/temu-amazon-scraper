#!/usr/bin/env python3
"""
挖 goods_list 的真实调用参数（从 bundle），看它到底接不接受类目/关键词
"""
import json, re
from concurrent.futures import ThreadPoolExecutor
from curl_cffi import requests

BASE = "https://www.temu.com"
s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                  "Accept-Language": "en-US,en;q=0.9"})

# 首页 bundle
html = s.get(BASE + "/", impersonate="chrome124", timeout=30).text
urls = sorted(set(re.findall(r'"(https://static\.kwcdn\.com/[^"]+\.js)"', html)))
print(f"首页 {len(urls)} 个 bundle")

def get(u):
    try: return u, s.get(u, impersonate="chrome124", timeout=40).text
    except Exception: return u, ""

hits = []
with ThreadPoolExecutor(max_workers=10) as ex:
    for u, js in ex.map(get, urls):
        if len(js) < 3000: continue
        if "homepage/goods_list" in js or "goods_list" in js:
            name = u.split("/")[-1]
            for m in re.finditer(r"goods_list", js):
                i = m.start()
                seg = js[max(0,i-1600):i+400]
                if "homepage/goods_list" in seg or ("scene" in seg and "extend_fields" in seg):
                    hits.append((name, seg))
                    break

print(f"\n找到 {len(hits)} 个相关 bundle\n")
for name, seg in hits[:3]:
    print(f"--- {name}")
    # 找 params 构造
    for kw in ["extend_fields", "page_list_id", "home_goods_list", "list_id"]:
        i = seg.find(kw)
        if i > 0:
            print(f"    [{kw}] {seg[max(0,i-260):i+260]}")
            print()
    break

# 直接在所有 bundle 里搜 goods_list 的调用形式
print("\n=== 全局搜 homepage/goods_list 的调用 ===")
def get2(u):
    try: return u, s.get(u, impersonate="chrome124", timeout=40).text
    except Exception: return u, ""
with ThreadPoolExecutor(max_workers=10) as ex:
    for u, js in ex.map(get2, urls):
        if "homepage/goods_list" not in js: continue
        name = u.split("/")[-1]
        for m in re.finditer(r"/api/alexa/homepage/goods_list", js):
            i = m.start()
            seg = js[max(0,i-1200):i+300]
            print(f"\n--- {name} @ {i}")
            print("   ", seg.replace("\n", " ")[-1300:])
            break
