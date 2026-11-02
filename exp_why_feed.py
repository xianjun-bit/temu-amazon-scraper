#!/usr/bin/env python3
"""
为什么 Temu 免登录只能拿首页推荐位？—— 穷尽验证

已确认：
  POST /api/poppy/v1/search        -> 403 error_code=40001 (needLogin)
  POST /api/alexa/homepage/goods_list -> 200 免登录，但传 scene:"search" 无效

还没试的可能性：
  A. goods_list 的 opt_id 参数 —— body 里本来就有这个字段！
     opt_id 指向「筛选器」，如果类目/关键词也算筛选器，可能能绕过
  B. goods_list 的 list_id —— 搜索页 rawData 里有 listId
  C. goods_list 的 category_id / search_key 等其它参数名
  D. 类目页 URL（/category-xxx.html）走的是不是同一个免登录接口
  E. 搜索页 SSR 里有没有 optList（筛选器列表），里面可能有类目 ID
"""
import json, re, sys
from pathlib import Path
from curl_cffi import requests

BASE = "https://www.temu.com"
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from temu_parse import get_rawdata

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9", "Referer": BASE + "/"})

# ── 1) 搜索页 SSR：挖 optList / listId / 类目信息 ──
Q = ("search_key=laundry%20bag&search_method=shade&refer_page_el_sn=200010"
     "&srch_enter_source=top_search_entrance_10005&refer_page_name=home"
     "&refer_page_sn=10005&filter_items=1%3A1")
html = s.get(f"{BASE}/search_result.html?{Q}", impersonate="chrome124", timeout=30).text
st = get_rawdata(html)["store"]
print("=== 搜索页 rawData 顶层 ===")
print("  keys:", sorted(st.keys())[:30])
print("  listId:", st.get("listId"))
print("  searchKey:", st.get("searchKey"))

# filtersStore 里有没有筛选器
fs = st.get("filtersStore") or {}
print("\n=== filtersStore ===")
for k, v in fs.items():
    sv = json.dumps(v, ensure_ascii=False)
    print(f"  {k}: {sv[:180]}")

# 全页搜 optList / optId / category
print("\n=== 页面里搜 optList / optId / categoryId ===")
for kw in ["optList", "optId", "categoryId", "category_id", "goodsNumAdv"]:
    n = html.count(kw)
    print(f"  {kw}: {n}")
    if n:
        i = html.find(kw)
        seg = html[max(0,i-150):i+250].replace("\n", " ")
        print(f"     {seg[:330]}")

# ── 2) 类目页 URL 试水 ──
print("\n=== 类目页 ===")
for cat_url in [f"{BASE}/category-shoes.html",
                f"{BASE}/category-home-supplies.html",
                f"{BASE}/c-10007.html"]:
    try:
        r = s.get(cat_url, impersonate="chrome124", timeout=25)
        has = "window.rawData" in r.text
        print(f"  {cat_url.replace(BASE,''):<40} {r.status_code} len={len(r.text)} rawData={has}")
    except Exception as e:
        print(f"  {cat_url}: ERR {str(e)[:40]}")
