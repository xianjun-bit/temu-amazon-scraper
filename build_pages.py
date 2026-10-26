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

PAGES = [
    ("01-status-overview.md", "现状总览"),
    ("02-temu-antibot.md", "Temu 反爬拆解"),
    ("03-temu-api-reverse.md", "Temu API 逆向"),
    ("04-amazon-practice.md", "Amazon 实战"),
    ("05-pitfalls.md", "踩坑清单"),
    ("06-handoff.md", "换机续作"),
]

DOCS.mkdir(exist_ok=True)

# 复制 wiki 页（去掉 00-index，单独做首页）
for src, _ in PAGES:
    shutil.copy(WIKI / src, DOCS / src)

# 首页
idx = (WIKI / "00-index.md").read_text()
(DOCS / "index.md").write_text(idx)

# 顶部导航（插到每个页面开头）
NAV = """<div align="center">

**[← 返回目录](index.md)** · [现状总览](01-status-overview.md) · [Temu 反爬](02-temu-antibot.md) · [API 逆向](03-temu-api-reverse.md) · [Amazon 实战](04-amazon-practice.md) · [踩坑清单](05-pitfalls.md) · [换机续作](06-handoff.md)

</div>

---
"""
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
