#!/usr/bin/env python3
"""自检：不依赖网络、不依赖预训练权重，30 秒内证明这个 skill 的三层判断是对的。

跑法：python3 tests/selftest.py
退出码 0 = 全部通过，1 = 有失败（可直接接到 CI）。

断言的是四件事：
  1 带 AIGC 标识的 PNG 能被判成 AI-SIGNED，且 Label / ContentProducer 解析正确
  2 同一张图重存成 JPEG 之后，标识必须消失，不能误报
  3 干净图片必须落到 NO-EVIDENCE（而不是被判成假图）
  4 重存后的副本与原图 pHash 距离 <= 2，必须被判成 DUPLICATE
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import probe  # noqa: E402

FX = HERE / "fixtures"
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def main():
    for need in ("labeled.png", "stripped.jpg", "plain.png"):
        if not (FX / need).exists():
            print("缺素材，先跑：python3 tests/make_fixtures.py")
            return 1

    labeled = FX / "labeled.png"
    stripped = FX / "stripped.jpg"
    plain = FX / "plain.png"

    print("自检 · pixelproof-image-forensics")
    print("-" * 58)

    # 1 标识能被读出并归类
    m = probe.metadata_layer(labeled)
    tag, _why = probe.verdict(m, {"checked": False}, {"available": False})
    check("带 AIGC 标识的 PNG 判为 AI-SIGNED", tag == "AI-SIGNED", f"实际 {tag}")
    check("Label 解析为 1", str(m.get("aigc_label_value")) == "1",
          f"字段 {m.get('aigc_label_value')}")
    check("ContentProducer 非空", bool(m.get("aigc_producer")),
          str(m.get("aigc_producer")))

    # 2 重存即失效，且不能误报
    ms = probe.metadata_layer(stripped)
    tag_s, _ = probe.verdict(ms, {"checked": False}, {"available": False})
    check("重存成 JPEG 后标识消失", not ms.get("aigc_label"), "仍是 {}")
    check("重存后不误判为 AI", tag_s != "AI-SIGNED", f"实际 {tag_s}")

    # 3 干净图不能被打成假图
    mp = probe.metadata_layer(plain)
    tag_p, _ = probe.verdict(mp, {"checked": False}, {"available": False})
    check("干净图片落 NO-EVIDENCE", tag_p == "NO-EVIDENCE", f"实际 {tag_p}")

    # 4 查重能认出同一张图的另存版
    lib = {labeled.name: probe.hash_file(str(labeled))}
    dup = probe.duplicate_layer(stripped, lib)
    check("重存副本被判 DUPLICATE", dup.get("is_duplicate") is True,
          f"距离 {dup.get('distance')}（阈值 10）")
    dist = dup.get("distance")
    check("距离在 0~2 之间", dist is not None and 0 <= dist <= 2, f"距离 {dist}")

    passed = sum(1 for _n, ok, _d in results if ok)
    total = len(results)
    print("-" * 58)
    print(f"{passed}/{total} 通过")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
