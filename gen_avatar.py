#!/usr/bin/env python3
"""生成专家头像 expert.png（512x512）。

分类 11-SecurityCompliance 的主色调是 dark grey-blue。
图形语义：一张照片底片 + 放大镜（镜内是被放大的像素方块）+ AIGC 标识标签。
不用人像，是因为这个专家的产出是"结论与证据"，不是人格化服务。

4 倍超采样绘制后降采样，边缘无锯齿。
"""
import pathlib
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

S = 4                      # 超采样倍数
W = 512                    # 逻辑尺寸
N = W * S

BG_TOP = (38, 52, 65)
BG_BOT = (20, 28, 38)
CARD = (242, 245, 248)
RING = (201, 212, 222)
GOLD = (200, 162, 74)
INK = (26, 34, 44)


def lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def background():
    im = Image.new("RGB", (N, N), BG_BOT)
    d = ImageDraw.Draw(im)
    for y in range(N):
        d.line([(0, y), (N, y)], fill=lerp(BG_TOP, BG_BOT, y / (N - 1)))
    # 像素网格（暗示像素级取证）
    grid = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    step = 32 * S
    for x in range(0, N, step):
        gd.line([(x, 0), (x, N)], fill=(120, 150, 180, 22))
    for y in range(0, N, step):
        gd.line([(0, y), (N, y)], fill=(120, 150, 180, 22))
    im = Image.alpha_composite(im.convert("RGBA"), grid)

    # 右上角冷光晕，让画面不闷
    glow = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse(
        [int(300 * S), int(-140 * S), int(760 * S), int(320 * S)],
        fill=(120, 165, 210, 40))
    glow = glow.filter(ImageFilter.GaussianBlur(40 * S))
    return Image.alpha_composite(im, glow)


