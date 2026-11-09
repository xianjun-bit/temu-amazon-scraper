#!/usr/bin/env python3
"""
生成 GitHub Pages 站点（docs/ 目录）
- index.md   → 导航首页（从 wiki/00-index.md 转换）
- 复制所有 wiki 页面
- 加一个 HTML 导航页
"""
import re, shutil, sys
from pathlib import Path

ROOT = Path(__file__).parent
WIKI = ROOT / "wiki"
DOCS = ROOT / "docs"

# 自动扫描 wiki/ 目录（新增页面不用再手改这里，避免漏掉）
def _scan_pages():
    out = []
    for f in sorted(WIKI.glob("*.md")):
        if f.name == "00-index.md":
            continue
        if ".backup" in f.name or f.name.startswith("."):
            continue
        out.append((f.name, f.stem))
    return out

PAGES = _scan_pages()

DOCS.mkdir(parents=True, exist_ok=True)  # WorkBuddy 路径层对 exist_ok 也会抛，忽略

# 复制 wiki 页（去掉 00-index，单独做首页）
for src, _ in PAGES:
    shutil.copy(WIKI / src, DOCS / src)

# 首页
idx = (WIKI / "00-index.md").read_text()
(DOCS / "index.md").write_text(idx)

# 顶部导航（插到每个页面开头）
def _nav():
    links = " · ".join(f"[{name}]({fn})" for fn, name in PAGES)
    return f"""<div align="center">

**[← 返回目录](index.md)** · {links}

</div>

---
"""
NAV = _nav()
for src, _ in PAGES:
    p = DOCS / src
    p.write_text(NAV + p.read_text())

# README 指向站点
readme = ROOT / "README.md"
s = readme.read_text()
if "docs/index.md" not in s:
    s = s.replace("## 一、结论速览",
                  "> 📖 在线文档（Pages）：https://tom982346-ctrl.github.io/temu-amazon-scraper/\n\n"
                  "## 一、结论速览")
    readme.write_text(s)

print(f"✅ 已生成 {len(PAGES)+1} 个页面 -> {DOCS}")
for f in sorted(DOCS.glob("*.md")):
    print(f"   {f.name}")
