# ai-image-forensics

[![selftest](https://github.com/Jan-My31/ai-image-forensics/actions/workflows/selftest.yml/badge.svg)](https://github.com/Jan-My31/ai-image-forensics/actions/workflows/selftest.yml)
[![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.10%20%7C%203.12%20%7C%203.13-blue.svg)](#安装)

判断一张图是 **AI 生成**、**P 过**，还是**重复图**。三层取证，一条命令，国内合规标识原生支持。

不训练模型、不上传图片、不需要 GPU。

```bash
pip install -r requirements.txt
python3 scripts/probe.py 图1.png 图2.jpg
```

```
图1.png   ->   AI-SIGNED
  理由：文件里有 AIGC 合规标识（Label=1），这是生成方的自证
  元数据：aigc_label | 格式 PNG 1024x1536

======================================================================
图2.jpg   ->   NO-EVIDENCE
  理由：三层都没找到标识；这不等于真图，需要业务侧另找证据
  元数据：无正向标记 | 格式 JPEG 4000x2667

======================================================================
合计 2 张：AI-SIGNED=1  NO-EVIDENCE=1
```

> 四档结论里最常见的是 `NO-EVIDENCE`（查不出）。这不是失败——说"查不出来"是专业，硬给结论才是不专业。

---

## 目录

- [它解决什么问题](#它解决什么问题)
- [三层，按成本排序](#三层按成本排序)
- [四档结论](#四档结论)
- [安装](#安装)
- [用法](#用法)
- [一个真实例子：元数据和模型打架时听谁的](#一个真实例子元数据和模型打架时听谁的)
- [电商签收图：先建库，再查单](#电商签收图先建库再查单)
- [三个模型脚本，分工别搞错](#三个模型脚本分工别搞错)
- [权重下载](#权重下载)
- [阈值速查](#阈值速查)
- [怎么证明它是对的](#怎么证明它是对的)
- [性能](#性能)
- [已知的边界（也是它不做的事）](#已知的边界也是它不做的事)
- [文件结构](#文件结构)
- [排错](#排错)
- [作为 agent skill 使用](#作为-agent-skill-使用)
- [上游引用](#上游引用)
- [许可](#许可)
- [English](#english)

---

## 它解决什么问题

现成的开源检测器基本都盯着 C2PA、SynthID、Midjourney、Stable Diffusion 这几套，
**没有一个认中国的 TC260 AIGC 隐式标识**。而国内合规生成的图恰恰都带这个标识，
它就藏在 PNG 的 `eXIf` chunk 里、EXIF UserComment(0x9286) 那段 ASCII JSON 里。

实测过的一个客户端工具（[image-provenance](https://github.com/863401402/image-provenance)）：
喂一张带完整 AIGC 标识的图，它显示「未发现 AI 来源凭证」。翻源码，
`src/markers.js` 里没有 AIGC、也没有 TC260 这两个词。

这个项目就是从那儿来的——**先把最便宜、最确定的那层做对，再谈模型**。

顺带一个结论：把一个开源检测器 clone 下来跑通，和它能给出可信答案，是两件事。仓库里有六个方案的实际结局，写在 [`references/thresholds.md`](references/thresholds.md)。

## 三层，按成本排序

| 层 | 手段 | 单张耗时 | 能定什么 |
|---|---|---|---|
| 1 元数据 | AIGC 标识 / C2PA / EXIF / 生成器指纹 | 毫秒 | 命中即定论（生成方自证） |
| 2 查重 | pHash + dHash，汉明距离 | 与第 1 层合计约 18 ms | 命中即重复 |
| 3 像素 | Community-Forensics ViT-S/384（可选） | 0.2–0.75 s | 只能当线索 |

顺序别反。倒过来做，你会花一整晚在 CPU 上，拿到一个解释不了的分数。

## 四档结论

| 结论 | 触发条件 | 怎么用 |
|---|---|---|
| `AI-SIGNED` | 命中 AIGC 国标标识或 C2PA 凭证 | 可直接采信，这是生成方自证 |
| `DUPLICATE` | 与图库中某张 pHash 距离 ≤10 | 可直接判重 |
| `AI-LIKELY` | 有生成器指纹，或像素模型 p_fake>0.6 | 只当线索，必须人工复核 |
| `NO-EVIDENCE` | 三层都没找到 | **不等于真图** |

## 安装

要求 Python 3.10 及以上（CI 覆盖 3.10 / 3.12 / 3.13）。

```bash
git clone https://github.com/Jan-My31/ai-image-forensics.git
cd ai-image-forensics

# 前两层只需要这两个，装完就能用
pip install -r requirements.txt      # Pillow>=10, numpy>=1.24
```

像素层要另外装（大概 2 GB，只在你要用 `--model` 或跑模型脚本时才需要）：

```bash
pip install torch torchvision timm safetensors
```

**不需要** OpenCV——pHash 是纯 numpy 实现的，省一个几百 MB 的依赖。

## 用法

```
python3 scripts/probe.py [图片...] [--dir 目录] [--lib 图库目录] [--model 权重] [--json]
```

| 参数 | 说明 |
|---|---|
| `图片...` | 一个或多个文件路径 |
| `--dir` | 整个目录，递归查找 jpg/png/webp/bmp/tif/heic |
| `--lib` | 已知图库目录，用来查重（不给就跳过第 2 层） |
| `--model` | commfor384 权重目录或 `.safetensors` 文件，给了才跑第 3 层 |
| `--json` | 只输出 JSON，方便接自己的流水线 |

四种典型用法：

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

`--json` 的输出结构（下面是真实输出，`metadata` 只保留了非空字段）：

```json
[
  {
    "file": "samples/real/real04.jpg",
    "verdict": "AI-LIKELY",
    "reason": "像素层判 p_fake=0.8961（单一模型，仅作线索）",
    "metadata": {
      "aigc_label": false, "c2pa": false, "xmp": true,
      "camera_exif": true, "datetime_original": true,
      "format": "MPO", "size": "3770x2827",
      "make": "Apple", "model": "iPhone 15 Pro Max", "software": "17.2"
    },
    "duplicate": { "checked": false, "reason": "未提供图库（--lib）" },
    "pixel": { "available": true, "p_fake": 0.8961, "logit": 2.154 }
  }
]
```

每层都有独立的 `checked` / `available` 字段。**跑没跑和结论是什么，是两件事**，JSON 里分得很清楚。

## 一个真实例子：元数据和模型打架时听谁的

上面那段 JSON 是真的，来自一张 iPhone 15 Pro Max 拍的照片：

| 证据 | 数值 | 指向 |
|---|---|---|
| EXIF `Make` / `Model` | `Apple` / `iPhone 15 Pro Max` | 真图 |
| `DateTimeOriginal` | 有 | 真图 |
| `Software` | `17.2`（系统相机） | 真图 |
| Community-Forensics 384 | `p_fake = 0.8961` | AI |

模型给了 0.8961，元数据三项全指向真图。同一批 10 张真实照片里，这一张被模型判成 `AI-LIKELY`。

**冲突时以元数据为准，并且把冲突本身记下来。** 一张 iPhone 原图被通用检测器判 0.8961，
这个数字不是"这张图可疑"，而是"这个模型不该用在商品图上"。

`probe.py` 的默认判定顺序就是按这个优先级写的：标识 → C2PA → 生成器指纹 → 查重 → 像素分数。

## 电商签收图：先建库，再查单

这是它最实际的使用场景——订单签收图、售后凭证、买家晒图。

**顺序不能反**：先把历史签收图和商品官图建成 hash 索引库，新图入站时先查库。
单张比对没有参照系，等于白跑。

三组比对，分别对应三种作弊方式：

1. **同一订单内**多角度图，其实是同一张裁出来的 → 骗"多角度佐证"
2. **不同订单之间**盗用同一张图 → 一个买家号循环用一张图
3. **与商品官图**完全一致 → 说明根本没有实拍

按风险分层输出，别混成一个分数：

| 分档 | 依据 | 处置 |
|---|---|---|
| 重复 | pHash 距离 ≤10 | 直接拒收，附距离数值 |
| 元数据被清空 | 无 EXIF 无标识 | 要求补原图重拍 |
| 模型倾向 AI | p_fake>0.6 且前两层无结论 | 人工复核，不进自动驳回 |

## 三个模型脚本，分工别搞错

`probe.py --model` 走的是 Community-Forensics。另外两个是「专用件」，
用错方向会得到一堆假阳性——这比没有检测更糟。

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

第一组是 7 张 2026 年的生成图，全部 p_fake 在 0.0000–0.0019 ——**通用模型对当年度新生成器基本失效**。
第二组是普通真实照片，被换脸模型判成换脸。两个方向都错，所以模型层的输出只能进「存疑」。

## 权重下载

本仓库**不分发任何权重**，全都要自己下。国内直连 huggingface.co 通常不通，先设镜像：

```bash
export HF_ENDPOINT=https://hf-mirror.com

# Community-Forensics 384（87 MB，推荐）
mkdir -p models/commfor384
curl -L -o models/commfor384/model.safetensors \
  "$HF_ENDPOINT/OwensLab/commfor-model-384/resolve/main/model.safetensors"
```

| 模型 | 来源 | 大小 | 备注 |
|---|---|---|---|
| commfor384 | HF `OwensLab/commfor-model-384` | 87 MB | 首选，384 比 224 准得多 |
| commfor224 | HF `OwensLab/commfor-model-224` | 86 MB | 只在跑得慢的机器上用 |
| RAIW | HF `wiltodelta/raiw-source-classify` | 2.03 GB | 较大，用 `aria2c -x16 -s16` |
| XAI-Deepfakes | 仓库内 `model/checkpoint/ff_attribution.ckpt` | 70 MB | 只对人脸有意义 |

> 下大文件时注意：`curl -m 120` 会在 120 秒处截断，得到一个"看起来大小对"的坏文件。
> 校验方式：`python3 -c "import zipfile;zipfile.ZipFile('xxx.npz')"`，报 `File is not a zip file` 就是没下完。

## 阈值速查

| 判据 | 阈值 | 依据 |
|---|---|---|
| pHash/dHash 判重 | ≤10 | 跨图最小距离 24，留足余量 |
| pHash 距离分级 | 0–2 同一张（仅重压缩）；3–10 同一张（裁剪/调色）；11–23 存疑；≥24 不同图 | 68 个变体实测 |
| 像素 `p_fake` | >0.6 才算线索 | 0.1–0.6 区间基本是噪声 |
| AIGC 标识 | 存在即命中 | 标准字段，不设阈值 |

## 怎么证明它是对的

```bash
python3 tests/make_fixtures.py     # 现场合成自检素材，不依赖任何第三方图片
python3 tests/selftest.py
```

```
自检 · pixelproof-image-forensics
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
所以这套自检既跑得动，也没有版权问题。CI 每次 push 都会在三个 Python 版本上各跑一遍。

**注意**：自检证明的是「管线通、判定逻辑对」，**不证明准确率**。
准确率证据在 [`references/thresholds.md`](references/thresholds.md)，那是 17 张图
（10 真实 + 7 生成，含 68 个平台化变体）的实测记录，包括已知的翻车案例。

## 性能

MacBook M1 / Python 3.13 / CPU 单线程，实测：

| 场景 | 耗时 | 折算 |
|---|---|---|
| 68 张图跑前两层 | 1.56 s | 约 18 ms/张（含 0.33 s 解释器启动） |
| 68 张 × 68 张图库互比（4624 次距离） | 2.77 s | 查重层几乎免费 |
| 10 张图三层全开（含模型加载） | 7.65 s | 加载约 5 s，之后约 0.2 s/张 |

查重层是 O(n×m) 的汉明距离，一万张图库对一万张新图约 1 亿次异或，建议上 numpy 批量算，别在 Python 里循环。

## 已知的边界（也是它不做的事）

1. **没有标识 ≠ 真图。** 加一道另存就洗掉了，微信转发、截图、剪贴板全都会洗。实测 Pillow 重存一次，AIGC 字段必丢。
2. **像素模型不能单独定罪。** 同一个模型对 DALL·E 2 的 5 张官方测试图 5/5 判出，对 7 张 2026 年新生成图 0/7（p_fake 0.0000–0.0019）。它只对训练里见过的生成器有效。
3. **假阳性会伤到真实用户。** iPhone 拍的一张纸箱照被 384 版判成 0.8961。像素层的输出只能进「存疑」。
4. **裁剪会漏查重，而且漏得很多。** 缩放到 1280/900 再压 q75/q60、二次截图，17/17 都能判出；**裁掉 7.5% 边缘后只有 4/17 判出**。这是实测的漏检率，不是估计。
5. **它不做这些**：不检测换脸视频、不做深度伪造的逐帧分析、不提供法律鉴定报告、不判断图片内容是否违规。真要对外举证，送有资质的电子数据司法鉴定机构。

## 文件结构

```
SKILL.md                  给 agent 读的使用说明（不是给人读的）
README.md                 就是你正在看的这个
scripts/probe.py          三层编排 + 四档结论（主入口）
scripts/exif_c2pa.py      AIGC 标识 / C2PA / EXIF 解析
scripts/phash.py          pHash + dHash（纯 numpy，不依赖 OpenCV）
scripts/run_commfor.py    通用生成图判别，独立可跑
scripts/run_raiw.py       厂商溯源，独立可跑
scripts/run_xai.py        换脸五分类，独立可跑
tests/make_fixtures.py    自检素材合成
tests/selftest.py         8 条断言
references/thresholds.md  所有阈值的来源与实测数字
.github/workflows/        CI：三个 Python 版本各跑一次自检
```

## 排错

**`ModuleNotFoundError: No module named 'PIL'`**
没装依赖：`pip install -r requirements.txt`。

**`找不到权重 ...`**
`--model` 指错了，或者权重没下。给的可以是目录（自动找 `model.safetensors`）也可以是文件本身。

**`File is not a zip file`（RAIW 的 npz）**
下载被截断了。2.03 GB 的文件用 `curl -m` 限时必挂，换 `aria2c -x16 -s16`，并核对大小。

**`torch.load` 报 `failed finding central directory`**
GitHub 打包的 tarball 下载不完整。`gzip -t` 验证一下，重新下。

**`missing=... unexpected=...` 一大堆**
权重和模型结构对不上。Community-Forensics 的 checkpoint 来自 `ViTClassifier` 包装类，键带 `vit.` 前缀，脚本里已经处理了；如果还报，多半是下到了另一个尺寸的权重。

**pHash 距离总是很大，判不出重复**
大概率是裁剪。见边界的第 4 条，裁剪超过 15% 就别用 pHash 下结论。

**被判 `NO-EVIDENCE`，但明明就是 AI 图**
正常。这正是它的设计：查不出就说查不出。要不要进一步查，取决于你的业务能承受多少误判。

## 作为 agent skill 使用

这个目录本身就是一份 skill（`SKILL.md` 是给 agent 读的）。装法：

```bash
# A. WorkBuddy 用户级 skills 目录
git clone https://github.com/Jan-My31/ai-image-forensics.git ~/.workbuddy/skills/pixelproof-image-forensics

# B. 某个项目的 .workbuddy/skills/ 下，团队共用
git clone https://github.com/Jan-My31/ai-image-forensics.git <项目>/.workbuddy/skills/pixelproof-image-forensics
```

不用 git 也可以：仓库页面右上角 Code → Download ZIP，解压后放进同一个路径。

装好之后，agent 看到「这张图是不是 AI 生成的」这类问题时，会自动读 `SKILL.md`
并按里面的流程调用 `probe.py`。

配套的 WorkBuddy 专家包（内嵌同一个 skill，图形界面直接用）：
[image-forensics-expert](https://github.com/Jan-My31/image-forensics-expert)。

## 上游引用

本仓库不包含任何第三方模型权重或数据集，只调用它们：

- [Community-Forensics](https://github.com/JeongsooP/Community-Forensics)（CVPR 2025，ViT-S 224/384）
- [image-provenance](https://github.com/863401402/image-provenance)（反面教材，见上）
- [XAI-Deepfakes](https://github.com/IDT-ITI/XAI-Deepfakes)（ICMR 2024 workshop，EfficientNetV2-B0 五分类）
- [raiw-source-classify](https://huggingface.co/wiltodelta/raiw-source-classify)（10 厂商归属 + abstain）
- FSD（CVPR 2025，CC BY-NC-SA 4.0，非商用）、UnivFD（CVPR 2023）、[Organika/sdxl-detector](https://huggingface.co/Organika/sdxl-detector)、LAID（PST 2025）
- TC260《人工智能生成合成内容标识方法》AIGC 隐式标识字段
- C2PA / JUMBF 内容凭证

## 许可

MIT。上游模型各自的许可请单独确认（FSD 是非商用）。

## English

**What it is.** A three-layer image authenticity check for Chinese-market content: TC260 AIGC
provenance labels and EXIF/C2PA metadata first (milliseconds), perceptual-hash duplicate search
second (~18 ms), and an optional ViT-S/384 pixel classifier last (0.2–0.75 s). One command,
four verdicts, no uploads, no GPU.

**Why it exists.** Every mainstream open-source detector looks for C2PA, SynthID, Midjourney or
Stable Diffusion fingerprints. None of them recognise China's TC260 `AIGC` implicit label, which
is exactly what compliant Chinese generators embed — as an ASCII JSON blob in the PNG `eXIf`
chunk, EXIF `UserComment` (0x9286). A popular client-side tool we tested reports "no AI
provenance found" on an image carrying a complete label.

**Honest limits.** No label does not mean real — any re-save strips it. The pixel classifier
scores 5/5 on DALL·E 2 reference images and 0/7 on 2026-era generators. Cropping 7.5% off the
edge drops duplicate detection from 17/17 to 4/17. `NO-EVIDENCE` is the most common output by
design, and it never means "authentic".

```bash
pip install -r requirements.txt
python3 scripts/probe.py --dir ./inbox --lib ./known-library --json
```
