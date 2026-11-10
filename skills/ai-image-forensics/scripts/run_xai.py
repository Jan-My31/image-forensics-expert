#!/usr/bin/env python3
"""XAI-Deepfakes (ICMR'24 workshop) 本地推理 —— 换脸（face swap）五分类。

模型：timm/tf_efficientnetv2_b0.in1k，num_classes=5
权重：仓库内的 model/checkpoint/ff_attribution.ckpt（约 70 MB，Lightning ckpt）
      用 --weights 指定，或环境变量 XAI_DEEPFAKES_CKPT
输出：Real / NeuralTextures / Face2Face / DeepFakes / FaceSwap
预处理：Resize(224, antialias=False) -> ImageNet Normalize（见 explanation/evaluate.py）

⚠️ 这是换脸分类器，训练数据是 FaceForensics++ 的人脸帧。
   实测把 10 张普通真实照片里的 5 张判成换脸（R02 Face2Face .47 / R03 .54 /
   R06 NeuralTextures .95 / R08 FaceSwap .32 / R10 DeepFakes .27）。
   商品图、包装图、订单签收图绝不能喂给它。
"""
import argparse
import csv
import os
import pathlib
import sys

LAB = ["Real", "NeuralTextures", "Face2Face", "DeepFakes", "FaceSwap"]
DEFAULT_CKPT = (pathlib.Path(__file__).parent.parent
                / "models/xai/ff_attribution.ckpt")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--weights", default=None, help="ff_attribution.ckpt 路径")
    ap.add_argument("--out", default=None, help="可选，输出 CSV 路径")
    ap.add_argument("--threads", type=int, default=8)
    a = ap.parse_args()

    ckpt = (a.weights or os.environ.get("XAI_DEEPFAKES_CKPT") or str(DEFAULT_CKPT))
    if not pathlib.Path(ckpt).exists():
        sys.exit(f"[fail] 找不到权重：{ckpt}\n"
                 f"       从 XAI-Deepfakes 仓库取 model/checkpoint/ff_attribution.ckpt"
                 f"（约 70 MB），或用 --weights 指定。")
    try:
        import torch
        import timm
        import torchvision.transforms.v2 as v2
        from PIL import Image
    except ImportError as e:
        sys.exit(f"[fail] 缺少依赖 {e.name}：pip install torch torchvision timm pillow")

    torch.set_num_threads(a.threads)
    tf = v2.Compose([
        v2.ToImage(),
        v2.Resize(224, interpolation=v2.InterpolationMode.BILINEAR, antialias=False),
        v2.ToDtype(torch.float32, scale=True),
        v2.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])

    m = timm.create_model("tf_efficientnetv2_b0", pretrained=False, num_classes=5)
    ck = torch.load(ckpt, map_location="cpu", weights_only=False)
    sd = {k[len("model."):]: v for k, v in ck["state_dict"].items()
          if k.startswith("model.")}
    missing, unexpected = m.load_state_dict(sd, strict=False)
    print(f"[ckpt] epoch={ck.get('epoch')} step={ck.get('global_step')} "
          f"missing={len(missing)} unexpected={len(unexpected)}")
    m.eval()

    rows = []
    with torch.no_grad():
        for p in a.paths:
            p = pathlib.Path(p)
            if not p.exists():
                print("MISS", p)
                continue
            x = tf(Image.open(p).convert("RGB")).unsqueeze(0)
            prob = torch.softmax(m(x), dim=1).squeeze()
            row = {"file": p.name, "top": LAB[int(prob.argmax())],
                   "p_real": round(float(prob[0]), 4)}
            for i, n in enumerate(LAB):
                row[n] = round(float(prob[i]), 4)
            rows.append(row)
            print(f"{p.name:34s} -> {row['top']:14s} p_real={float(prob[0]):.3f}  "
                  + " ".join(f"{n[:4]}={float(prob[i]):.2f}" for i, n in enumerate(LAB)))

    if a.out:
        with open(a.out, "w", newline="", encoding="utf-8") as f:
            wri = csv.DictWriter(f, fieldnames=["file", "top", "p_real"] + LAB)
            wri.writeheader()
            wri.writerows(rows)
        print("saved", a.out)


if __name__ == "__main__":
    main()
