#!/usr/bin/env python3
"""RAIW multi-provider source classifier 本地推理。

模型：wiltodelta/raiw-source-classify 的 multi-provider-source-v3.npz（约 2.03 GB）
安装：pip install "remove-ai-watermarks[source-classify]"
权重：从 HF 仓库 wiltodelta/raiw-source-classify 下载，或用 --weights 指定本地路径
      （也可用环境变量 RAIW_SOURCE_CLASSIFY_WEIGHTS）

输出：10 个厂商类别 + unknown，以及是否 abstain（拒判）

注意：这个分类器的设计是"宁可弃权也不乱猜"。实测 17 个样本全部
      label=unknown / reason=abstained，confidence 在 0.0007~0.2185。
      弃权等于没答案——不要把它当通用 AI 判别器用。
"""
import argparse
import dataclasses
import json
import os
import pathlib
import sys

DEFAULT_WEIGHTS = pathlib.Path(__file__).parent.parent / "models/raiw/multi-provider-source-v3.npz"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--weights", default=None, help="npz 权重路径")
    ap.add_argument("--out", default=None, help="可选，输出 JSON 路径")
    a = ap.parse_args()

    w = a.weights or os.environ.get("RAIW_SOURCE_CLASSIFY_WEIGHTS") or str(DEFAULT_WEIGHTS)
    if not pathlib.Path(w).exists():
        sys.exit(f"[fail] 找不到权重：{w}\n"
                 f"       下载 wiltodelta/raiw-source-classify 的 "
                 f"multi-provider-source-v3.npz（约 2 GB），或用 --weights 指定路径。")
    os.environ["RAIW_SOURCE_CLASSIFY_WEIGHTS"] = w

    try:
        from remove_ai_watermarks import classify_source
    except ImportError:
        sys.exit('[fail] 未安装：pip install "remove-ai-watermarks[source-classify]"')

    rows = []
    for p in a.paths:
        if not pathlib.Path(p).exists():
            print("MISS", p)
            continue
        try:
            r = classify_source(p)
        except Exception as e:
            print(f"ERR {p}: {e}")
            continue
        if dataclasses.is_dataclass(r):
            r = dataclasses.asdict(r)
        elif hasattr(r, "__dict__"):
            r = dict(vars(r))
        r = json.loads(json.dumps(r, default=str))
        pooled = r.get("pooled_scores") or {}
        best = max(pooled, key=pooled.get) if pooled else None
        rows.append({"file": pathlib.Path(p).name, **r})
        if best:
            print(f"{pathlib.Path(p).name:34s} -> {r.get('label', '?'):18s} "
                  f"conf={float(r.get('confidence') or 0):.4f}  "
                  f"reason={r.get('reason')}  最高分={best}({pooled[best]:.2f})")
        else:
            print(f"{pathlib.Path(p).name:34s} -> {r.get('label', '?')}")

    if a.out:
        pathlib.Path(a.out).write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print("saved", a.out)


if __name__ == "__main__":
    main()
