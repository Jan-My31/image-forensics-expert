#!/usr/bin/env python3
"""溯源层：读取 EXIF / XMP / C2PA(JUMBF) / PNG 文本块 / JPEG 量化表。

不依赖 exiftool，纯 Python + Pillow。输出一行一条 JSON，便于批量统计。
用法：python3 exif_c2pa.py samples/real/*.jpg samples/ai/*.png
"""
import json
import os
import re
import sys
from io import BytesIO

from PIL import Image

C2PA_MARKERS = (b"c2pa", b"jumb", b"urn:uuid:", b"contentauth")


def jpeg_app_segments(path):
    """返回 JPEG 各 APPn 段 (marker, payload)。用于找 APP11 JUMBF(C2PA)。"""
    segs = []
    with open(path, "rb") as f:
        data = f.read(4 * 1024 * 1024)
    if data[:2] != b"\xff\xd8":
        return segs
    i = 2
    while i < len(data) - 4:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0xD9):
            i += 2
            continue
        length = int.from_bytes(data[i + 2:i + 4], "big")
        if length < 2:
            break
        segs.append((marker, data[i + 4:i + 2 + length]))
        if marker == 0xDA:  # SOS，后面是压缩数据
            break
        i += 2 + length
    return segs


def png_chunks(path):
    """返回 PNG 文本类 chunk 的 {关键字: 内容}。ComfyUI / A1111 常把参数写在这里。"""
    out = {}
    try:
        with Image.open(path) as im:
            info = dict(im.info)
        for k, v in info.items():
            if isinstance(v, str) and v.strip():
                out[k] = v[:300]
            elif isinstance(v, bytes) and len(v) < 4096:
                try:
                    out[k] = v.decode("utf-8", "ignore")[:300]
                except Exception:
                    pass
    except Exception:
        pass
    return out


def exif_summary(im):
    raw = im.getexif()
    if not raw:
        return {}, {}
    merged = dict(raw)
    # 子 IFD（Exif / GPS）
    for ifd_key in (0x8769, 0x8825):
        try:
            sub = raw.get_ifd(ifd_key)
            if sub:
                merged.update(dict(sub))
        except Exception:
            pass
    tags = {
        271: "Make", 272: "Model", 274: "Orientation", 305: "Software",
        306: "DateTime", 36867: "DateTimeOriginal", 37386: "LensModel",
        33434: "ExposureTime", 33437: "FNumber", 34855: "ISO",
    }
    out = {}
    for k, name in tags.items():
        if k in merged and merged[k] not in (None, ""):
            out[name] = str(merged[k])[:80] if not isinstance(merged[k], bytes) else "<bytes>"
    return out, {str(k): str(v)[:40] for k, v in merged.items() if k not in tags}


def jpeg_quality_estimate(path):
    """用标准量化表的相对偏差粗估 JPEG 质量因子（只对 JPEG 有效）。"""
    try:
        with Image.open(path) as im:
            qt = getattr(im, "quantization", None)
            if not qt:
                return None
        base = [
            16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60,
            55, 14, 13, 16, 24, 40, 57, 69, 56, 14, 17, 22, 29, 51, 87, 80,
            62, 18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104,
            113, 92, 49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98,
            112, 100, 103, 99,
        ]
        table = list(qt[0])[:64]
        ratios = [t / b for t, b in zip(table, base)]
        r = sum(ratios) / len(ratios)
        if r <= 1:
            q = 50 + 50 * (1 - r) / 0.5 if r > 0.5 else 100
        else:
            q = 50 / max(r, 1e-6)
        return int(max(1, min(100, round(q))))
    except Exception:
        return None


def find_aigc_label(path):
    """在文件头 2MB 里找 AIGC 隐式标识（TC260 标准 / 各家生成器写的 JSON）。

    常见形态：PNG eXIf 的 UserComment、JPEG APP1、XMP 字段里一段被转义的 JSON，
    键名形如 {"AIGC": {"Label": "1", "ContentProducer": ...}}。
    """
    with open(path, "rb") as f:
        head = f.read(2 * 1024 * 1024)
    idx = head.find(b"AIGC")
    if idx < 0:
        return {"found": False}
    win = head[max(0, idx - 400): idx + 12000]
    # 有的容器把整段 JSON 又转义了一层；两种形态都试
    escaped = win.replace(b'\\"', b'"').replace(b"\\/", b"/")
    for candidate in (win, escaped):
        start = candidate.find(b"{")
        while start >= 0:
            frag = candidate[start:].decode("utf-8", "ignore")
            try:
                obj, _end = json.JSONDecoder().raw_decode(frag)
                node = obj.get("AIGC", obj) if isinstance(obj, dict) else {}
                if isinstance(node, dict) and ("Label" in node or "ContentProducer" in node):
                    return {
                        "found": True,
                        "label": str(node.get("Label")),
                        "producer": str(node.get("ContentProducer"))[:32],
                        "produce_id": str(node.get("ProduceID") or "")[:44],
                        "reserved": str(node.get("ReservedCode1"))[:70],
                    }
            except Exception:
                pass
            start = candidate.find(b"{", start + 1)
    return {"found": True, "raw": win[:100].decode("utf-8", "ignore")}


def analyze(path):
    rec = {"file": os.path.basename(path), "bytes": os.path.getsize(path)}
    with Image.open(path) as im:
        rec["format"] = im.format
        rec["size"] = f"{im.width}x{im.height}"
        rec["mode"] = im.mode
        exif, other = exif_summary(im)
        rec["exif"] = exif
        rec["exif_extra_keys"] = list(other.keys())[:12]
        rec["info_keys"] = [k for k in im.info.keys()]
        rec["png_text"] = png_chunks(path) if im.format == "PNG" else {}

    rec["has_camera_exif"] = bool(exif.get("Make") and exif.get("Model"))
    rec["has_datetime_original"] = "DateTimeOriginal" in exif
    rec["aigc_label"] = find_aigc_label(path)

    # C2PA / XMP 扫描（JPEG APP11 + PNG 里搜 jumbf 签名）
    c2pa_hit, xmp_hit = False, False
    if rec["format"] in ("JPEG", "MPO"):
        for marker, payload in jpeg_app_segments(path):
            low = payload.lower()
            if marker == 0xEB and (b"jumb" in low or b"c2pa" in low):
                c2pa_hit = True
            if b"<x:xmpmeta" in low or b"ns.adobe.com/xap" in low:
                xmp_hit = True
    else:
        with open(path, "rb") as f:
            head = f.read(1024 * 1024)
        low = head.lower()
        c2pa_hit = b"jumb" in low or b"c2pa" in low
        xmp_hit = b"<x:xmpmeta" in low
    rec["c2pa_jumbf"] = c2pa_hit
    rec["xmp_present"] = xmp_hit

    if rec["format"] == "JPEG":
        rec["jpeg_quality_est"] = jpeg_quality_estimate(path)

    # 生成器指纹：PNG 文本块 / Software 字段里的关键词
    blob = " ".join([
        str(rec.get("png_text", "")), str(exif.get("Software", "")),
        str(exif.get("Model", "")),
    ]).lower()
    hits = [k for k in (
        "comfyui", "automatic1111", "stable diffusion", "midjourney", "dall",
        "flux", "novelai", "grok", "firefly", "hunyuan", "seedream",
    ) if k in blob]
    rec["generator_hints"] = hits
    return rec


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(json.dumps(analyze(p), ensure_ascii=False))
