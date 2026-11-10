#!/usr/bin/env python3
"""Community-Forensics (CVPR 2025) 本地推理。
权重：OwensLab/commfor-model-224 或 -384（HF 镜像，各 86/87MB）
预处理（官方 dataloader.get_transform(mode='test')）：
  224: Resize(256) -> CenterCrop(224) -> ToTensor[0,1] -> ImageNet Normalize
  384: Resize(440) -> CenterCrop(384) -> 同上
输出：sigmoid(logit)，1=fake

默认用 384。实测同一批 DALL·E 2 图：224 版权重只中 3/5，384 版 5/5。
weights 查找顺序：--weights > 环境变量 COMMFOR_{size}_WEIGHTS > models/commfor{size}/model.safetensors
"""
import argparse, csv, os, pathlib, sys, time
import torch, timm
from PIL import Image
import torchvision.transforms as T

ROOT = pathlib.Path(__file__).parent.parent
MEAN = [0.485, 0.456, 0.406]
STD = [0.229, 0.224, 0.225]


def build(size, weights=None):
    w = pathlib.Path(weights or os.environ.get(f"COMMFOR_{size}_WEIGHTS")
                     or ROOT / f"models/commfor{size}/model.safetensors")
    if not w.exists():
        sys.exit(f"[fail] 找不到权重：{w}\n"
                 f"       下载 OwensLab/commfor-model-{size}（约 86/87 MB）"
                 f"的 model.safetensors，或用 --weights 指定。")
    m = timm.create_model(f"vit_small_patch16_{size}", pretrained=False, num_classes=1)
    from safetensors.torch import load_file
    sd = load_file(str(w))
    # checkpoint 来自 ViTClassifier 包装类（self.vit = timm model），键带 "vit." 前缀
    if all(k.startswith("vit.") for k in sd):
        sd = {k[len("vit."):]: v for k, v in sd.items()}
    missing, unexpected = m.load_state_dict(sd, strict=False)
    if missing or unexpected:
        print(f"[warn] missing={len(missing)} unexpected={len(unexpected)}")
    else:
        print(f"[ok] {size} 版权重全部匹配（{len(sd)}/{len(sd)}）")
    return m.eval()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--size", type=int, default=384, choices=[224, 384])
    ap.add_argument("--weights", default=None, help="model.safetensors 路径")
    ap.add_argument("--out", default=None)
    ap.add_argument("--threads", type=int, default=8)
    a = ap.parse_args()
    torch.set_num_threads(a.threads)

    resize, crop = (256, 224) if a.size == 224 else (440, 384)
    tf = T.Compose([T.Resize(resize), T.CenterCrop(crop),
                    T.ToTensor(), T.Normalize(MEAN, STD)])
    model = build(a.size, a.weights)
    out = a.out

    rows = []
    with torch.no_grad():
        for p in a.paths:
            p = pathlib.Path(p)
            if not p.exists():
                print("MISS", p); continue
            x = tf(Image.open(p).convert("RGB")).unsqueeze(0)
            t0 = time.perf_counter()
            logit = model(x).squeeze().item()
            dt = time.perf_counter() - t0
            prob = 1 / (1 + pow(2.718281828, -logit))
            rows.append({"file": p.name, "logit": round(logit, 4),
                         "p_fake": round(prob, 4), "sec": round(dt, 3)})
            print(f"{p.name:34s} logit={logit:8.4f}  p_fake={prob:6.4f}  {dt*1000:6.0f} ms")
    if out:
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["file", "logit", "p_fake", "sec"])
            w.writeheader(); w.writerows(rows)
        print("saved", out)


if __name__ == "__main__":
    main()
