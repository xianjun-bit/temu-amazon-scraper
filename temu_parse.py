#!/usr/bin/env python3
"""公共工具：从 HTML 中用括号平衡法提取 window.rawData / 其他内联 JSON"""
import json, re


def extract_json_after(text, marker):
    """在 marker 之后用括号平衡法提取一个完整 JSON 值"""
    i = text.find(marker)
    if i < 0:
        return None
    j = text.find('{', i)
    if j < 0:
        return None
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
                try:
                    return json.loads(text[j:k + 1])
                except Exception:
                    return None
    return None


def get_rawdata(html):
    return extract_json_after(html, 'window.rawData=')


def iter_goods(obj, path="", out=None, depth=0):
    """在任意 JSON 中递归找形似商品列表的数组"""
    if out is None: out = []
    if depth > 8 or not isinstance(obj, (dict, list)):
        return out
    if isinstance(obj, list):
        if obj and isinstance(obj[0], dict) and any(k in obj[0] for k in ("goods_id", "goodsId", "goodsName", "title")):
            out.append((path, obj))
        for i, v in enumerate(obj[:50]):
            iter_goods(v, f"{path}[{i}]", out, depth + 1)
    else:
        for k, v in obj.items():
            iter_goods(v, f"{path}.{k}", out, depth + 1)
    return out


if __name__ == "__main__":
    import sys
    html = open(sys.argv[1]).read()
    raw = get_rawdata(html)
    if not raw:
        print("no rawData"); sys.exit(1)
    st = raw.get("store", {})
    print("store keys:", list(st.keys())[:60])
    for k in ["searchKey", "pageSize", "currentPage", "hasSearchResults", "isLoading", "hasMore", "listId", "searchMethod", "region", "currency"]:
        print(f"  {k:<20} {json.dumps(st.get(k), ensure_ascii=False)[:90]}")
    gl = st.get("goodsList")
    print(f"\ngoodsList: type={type(gl).__name__} len={len(gl) if isinstance(gl, (list,dict)) else '-'}")
    if isinstance(gl, list) and gl:
        print("goodsList[0]:")
        for k, v in list(gl[0].items())[:45]:
            print(f"    {k:<24} {str(v)[:80]}")
    print("\n=== 商品数组搜索 ===")
    for p, arr in iter_goods(st)[:8]:
        print(f"  {p}  n={len(arr)}")
