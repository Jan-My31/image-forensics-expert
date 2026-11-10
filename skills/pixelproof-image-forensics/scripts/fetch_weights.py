#!/usr/bin/env python3
"""一条命令把三个模型的权重下到 models/ 下，带镜像、断点续传和 SHA256 校验。

为什么需要这个脚本：权重不随仓库分发，四个文件合计 2.2 GB。手动拼下载命令很容易
出两类事故 —— 一是国内直连 HuggingFace 卡在 78 KB/s，二是 curl 被代理截断后
文件看着"下完了"其实只有一半（本机真遇到过：GitHub tarball 少了一个 ckpt，
解压报 "failed finding central directory"）。所以这里下载完必须过体积 + SHA256。

用法：
  python3 scripts/fetch_weights.py --list
  python3 scripts/fetch_weights.py commfor384              # 最小的那个，87 MB
  python3 scripts/fetch_weights.py commfor384 commfor224 raiw
  python3 scripts/fetch_weights.py --all
  python3 scripts/fetch_weights.py --all --check           # 只校验本地已有的文件

国内默认走 hf-mirror；想用官方源就 `HF_ENDPOINT=https://huggingface.co`。
有 aria2c 会自动用它（-x16 -s16），没有就退回单流 urllib，两者都支持续传。
"""
import argparse
import hashlib
import os
import pathlib
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENDPOINT = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com").rstrip("/")

# dest 与 scripts/run_*.py 的默认查找路径保持一致，下完就能直接跑，不用再传 --weights
MANIFEST = {
    "commfor384": {
        "repo": "OwensLab/commfor-model-384",
        "file": "model.safetensors",
        "dest": "models/commfor384/model.safetensors",
        "size": 87_262_324,
        "sha256": "b89f36275f3bf5e2b040eee36597a8f19db051bff9a473a9cf7b2466284fb387",
        "note": "通用生成图判别，ViT-S/16 384。优先下这个。",
    },
    "commfor224": {
        "repo": "OwensLab/commfor-model-224",
        "file": "model.safetensors",
        "dest": "models/commfor224/model.safetensors",
        "size": 86_678_644,
        "sha256": "a6cc439d5a6d2dfadd60c77d27a2838ad55b34e601ecd30f46ad97266d6ac4e0",
        "note": "同模型的 224 版。实测召回明显更差，只在显存/内存吃紧时用。",
    },
    "raiw": {
        "repo": "wiltodelta/raiw-source-classify",
        "file": "multi-provider-source-v3.npz",
        "dest": "models/raiw/multi-provider-source-v3.npz",
        "size": 2_030_769_977,
        "sha256": "f65dac7cd7a6d8025e0b849bba9117635d6280628c226f47b599332898580f3c",
        "note": "2 GB，厂商归属。单线程 curl 约六小时，务必用 aria2c 或多线程。",
    },
    "xai": {
        "url": "https://github.com/IDT-ITI/XAI-Deepfakes/raw/main/model/checkpoint/ff_attribution.ckpt",
        "dest": "models/xai/ff_attribution.ckpt",
        "size": 70_986_442,
        "sha256": "67d721661e164883d328b32d88ff938cd8e80c77cb9c96c15e4570ddd32bdf8a",
        "note": "换脸五分类。只认人脸，别喂商品图。GitHub 直连不通时见 --gh-mirror。",
    },
}
ORDER = ["commfor384", "commfor224", "xai", "raiw"]


def url_of(key, gh_mirror=None):
    m = MANIFEST[key]
    if "url" in m:
        u = m["url"]
        if gh_mirror:
            u = gh_mirror.rstrip("/") + "/" + u
        return u
    return f"{ENDPOINT}/{m['repo']}/resolve/main/{m['file']}"


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}"
        n /= 1024


def sha256_of(path, block=1 << 22):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(block), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(key, path):
    """体积 + SHA256 双重校验。返回 (ok, 说明)。"""
    m = MANIFEST[key]
    got = path.stat().st_size
    if got != m["size"]:
        return False, f"体积不符：期望 {m['size']:,}，实际 {got:,}（差 {m['size'] - got:,}）"
    digest = sha256_of(path)
    if digest != m["sha256"]:
        return False, f"SHA256 不符：期望 {m['sha256'][:16]}…，实际 {digest[:16]}…"
    return True, "体积与 SHA256 均一致"


def download_aria2(url, tmp, jobs):
    exe = shutil.which("aria2c")
    if not exe:
        return False
    cmd = [exe, "-x", str(jobs), "-s", str(jobs), "--continue=true",
           "--auto-file-renaming=false", "--allow-overwrite=true",
           "--summary-interval=5", "--console-log-level=warn",
           "-d", str(tmp.parent), "-o", tmp.name, url]
    print(f"  aria2c -x{jobs} 下载中…")
    return subprocess.call(cmd) == 0


