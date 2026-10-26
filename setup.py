#!/usr/bin/env python3
"""
一键复现脚本 —— 在新机器上重建整个环境。

用法：
    python3 setup.py             # 装依赖（自动 clone amazon-scraper + 建 venv）
    python3 setup.py --check     # 只做环境自检，不改动任何东西

环境变量：
    AMZ_REPO   amazon-scraper 存放路径（默认 <包内>/vendor/amazon-scraper）
"""
import os, platform, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).parent
AMZ_REPO = Path(os.environ.get("AMZ_REPO", str(ROOT / "vendor" / "amazon-scraper")))
IS_MAC = platform.system() == "Darwin"

def run(cmd, cwd=None, check=True):
    print(f"  $ {cmd}")
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        print(f"    ❌ 失败: {r.stderr.strip()[:300]}")
        return False
    return True

def check():
    print("=== 环境自检 ===")
    py = sys.version.split()[0]
    print(f"  Python        : {py}  {'✅' if sys.version_info >= (3, 10) else '❌ 需 3.10+'}")
    print(f"  平台          : {platform.system()} {platform.machine()}")
    for tool, ver in [("git", "git --version"), ("node", "node -v")]:
        r = subprocess.run(ver, shell=True, capture_output=True, text=True)
        print(f"  {tool:<14}: {r.stdout.strip() if r.returncode == 0 else '❌ 未安装'}")
    # venv
    for name, venv in [("temu", ROOT / ".venv"), ("amazon", AMZ_REPO / ".venv")]:
        if venv.exists():
            print(f"  venv[{name:<7}]: ✅ {venv}")
        else:
            print(f"  venv[{name:<7}]: ⚠️ 未创建 {venv}")
    # chrome
    chrome = "/Applications/Google Chrome.app"
    if IS_MAC:
        print(f"  Chrome        : {'✅' if Path(chrome).exists() else '⚠️ 未找到（仅 browser 模式需要）'}")
    print(f"  代理环境变量  : {'⚠️ ' + os.environ.get('HTTP_PROXY','') if os.environ.get('HTTP_PROXY') else '✅ 无'}")

def setup():
    print("=== 1. Python venv ===")
    if not (ROOT / ".venv").exists():
        run(f"{sys.executable} -m venv {ROOT / '.venv'}")
    req = ROOT / "requirements.txt"
    if req.exists():
        run(f"{ROOT / '.venv' / 'bin' / 'pip'} install -q -r {req}")

    print("=== 2. Playwright（仅 Temu browser 模式需要）===")
    if (ROOT / ".venv").exists():
        run(f"{ROOT / '.venv' / 'bin' / 'pip'} install -q playwright")
        # 复用系统 Chrome，无需下载 chromium
        print("  ℹ️ 使用系统 Chrome（channel='chrome'），跳过 chromium 下载")

    print("=== 3. Amazon scraper ===")
    if not Path(AMZ_REPO).exists():
        run(f"git clone --depth 1 https://github.com/omkarcloud/amazon-scraper {AMZ_REPO}")
    else:
        print(f"  ✓ 已存在 {AMZ_REPO}")
    if not (AMZ_REPO / ".venv").exists():
        run(f"{sys.executable} -m venv {AMZ_REPO / '.venv'}")
        run(f"{AMZ_REPO / '.venv' / 'bin' / 'pip'} install -q -r {AMZ_REPO / 'requirements.txt'}")
    else:
        print(f"  ✓ venv 已存在")

    print("=== 4. 目录准备 ===")
    for d in ("output", "output_amazon"):
        (ROOT / d).mkdir(parents=True, exist_ok=True)
    print("  ✓ output/ 与 output_amazon/ 就绪")

    print("\n✅ 完成。快速验证：")
    print("   # Amazon 跑 5 条")
    print(f"   AMZ_KEYWORD='laundry bag' AMZ_LIMIT=5 {AMZ_REPO / '.venv' / 'bin' / 'python'} {ROOT / 'amazon_collect.py'}")
    print("   # Temu 列表页")
    print(f"   {ROOT / '.venv' / 'bin' / 'python'} {ROOT / 'temu_collect.py'} --mode api --limit 40 --images")

if __name__ == "__main__":
    if "--check" in sys.argv:
        check()
    else:
        setup()
