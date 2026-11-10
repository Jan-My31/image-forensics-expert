#!/usr/bin/env python3
"""重复图 / 搬运图排查：感知哈希 + 尺寸与元数据比对。

pHash 抗缩放、抗重压缩、抗轻微调色；同一张图的不同版本汉明距离通常 <10。
用法：
  python3 phash.py hash  图片...        # 打印每张图的 pHash / dHash / 边长
  python3 phash.py cmp   查询图 库目录   # 在目录里找最相似的图
"""
import os
import sys

import numpy as np
from PIL import Image

SIZE = 32
LOW = 8


def _gray(im, size=SIZE):
    return im.convert("L").resize((size, size), Image.LANCZOS)


_DCT_CACHE = {}


def _dct_matrix(n):
    """DCT-II 的变换矩阵。32x32 自己算比装 opencv 划算。"""
    if n not in _DCT_CACHE:
        k = np.arange(n)[:, None]
        x = np.arange(n)[None, :]
        _DCT_CACHE[n] = np.cos(np.pi * k * (2 * x + 1) / (2 * n)).astype(np.float32)
    return _DCT_CACHE[n]


def dct2(g):
    """二维 DCT-II，等价于 cv2.dct 的可分离实现。"""
    d = _dct_matrix(g.shape[0])
    return d @ g @ d.T


def phash(im):
    g = np.asarray(_gray(im), dtype=np.float32)
    dct = dct2(g)
    block = dct[:LOW, :LOW].flatten()
    med = np.median(block[1:])
    return "".join("1" if v > med else "0" for v in block)


def dhash(im):
    g = np.asarray(im.convert("L").resize((LOW + 1, LOW), Image.LANCZOS), dtype=np.int16)
    diff = g[:, 1:] > g[:, :-1]
    return "".join("1" if v else "0" for v in diff.flatten())


def hamming(a, b):
    return sum(x != y for x, y in zip(a, b))


def hash_file(path):
    with Image.open(path) as im:
        if im.format == "MPO":
            im.seek(0)
        return phash(im), dhash(im), im.size, im.format


def cmd_hash(paths):
    print(f"{'file':42} {'pHash':64} {'dHash':16} size fmt")
    for p in paths:
        ph, dh, size, fmt = hash_file(p)
        print(f"{os.path.basename(p)[:40]:42} {ph} {dh} {size[0]}x{size[1]} {fmt}")


def cmd_cmp(query, lib_dir):
    qp, qd, qsize, _ = hash_file(query)
    rows = []
    for name in sorted(os.listdir(lib_dir)):
        if name.startswith(".") or name == os.path.basename(query):
            continue
        p = os.path.join(lib_dir, name)
        try:
            hp, hd, hsize, _ = hash_file(p)
        except Exception:
            continue
        rows.append((hamming(qp, hp), hamming(qd, hd), name, hsize))
    rows.sort()
    print(f"query: {os.path.basename(query)}  {qsize[0]}x{qsize[1]}")
    print(f"{'pHash':>6} {'dHash':>6}  file")
    for a, b, name, size in rows[:12]:
        flag = "  <= 疑似同源" if a <= 10 else ""
        print(f"{a:>6} {b:>6}  {name[:52]:54}({size[0]}x{size[1]}){flag}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "hash"
    if mode == "hash":
        cmd_hash(sys.argv[2:])
    elif mode == "cmp":
        cmd_cmp(sys.argv[2], sys.argv[3])
    else:
        print(__doc__)