def download_urllib(url, tmp):
    """单流下载，支持 Range 续传，每 2 秒打一次进度。"""
    have = tmp.stat().st_size if tmp.exists() else 0
    req = urllib.request.Request(url)
    if have:
        req.add_header("Range", f"bytes={have}-")
        print(f"  续传，已有 {human(have)}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            total = int(r.headers.get("Content-Length") or 0) + have
            mode = "ab" if have and r.status == 206 else "wb"
            if mode == "wb":
                have = 0
            t0, last = time.time(), 0.0
            with open(tmp, mode) as f:
                while True:
                    chunk = r.read(1 << 18)
                    if not chunk:
                        break
                    f.write(chunk)
                    have += len(chunk)
                    now = time.time()
                    if now - last > 2:
                        last = now
                        speed = have / max(now - t0, 1e-6)
                        pct = f"{have / total * 100:5.1f}%" if total else "  ?  "
                        print(f"\r  {pct}  {human(have)}"
                              f"{' / ' + human(total) if total else ''}  {human(speed)}/s",
                              end="", flush=True)
            print()
        return True
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        print(f"\n  下载失败：{e}")
        return False


def handle(key, args):
    m = MANIFEST[key]
    dest = ROOT / m["dest"]
    print(f"\n[{key}] {m['note']}")
    print(f"  目标：{m['dest']}（{human(m['size'])}）")

    if dest.exists():
        ok, why = verify(key, dest)
        if ok:
            print(f"  ✓ 已存在且校验通过，跳过")
            return True
        print(f"  ! 已存在但校验失败（{why}），重新下载")
        dest.unlink()

    if args.check:
        print(f"  ✗ 缺失")
        return False

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    url = url_of(key, args.gh_mirror)
    print(f"  来源：{url}")

    if not args.no_aria2 and download_aria2(url, tmp, args.jobs):
        pass
    elif not download_urllib(url, tmp):
        print(f"  ✗ 未完成。可换源重试：")
        print(f"    HF_ENDPOINT=https://huggingface.co python3 {sys.argv[0]} {key}")
        if "url" in m:
            print(f"    或加 --gh-mirror <镜像前缀> 走 GitHub 镜像")
        if tmp.exists():
            print(f"    已下载部分保留在 {tmp.name}，重跑会自动续传")
        return False

    if not tmp.exists():
        print(f"  ✗ 下载器没有产出文件")
        return False

    ok, why = verify(key, tmp)
    if not ok:
        print(f"  ✗ 校验失败：{why}")
        print(f"    这通常是代理或镜像截断。删掉重下的文件，重跑本命令。")
        tmp.unlink()
        return False

    tmp.replace(dest)
    print(f"  ✓ 校验通过，已就位 {m['dest']}")
    return True


def main():
    ap = argparse.ArgumentParser(
        description="下载 pixelproof-image-forensics 的模型权重（默认走 hf-mirror）")
    ap.add_argument("keys", nargs="*", metavar="模型",
                    help=f"可选：{', '.join(ORDER)}")
    ap.add_argument("--all", action="store_true", help="下载全部四个")
    ap.add_argument("--list", action="store_true", help="只列出清单和状态")
    ap.add_argument("--check", action="store_true", help="只校验，不下载")
    ap.add_argument("--jobs", type=int, default=16, help="aria2c 连接数，默认 16")
    ap.add_argument("--no-aria2", action="store_true", help="强制用单流 urllib")
    ap.add_argument("--gh-mirror", default=None,
                    help="GitHub 镜像前缀，用于 xai 权重，如 https://ghfast.top")
    args = ap.parse_args()

    if args.list:
        print(f"权重清单（源：{ENDPOINT}）\n")
        for k in ORDER:
            m = MANIFEST[k]
            p = ROOT / m["dest"]
            state = "已就位" if p.exists() else "缺失"
            if p.exists():
                ok, _ = verify(k, p)
                state = "已就位 ✓" if ok else "存在但校验失败"
            print(f"  {k:11} {human(m['size']):>9}  {state}")
            print(f"             {m['note']}")
        print(f"\n下载：python3 scripts/fetch_weights.py --all")
        return 0

    keys = ORDER if args.all else args.keys
    if not keys:
        ap.error("指定模型名，或用 --all / --list")
    unknown = [k for k in keys if k not in MANIFEST]
    if unknown:
        ap.error(f"不认识的模型名：{', '.join(unknown)}；可选 {', '.join(ORDER)}")

    results = {k: handle(k, args) for k in keys}

    print("\n" + "-" * 52)
    for k, ok in results.items():
        print(f"  {k:11} {'✓ 可用' if ok else '✗ 未就绪'}")
    if all(results.values()):
        print("\n四个都能用之后，像素层这么跑：")
        print("  python3 scripts/probe.py 图.jpg --model models/commfor384")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