def photo_card():
    """倾斜的照片底片，带投影。"""
    pad = 60 * S
    card = Image.new("RGBA", (260 * S + pad * 2, 220 * S + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    x0, y0 = pad, pad
    x1, y1 = pad + 260 * S, pad + 220 * S
    d.rounded_rectangle([x0, y0, x1, y1], radius=10 * S, fill=CARD)

    # 照片内容：天空 + 地面 + 一个纸箱（签收图意象）
    ix0, iy0, ix1, iy1 = x0 + 14 * S, y0 + 14 * S, x1 - 14 * S, y1 - 14 * S
    inner = Image.new("RGB", (ix1 - ix0, iy1 - iy0))
    idr = ImageDraw.Draw(inner)
    h = iy1 - iy0
    for y in range(h):
        idr.line([(0, y), (ix1 - ix0, y)], fill=lerp((150, 172, 190), (196, 208, 218),
                                                     y / (h - 1)))
    idr.rectangle([0, int(h * 0.68), ix1 - ix0, h], fill=(108, 116, 108))
    idr.ellipse([int(h * 0.10), int(h * 0.10), int(h * 0.10) + int(h * 0.16),
                 int(h * 0.10) + int(h * 0.16)], fill=(238, 236, 224))
    # 纸箱
    bw, bh = int((ix1 - ix0) * 0.34), int(h * 0.30)
    bx = int((ix1 - ix0) * 0.36)
    by = int(h * 0.68) - bh
    idr.rectangle([bx, by, bx + bw, by + bh], fill=(168, 122, 74))
    idr.rectangle([bx, by, bx + bw, by + int(bh * 0.22)], fill=(148, 106, 62))
    idr.line([(bx + bw // 2, by), (bx + bw // 2, by + bh)], fill=(210, 190, 160),
             width=max(1, S // 2))

    card.paste(inner, (ix0, iy0))
    d.rounded_rectangle([x0, y0, x1, y1], radius=10 * S, outline=(206, 214, 222),
                        width=2 * S)
    return card.rotate(7, resample=Image.BICUBIC, expand=False)


def lens(card_mosaic):
    """放大镜：镜内是放大后的像素块。"""
    layer = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx, cy, r = 332 * S, 302 * S, 86 * S

    # 阴影
    sh = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse([cx - r, cy - r, cx + r, cy + r], fill=(0, 0, 0, 110))
    sh = sh.filter(ImageFilter.GaussianBlur(10 * S))
    layer = Image.alpha_composite(layer, sh)

    # 镜内：马赛克像素块（7x7，块边界再描一道网格线）
    mask = Image.new("L", (N, N), 0)
    ImageDraw.Draw(mask).ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    cells = 7
    pix = card_mosaic.resize((cells, cells), Image.NEAREST)
    pix = pix.resize((int(r * 2), int(r * 2)), Image.NEAREST)
    gd = ImageDraw.Draw(pix)
    cw = (r * 2) / cells
    for i in range(1, cells):
        gd.line([(cw * i, 0), (cw * i, r * 2)], fill=(255, 255, 255, 46), width=S)
        gd.line([(0, cw * i), (r * 2, cw * i)], fill=(255, 255, 255, 46), width=S)
    glass = Image.new("RGBA", (int(r * 2), int(r * 2)), (255, 255, 255, 0))
    glass.paste(pix, (0, 0))
    canvas = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    canvas.paste(glass, (int(cx - r), int(cy - r)))
    layer = Image.alpha_composite(layer, Image.composite(
        canvas, Image.new("RGBA", (N, N), (0, 0, 0, 0)), mask))

    # 冷色玻璃罩 + 高光
    tint = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    td = ImageDraw.Draw(tint)
    td.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(90, 140, 190, 40))
    hi = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    hd = ImageDraw.Draw(hi)
    hd.pieslice([cx - r * 0.78, cy - r * 0.92, cx + r * 0.2, cy - r * 0.05],
                start=200, end=320, fill=(255, 255, 255, 90))
    tint = Image.alpha_composite(tint, hi)
    layer = Image.alpha_composite(layer, Image.composite(
        tint, Image.new("RGBA", (N, N), (0, 0, 0, 0)), mask))

    # 镜圈
    d2 = ImageDraw.Draw(layer)
    d2.ellipse([cx - r, cy - r, cx + r, cy + r], outline=RING, width=11 * S)
    d2.ellipse([cx - r + 6 * S, cy - r + 6 * S, cx + r - 6 * S, cy + r - 6 * S],
               outline=(255, 255, 255, 60), width=2 * S)

    # 手柄（收短，避免圆形裁切时被切掉尖端）
    hx0, hy0 = cx + int(r * 0.68), cy + int(r * 0.68)
    hx1, hy1 = cx + int(r * 1.38), cy + int(r * 1.38)
    d2.line([(hx0, hy0), (hx1, hy1)], fill=RING, width=22 * S)
    d2.line([(hx0, hy0), (hx1, hy1)], fill=(225, 233, 240), width=12 * S)
    d2.ellipse([hx1 - 9 * S, hy1 - 9 * S, hx1 + 9 * S, hy1 + 9 * S], fill=RING)
    return layer


def chip(font):
    """AIGC 标识标签。"""
    layer = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x0, y0, x1, y1 = 82 * S, 84 * S, 232 * S, 136 * S
    d.rounded_rectangle([x0 + 3 * S, y0 + 3 * S, x1 + 3 * S, y1 + 3 * S],
                        radius=12 * S, fill=(0, 0, 0, 90))
    d.rounded_rectangle([x0, y0, x1, y1], radius=12 * S, fill=GOLD)
    d.text(((x0 + x1) / 2, (y0 + y1) / 2 + 1 * S), "AIGC", font=font,
           fill=INK, anchor="mm")
    return layer


def find_font(size):
    for p in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf",
              "/System/Library/Fonts/Supplemental/Arial.ttf",
              "/Library/Fonts/Arial Bold.ttf"):
        if pathlib.Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def main():
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "expert.png")
    base = background()

    card = photo_card()
    base.alpha_composite(card, (58 * S, 148 * S))

    # 取照片局部作为镜内马赛克的取样源
    mosaic_src = base.convert("RGB")
    base.alpha_composite(lens(mosaic_src))
    base.alpha_composite(chip(find_font(34 * S)))

    base = base.convert("RGB").resize((W, W), Image.LANCZOS)
    out.parent.mkdir(parents=True, exist_ok=True)
    base.save(out, "PNG", optimize=True)
    print("saved", out, base.size, f"{out.stat().st_size/1024:.1f} KB")


if __name__ == "__main__":
    main()
