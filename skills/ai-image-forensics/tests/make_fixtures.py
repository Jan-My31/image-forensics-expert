#!/usr/bin/env python3
"""现场合成自检素材，不依赖任何第三方图片。

产出（tests/fixtures/）：
  labeled.png    带 TC260 AIGC 标识（eXIf -> EXIF UserComment 0x9286，ASCII JSON）
  stripped.jpg   同一张图用 JPEG q92 重存一次，标识应消失
  plain.png      干净的合成图，没有任何标识

为什么自己造而不用真图：真图有版权，且体积大。这里只需要验证「读得到 / 丢得掉 /
比得出」三件事，图案是什么不重要。
"""
import struct
import zlib
import pathlib

from PIL import Image, ImageDraw

OUT = pathlib.Path(__file__).parent / "fixtures"
OUT.mkdir(parents=True, exist_ok=True)

LABEL = (
    '{"AIGC": {"Label": "1", "ContentProducer": "00000000000000000000N000", '
    '"ProduceID": "selftest-fixture-0001", "ReservedCode1": '
    '"{\\"Type\\":\\" TC260PG\\",\\"Version\\":1,\\"AlgID\\":\\"sm3\\",\\"SignAlgID\\":\\"sm2\\"}"}}'
)


def draw_scene(w=800, h=600):
    """画一张有梯度、有边缘、有文字的图，让 pHash 有稳定的低频结构。"""
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / (h - 1)
        d.line([(0, y), (w, y)],
               fill=(int(40 + 120 * t), int(90 + 60 * t), int(150 - 40 * t)))
    d.rectangle([80, 120, 360, 400], fill=(230, 210, 170), outline=(40, 40, 40), width=6)
    d.rectangle([420, 220, 720, 480], fill=(190, 60, 50), outline=(30, 30, 30), width=6)
    d.line([(0, 520), (w, 520)], fill=(250, 250, 250), width=8)
    return img


def build_exif_with_aigc(text: str) -> bytes:
    """手搓一段最小 TIFF：IFD0 指向 ExifIFD，ExifIFD 里放 UserComment(0x9286)。"""
    payload = b"ASCII\x00\x00\x00" + text.encode("utf-8")
    ifd0_off, exif_off, data_off = 8, 26, 44
    head = struct.pack("<2sHI", b"II", 42, ifd0_off)
    ifd0 = struct.pack("<H", 1)
    ifd0 += struct.pack("<HHII", 0x8769, 4, 1, exif_off)   # ExifIFD 指针
    ifd0 += struct.pack("<I", 0)                            # 无下一个 IFD
    exif = struct.pack("<H", 1)
    exif += struct.pack("<HHII", 0x9286, 7, len(payload), data_off)
    exif += struct.pack("<I", 0)
    blob = head + ifd0 + exif
    assert len(blob) == data_off, f"偏移算错了：{len(blob)} != {data_off}"
    return blob + payload


def png_chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def png_with_exif(img, exif: bytes) -> bytes:
    """把 eXIf 段插到 IHDR 之后，其余交给 zlib 内存编码。"""
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    raw = buf.getvalue()
    # PNG 结构：8 字节签名 + IHDR 整块（4 长度 + 4 类型 + 13 数据 + 4 CRC = 25）
    ihdr_end = 8 + 25
    return raw[:ihdr_end] + png_chunk(b"eXIf", exif) + raw[ihdr_end:]


def main():
    scene = draw_scene()

    labeled = OUT / "labeled.png"
    labeled.write_bytes(png_with_exif(scene, build_exif_with_aigc(LABEL)))

    scene.save(OUT / "stripped.jpg", "JPEG", quality=92)
    scene.save(OUT / "plain.png", "PNG")

    for p in sorted(OUT.iterdir()):
        print(f"{p.name:14s} {p.stat().st_size:>8d} B")


if __name__ == "__main__":
    main()
