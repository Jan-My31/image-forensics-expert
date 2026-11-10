#!/usr/bin/env python3
"""一层命令跑完三层取证，输出结构化结论。

用法：
  python3 probe.py 图1.jpg 图2.png ...
  python3 probe.py --dir 图片目录 --lib 已知图库目录     # 顺便查重复
  python3 probe.py --dir 图片目录 --model models/commfor384   # 加像素层（可选）

三层：
  1 元数据   AIGC 国标标识 / C2PA / EXIF / 生成器指纹 / 重存痕迹
  2 重复     pHash + dHash，汉明距离
  3 像素     可选，Community-Forensics ViT-S/384（需 models/commfor384 权重）

结论只分四档，宁可说"不确定"也不猜：
  AI-SIGNED   有合规标识，直接可信
  AI-LIKELY   有生成器指纹或多处编辑痕迹
  DUPLICATE   与图库里某张高度相似
  NO-EVIDENCE 没找到任何标识（不等于真图）
"""
import argparse, json, os, sys, pathlib

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))
from exif_c2pa import analyze as meta_analyze
from phash import hash_file, hamming

EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic"}


def list_images(root):
    root = pathlib.Path(root)
    return sorted(p for p in root.rglob("*")
                  if p.is_file() and p.suffix.lower() in EXTS)


def metadata_layer(path):
    r = meta_analyze(str(path))
    aigc = r.get("aigc_label") or {}
    ev = {
        "aigc_label": bool(aigc.get("found")),
        "c2pa": bool(r.get("c2pa_jumbf")),
        "xmp": bool(r.get("xmp_present")),
        "camera_exif": bool(r.get("has_camera_exif")),
        "datetime_original": bool(r.get("has_datetime_original")),
        "generator_hints": r.get("generator_hints") or [],
        "format": r.get("format"),
        "size": r.get("size"),
        "make": r.get("exif", {}).get("Make"),
        "model": r.get("exif", {}).get("Model"),
        "software": r.get("exif", {}).get("Software"),
    }
    if aigc.get("found"):
        ev["aigc_label_value"] = aigc.get("label")
        ev["aigc_producer"] = aigc.get("producer") or aigc.get("content_producer")
        ev["aigc_produce_id"] = aigc.get("produce_id")
    if "jpeg_quality_est" in r:
        ev["jpeg_quality_est"] = r["jpeg_quality_est"]
    return ev


def duplicate_layer(path, lib_hashes, threshold=10):
    if not lib_hashes:
        return {"checked": False, "reason": "未提供图库（--lib）"}
    try:
        h = hash_file(str(path))
    except Exception as e:
        return {"checked": False, "reason": str(e)}
    qp, qd, qsize = h[0], h[1], h[2]
    best, best_name = 999, None
    for name, other in lib_hashes.items():
        if name == path.name:
            continue
        d = min(hamming(qp, other[0]), hamming(qd, other[1]))
        if d < best:
            best, best_name = d, name
    return {"checked": True, "size": f"{qsize[0]}x{qsize[1]}",
            "nearest": best_name, "distance": best,
            "is_duplicate": best <= threshold}


def pixel_layer(path, model):
    try:
        import torch, timm
        from PIL import Image
        import torchvision.transforms as T
        from safetensors.torch import load_file
    except ImportError as e:
        return {"available": False, "reason": f"缺依赖：{e}"}

    w = pathlib.Path(model).expanduser()
    if w.is_dir():
        w = w / "model.safetensors"
    if not w.exists():
        return {"available": False, "reason": f"找不到权重 {w}"}

    cache = pixel_layer.__dict__.setdefault("_cache", {})
    if str(w) not in cache:
        m = timm.create_model("vit_small_patch16_384", pretrained=False, num_classes=1)
        sd = load_file(str(w))
        if all(k.startswith("vit.") for k in sd):
            sd = {k[4:]: v for k, v in sd.items()}
        m.load_state_dict(sd, strict=False)
        cache[str(w)] = m.eval()
    mdl = cache[str(w)]

    tf = T.Compose([T.Resize(440), T.CenterCrop(384), T.ToTensor(),
                    T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])])
    with torch.no_grad():
        logit = mdl(tf(Image.open(path).convert("RGB")).unsqueeze(0)).item()
    p = 1 / (1 + pow(2.718281828, -logit))
    return {"available": True, "p_fake": round(p, 4), "logit": round(logit, 3),
            "note": "p_fake>0.6 才算线索，0.1~0.6 区间不要下结论"}


def verdict(meta, dup, pix):
    if meta["aigc_label"]:
        return "AI-SIGNED", "文件里有 AIGC 合规标识（Label=1），这是生成方的自证"
    if meta["c2pa"]:
        return "AI-SIGNED", "文件里有 C2PA/JUMBF 内容凭证"
    if meta["generator_hints"]:
        return "AI-LIKELY", f"元数据里有生成器指纹：{', '.join(meta['generator_hints'])}"
    if dup.get("checked") and dup.get("is_duplicate"):
        return "DUPLICATE", f"与 {dup['nearest']} 的感知哈希距离 {dup['distance']}，阈值 10"
    if pix.get("available") and pix.get("p_fake", 0) > 0.6:
        return "AI-LIKELY", f"像素层判 p_fake={pix['p_fake']}（单一模型，仅作线索）"
    return "NO-EVIDENCE", "三层都没找到标识；这不等于真图，需要业务侧另找证据"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--dir")
    ap.add_argument("--lib", help="已知图库目录，用来查重复")
    ap.add_argument("--model", help="commfor384 权重目录，给了才跑像素层")
    ap.add_argument("--json", action="store_true", help="只输出 JSON")
    a = ap.parse_args()

    files = [pathlib.Path(p) for p in a.paths]
    if a.dir:
        files += list_images(a.dir)
    if not files:
        ap.error("给图，或者给 --dir")

    lib_hashes = {}
    if a.lib:
        for p in list_images(a.lib):
            try:
                lib_hashes[p.name] = hash_file(str(p))
            except Exception:
                continue

    out = []
    for f in files:
        # 用 is_file 而不是 exists：空字符串会变成 "."，exists 为真但打开会炸
        if not str(f).strip() or not f.is_file():
            print(f"[skip] 不是文件 {f!s}", file=sys.stderr); continue
        meta = metadata_layer(f)
        dup = duplicate_layer(f, lib_hashes)
        pix = pixel_layer(f, a.model) if a.model else {"available": False}
        tag, why = verdict(meta, dup, pix)
        rec = {"file": str(f), "verdict": tag, "reason": why,
               "metadata": meta, "duplicate": dup, "pixel": pix}
        out.append(rec)
        if not a.json:
            print(f"\n{'='*70}\n{os.path.basename(str(f))}   ->   {tag}")
            print(f"  理由：{why}")
            flags = [k for k in ("aigc_label", "c2pa", "camera_exif",
                                 "datetime_original") if meta.get(k)]
            print(f"  元数据：{', '.join(flags) if flags else '无正向标记'}"
                  f" | 格式 {meta['format']} {meta['size']}")
            if meta.get("software"):
                print(f"  软件：{meta['software']}")
            if dup.get("checked"):
                print(f"  重复：最近 {dup['nearest']} 距离 {dup['distance']}"
                      f"{'  ≤10 判重复' if dup['is_duplicate'] else ''}")
            if pix.get("available"):
                print(f"  像素：p_fake={pix['p_fake']}")

    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        from collections import Counter
        c = Counter(r["verdict"] for r in out)
        print(f"\n{'='*70}\n合计 {len(out)} 张：" +
              "  ".join(f"{k}={v}" for k, v in c.most_common()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
