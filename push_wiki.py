#!/usr/bin/env python3
"""
把 wiki/ 目录推送到 GitHub Wiki。

GitHub 的 wiki 是个独立 git 仓库（<repo>.wiki.git），且**必须先在网页上
手动创建第一个页面**才会存在 —— 这是一次性的初始化动作。

用法：
  1) 浏览器打开 https://github.com/<你的账号>/<仓库>/wiki
  2) 点 "Create the first page"，标题随便填（如 Home），点 Save
  3) 回到终端跑：  python3 push_wiki.py
"""
import os, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).parent
WIKI = ROOT / "wiki"

def run(cmd, cwd=None):
    print(f"  $ {cmd}")
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    out = (r.stdout + r.stderr).strip()
    if out:
        print("    " + out.replace("\n", "\n    ")[:500])
    return r.returncode == 0

def main():
    repo = os.environ.get("WIKI_REPO", "tom982346-ctrl/temu-amazon-scraper")
    token = os.environ.get("GITHUB_TOKEN") or ""
    if not token:
        # 尝试从 gh 取
        r = subprocess.run("gh auth token", shell=True, capture_output=True, text=True)
        token = r.stdout.strip()
    if not token:
        print("❌ 拿不到 GitHub token。设置 GITHUB_TOKEN 环境变量，或先跑 gh auth login")
        sys.exit(1)

    remote = f"https://{token}@github.com/{repo}.wiki.git"
    tmp = Path(tempfile.mkdtemp()) / "wiki"
    tmp.mkdir(parents=True)

    print(f">>> 推送到 {repo} 的 Wiki")
    run(f"git init -q -b main", cwd=tmp)
    for f in sorted(WIKI.glob("*.md")):
        shutil.copy(f, tmp / f.name)
    # 00-index.md -> Home.md（GitHub wiki 首页必须是 Home）
    idx = tmp / "00-index.md"
    if idx.exists():
        shutil.move(str(idx), str(tmp / "Home.md"))

    run(f"git add -A", cwd=tmp)
    run(f'git -c user.name="tom982346-ctrl" '
        f'-c user.email="tom982346-ctrl@users.noreply.github.com" '
        f'commit -q -m "wiki: 同步逆向成果与踩坑记录"', cwd=tmp)
    run(f"git remote add origin {remote}", cwd=tmp)
    ok = run("git push -u origin main", cwd=tmp)

    if ok:
        print("\n✅ Wiki 推送成功！")
        print(f"   https://github.com/{repo}/wiki")
    else:
        print("\n❌ 推送失败。若提示 Repository not found，说明 wiki 还没初始化：")
        print(f"   浏览器打开 https://github.com/{repo}/wiki")
        print('   点 "Create the first page" → 标题填 Home → Save → 再跑一次本脚本')
    shutil.rmtree(tmp.parent, ignore_errors=True)

if __name__ == "__main__":
    main()
