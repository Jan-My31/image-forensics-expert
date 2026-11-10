# ai-image-forensics

判断一张图是 **AI 生成**、**P 过**，还是**重复图**。三层取证，一条命令，国内合规标识原生支持。

不训练模型、不上传图片、不需要 GPU。

```bash
python3 scripts/probe.py 图1.jpg 图2.png
```

```
A01.png   ->   AI-SIGNED
  理由：文件里有 AIGC 合规标识（Label=1），这是生成方的自证
  元数据：aigc_label | 格式 PNG 1024x1536
```

## 为什么做这个

现成的开源检测器基本都盯着 C2PA、SynthID、Midjourney、Stable Diffusion 这几套，
**没有一个认中国的 TC260 AIGC 隐式标识**。而国内合规生成的图恰恰都带这个标识，
它就藏在 PNG 的 `eXIf` chunk 里、EXIF UserComment(0x9286) 那段 ASCII JSON 里。

实测过的一个客户端工具（[image-provenance](https://github.com/863401402/image-provenance)）：
喂一张带完整 AIGC 标识的图，它显示「未发现 AI 来源凭证」。翻源码，
`src/markers.js` 里没有 AIGC、也没有 TC260 这两个词。

这个 skill 就是从那儿来的——**先把最便宜、最确定的那层做对**。

## 三层，按成本排序

| 层 | 手段 | 单张耗时 | 能定什么 |
|---|---|---|---|
| 1 元数据 | AIGC 标识 / C2PA / EXIF / 生成器指纹 | 毫秒 | 命中即定论（生成方自证） |
| 2 查重 | pHash + dHash，汉明距离 | ~20 ms | 命中即重复 |
| 3 像素 | Community-Forensics ViT-S/384（可选） | 0.2–0.75 s | 只能当线索 |

顺序别反。倒过来做，你会花一整晚在 CPU 上，拿到一个解释不了的分数。

## 四档结论

| 结论 | 含义 | 怎么用 |
|---|---|---|
| `AI-SIGNED` | 有 AIGC 国标标识或 C2PA 凭证 | 可直接采信 |
| `AI-LIKELY` | 有生成器指纹，或像素模型高分 | 人工复核 |
| `DUPLICATE` | 与图库中某张 pHash 距离 ≤10 | 可直接判重 |
| `NO-EVIDENCE` | 三层都没找到 | **不等于真图** |

## 用法

```bash
# 单张或几张
python3 scripts/probe.py a.jpg b.png

# 整个目录（顺便查重）
python3 scripts/probe.py --dir ./待审 --lib ./历史图库

# 加像素层（需要先下权重，见下）
python3 scripts/probe.py --dir ./待审 --model ./models/commfor384

# 只要 JSON，接自己的流水线
python3 scripts/probe.py --dir ./待审 --json
```

### 像素层权重（可选）

```bash
export HF_ENDPOINT=https://hf-mirror.com        # 国内直连 huggingface.co 通常不通
mkdir -p models/commfor384
curl -L -o models/commfor384/model.safetensors \
  "$HF_ENDPOINT/OwensLab/commfor-model-384/resolve/main/model.safetensors"
```

不给 `--model` 就只跑前两层，纯 Python，零依赖权重。

## 三个模型脚本，分工别搞错

`run_commfor.py` 是通用生成图判别；另外两个是「专用件」，用错方向会得到一堆假阳性：

| 脚本 | 模型 | 喂什么 | 别喂什么 |
|---|---|---|---|
| `run_commfor.py` | ViT-S/16 **384**（CVPR'25） | 通用生成图 | 别用 224 版，同一批图只有 3/5 |
| `run_raiw.py` | RAIW source-classify | 想知道"哪家生成的" | 别当判别器，实测 17/17 弃权 |
| `run_xai.py` | EfficientNetV2-B0 五分类 | **只喂人脸** | 商品图/签收图，10 张真图误判 5 张 |

```bash
python3 scripts/run_commfor.py 图.jpg --size 384 --weights ./models/commfor384/model.safetensors
python3 scripts/run_raiw.py     图.jpg --weights ./models/raiw/multi-provider-source-v3.npz
python3 scripts/run_xai.py    人脸.jpg --weights ./models/xai/ff_attribution.ckpt
```

三者统一查找顺序：`--weights` > 环境变量（`COMMFOR_384_WEIGHTS` / `RAIW_SOURCE_CLASSIFY_WEIGHTS` / `XAI_DEEPFAKES_CKPT`）> `models/<型号>/`。不传 `--out` 只打印，不落盘。

实测复现（MacBook M1 CPU / torch 2.12）：

```
[ok] 384 版权重全部匹配（152/152）
手机拍的破损快递箱_...png      logit= -7.3723  p_fake=0.0006      64 ms
手机拍摄的快递员送件现场_...png logit= -6.2384  p_fake=0.0019      93 ms
real02.jpg  -> Face2Face      p_real=0.320   ← 真图，被误判为换脸
real06.jpg  -> NeuralTextures p_real=0.042   ← 真图，误判 0.95
real01.jpg  -> unknown  conf=0.0007  reason=abstained  最高分=openai(-6.61)
```

## 怎么证明它是对的

```bash
python3 tests/make_fixtures.py     # 现场合成自检素材，不依赖任何第三方图片
python3 tests/selftest.py
```

```
自检 · ai-image-forensics
----------------------------------------------------------
  [PASS] 带 AIGC 标识的 PNG 判为 AI-SIGNED — 实际 AI-SIGNED
  [PASS] Label 解析为 1 — 字段 1
  [PASS] ContentProducer 非空 — 00000000000000000000N000
  [PASS] 重存成 JPEG 后标识消失 — 仍是 {}
  [PASS] 重存后不误判为 AI — 实际 NO-EVIDENCE
  [PASS] 干净图片落 NO-EVIDENCE — 实际 NO-EVIDENCE
  [PASS] 重存副本被判 DUPLICATE — 距离 0（阈值 10）
  [PASS] 距离在 0~2 之间 — 距离 0
----------------------------------------------------------
8/8 通过
```

素材是脚本现场画的，AIGC 标识是按 TC260 字段结构手工写进 `eXIf` 的，
所以这套自检既跑得动，也没有版权问题。

**注意**：自检证明的是「管线通、判定逻辑对」，**不证明准确率**。
准确率证据在 [`references/thresholds.md`](references/thresholds.md)，那是 17 张图
（10 真实 + 7 生成，含 68 个平台化变体）的实测记录，包括已知的翻车案例。

## 已知的边界

1. **没有标识 ≠ 真图。** 加一道另存就洗掉了，微信转发、截图、剪贴板全都会洗。实测 Pillow 重存一次，AIGC 字段必丢。
2. **像素模型不能单独定罪。** 同一个模型对 DALL·E 2 的 5 张官方测试图 5/5 判出，对 7 张 2026 年新生成图 0/7（p_fake 0.0000–0.0019）。它只对训练里见过的生成器有效。
3. **假阳性会伤到真实用户。** iPhone 拍的一张纸箱照被 384 版判成 0.896。像素层的输出只能进「存疑」。
4. **裁剪会漏查重。** 缩放/压缩/截图距离 0–2，裁掉 7.5% 边缘涨到 8–24。

## 文件

```
SKILL.md                  给 agent 读的使用说明
scripts/probe.py          三层编排 + 四档结论
scripts/exif_c2pa.py      AIGC 标识 / C2PA / EXIF 解析
scripts/phash.py          pHash + dHash（纯 numpy，不依赖 OpenCV）
scripts/run_commfor.py    通用生成图判别，独立可跑
scripts/run_raiw.py       厂商溯源，独立可跑
scripts/run_xai.py        换脸五分类，独立可跑
tests/make_fixtures.py    自检素材合成
tests/selftest.py         断言
references/thresholds.md  所有阈值的来源与实测数字
```

## 作为 agent skill 使用

这个目录本身就是一份 skill。两种装法：

```bash
# A. 直接放进 WorkBuddy 的用户级 skills 目录
git clone <this-repo> ~/.workbuddy/skills/ai-image-forensics

# B. 放进某个项目的 .workbuddy/skills/ 下，团队共用
git clone <this-repo> <项目>/.workbuddy/skills/ai-image-forensics
```

装着之后，agent 看到「这张图是不是 AI 生成的」这类问题时，会自动读 `SKILL.md`
并按里面的流程调用 `probe.py`。

## 引用到的上游项目

本仓库不包含任何第三方模型权重或数据集，只调用它们：

- [Community-Forensics](https://github.com/JeongsooP/Community-Forensics)（CVPR 2025，ViT-S 224/384）
- [image-provenance](https://github.com/863401402/image-provenance)（反面教材，见上）
- FSD（CVPR 2025，CC BY-NC-SA 4.0，非商用）
- UnivFD（CVPR 2023）、Organika/sdxl-detector、LAID（PST 2025）、XAI-Deepfakes（ICMR 2024 workshop）、wiltodelta/raiw-source-classify
- TC260《人工智能生成合成内容标识方法》AIGC 隐式标识字段
- C2PA / JUMBF 内容凭证

## 许可

MIT。上游模型各自的许可请单独确认（FSD 是非商用）。
