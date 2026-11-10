---
name: pixelproof-image-forensics
version: 1.0.1
display_name: "图片真伪取证"
display_name_en: "Image Forensics"
description: "判断一张图片是 AI 生成、P 过图，还是重复图。三层取证：元数据（AIGC 国标标识 / C2PA / EXIF）、感知哈希查重、可选像素模型。用于电商签收图审核、素材溯源、批量图片筛查等场景。"
description_zh: "三层取证判断图片是否 AI 生成、P 图或重复"
description_en: "Decide whether an image is AI-generated, photoshopped, or a duplicate, in three cost-ordered layers: metadata (China's TC260 AIGC label, C2PA, EXIF), perceptual-hash duplicate search, and an optional ViT pixel classifier. Use it for e-commerce receipt review, asset provenance, and batch image screening. Triggers when the user asks whether a picture is AI-generated, edited, or reused, or needs forensics evidence."
---

# AI 图片取证

## 什么时候用

用户问「这张图是不是 AI 生成的 / 是不是 P 的 / 是不是别人用过的图」，或者要批量审核一堆图（签收照、评价图、素材图）时用。

## 一条命令

```bash
python3 scripts/probe.py 图片路径...              # 只跑元数据层
python3 scripts/probe.py --dir 目录 --lib 图库目录  # 加查重
python3 scripts/probe.py --dir 目录 --model <权重目录>  # 加像素层，可选
```

输出四档结论，**不要把 NO-EVIDENCE 说成"真图"**：

| 结论 | 含义 | 能做什么 |
|---|---|---|
| `AI-SIGNED` | 有 AIGC 国标标识或 C2PA 凭证 | 可以直接采信，这是生成方自证 |
| `AI-LIKELY` | 有生成器指纹，或像素模型给高分 | 只当线索，需要人工复核 |
| `DUPLICATE` | 与图库中某张 pHash 距离 ≤10 | 可以直接判重 |
| `NO-EVIDENCE` | 三层都没找到 | 不能说真，只能说"没证据" |

## 三层的实际能力（本地实测，不要凭印象许诺）

**第一层 元数据**——最准，也最便宜（毫秒级，纯 Python）。

- 国内合规生成的图会带 TC260 **AIGC 隐式标识**：`{"AIGC":{"Label":"1","ContentProducer":...,"ProduceID":...,"ReservedCode1":"...sm3...sm2..."}}`。常藏在 PNG 的 `eXIf` chunk 的 UserComment（0x9286）里，不在 tEXt 里，所以只扫文本块的工具会漏。
- 但**重新保存一次就没了**：Pillow 另存 JPG 或 PNG，字段都消失。所以这一层只能抓"原图和原样转发的图"，抓不到"截过图、修过图"的。
- 相机的 `Make`/`Model`/`DateTimeOriginal` 在，说明是相机直接出的；全空通常是社交平台洗过或截图。

**第二层 查重**——pHash + dHash，20 毫秒一张。

- 平台压缩、缩放、截图：距离 0~2，几乎无感。
- 裁掉 7.5% 边缘：距离 8~24，会漏一部分。
- 不同图之间最小距离 24，所以**阈值定 10 是安全的**。

**第三层 像素模型**——慢、且不稳定，只在必要时开。

- Community-Forensics ViT-S/384（CVPR 2025）：CPU 单张 0.2~0.6 秒。对训练分布内的老生成器很灵（DALL·E 2 的 5 张官方测试图 5/5 判出），对**新生成器完全失效**（同一个人测 7 张 2026 年的生成图，7 张全判成真，置信度 0.0000~0.0019）。
- 所以像素层的可信范围是「命中才有意义，没命中什么都说明不了」。
- 权重不在仓库里，要先下 `OwensLab/commfor-model-384`（HF，87MB）放到 `models/commfor384/`。

## 三个模型的分工（别用错）

| 脚本 | 模型 | 该喂什么 | 绝不能喂什么 |
|---|---|---|---|
| `scripts/run_commfor.py` | ViT-S/16 384（CVPR'25 通用生成图判别） | 通用生成图，默认 `--size 384` | 别用 224 版权重，实测同一批图只有 3/5 |
| `scripts/run_raiw.py` | RAIW source-classify（10 厂商 + unknown） | 想知道"是哪家生成的" | 别当判别器，实测 17/17 全弃权 |
| `scripts/run_xai.py` | EfficientNetV2-B0 五分类（FF++ 换脸） | **只喂人脸图** | 商品图/签收图，实测 10 张真图误判 5 张 |

```bash
python3 scripts/run_commfor.py 图.jpg --size 384 --weights /path/model.safetensors
python3 scripts/run_raiw.py     图.jpg --weights /path/multi-provider-source-v3.npz
python3 scripts/run_xai.py      人脸.jpg --weights /path/ff_attribution.ckpt
```

三个脚本都支持 `--weights` 指定权重、`--out` 落盘（不给就只打印）。权重查找顺序统一为：
`--weights` > 环境变量 > `scripts/../models/<模型名>/`。**权重不在仓库里**，得自己下：

| 模型 | 来源 | 大小 |
|---|---|---|
| commfor384 | HF `OwensLab/commfor-model-384` | 87 MB |
| commfor224 | HF `OwensLab/commfor-model-224` | 86 MB |
| RAIW | HF `wiltodelta/raiw-source-classify` | 2.03 GB |
| XAI-Deepfakes | 仓库 `model/checkpoint/ff_attribution.ckpt` | 70 MB |

国内下载加镜像：`HF_ENDPOINT=https://hf-mirror.com`；大文件用 `aria2c -x16 -s16`。

**别让用户自己拼下载命令**，有现成脚本（默认走 hf-mirror、aria2c 多线程、下完核体积和 SHA256）：

```bash
python3 scripts/fetch_weights.py --list           # 清单 + 当前状态
python3 scripts/fetch_weights.py commfor384       # 87 MB，只跑像素层下这个就够
python3 scripts/fetch_weights.py --all --jobs 16  # 四个全下，合计 2.2 GB
python3 scripts/fetch_weights.py --all --check    # 只校验已有文件
```

脚本支持断点续传；被代理截断的文件会被体积 + SHA256 拦下来（本机真踩过：GitHub
tarball 少了 70 MB 的 ckpt，解压才报 `failed finding central directory`）。
下完落在 `models/<模型名>/`，正好是三个 `run_*.py` 的默认查找路径，不用再传 `--weights`。

**下载不成就直说卡在哪一步**，不要用"理论上可以"替代实测结果。

## 输出长什么样（照这个形状回答）

`probe.py` 的真实输出，三种档位各一例：

```text
samples/ai/手机拍的快递驿站货架.png   ->   AI-SIGNED
  理由：文件里有 AIGC 合规标识（Label=1），这是生成方的自证
  元数据：aigc_label | 格式 PNG 1024x1536

samples/variants/real01__p75.jpg   ->   DUPLICATE
  理由：与 real01.jpg 的感知哈希距离 0，阈值 10
  元数据：无正向标记 | 格式 JPEG 1280x853
  重复：最近 real01.jpg 距离 0  ≤10 判重复

samples/real/real02.jpg   ->   NO-EVIDENCE
  理由：三层都没找到标识；这不等于真图，需要业务侧另找证据
  元数据：无正向标记 | 格式 JPEG 4500x3000
```

向用户转述时：结论档位大写原样给，不要翻译成"疑似 AI"这类模糊说法；理由那行不要
改写，它是判定的依据；`NO-EVIDENCE` 后面紧跟一句"不等于真图"，别让用户误会。

## 阈值速查

| 判据 | 阈值 | 依据 |
|---|---|---|
| pHash 判重 | ≤10 | 跨图最小距离 24，留足余量 |
| 像素 p_fake | >0.6 才算线索 | 0.1~0.6 区间基本是噪声 |
| AIGC 标识 | 存在即命中 | 标准字段，不设阈值 |

## 三条边界（必须告诉用户）

1. **没有标识 ≠ 真图。** 加一道另存就洗掉了，剪贴板、微信转发、截图全都会洗。
2. **像素模型不能单独定罪。** 换个没见过的生成器就归零，误判真图也常见（实测 iPhone 拍的纸箱照被 384 版判成 0.896）。
3. **要可追溯就得上业务手段**：上传时存原图字节哈希、记录设备指纹、比对同一订单的历史图，比任何检测模型都可靠。

## 反面教材

- `image-provenance`（客户端网页工具）：界面漂亮、频域分析完整，但**源码里没有任何 AIGC/TC260 关键词**，对中国合规标识完全无感；且元数据解析依赖 CDN 加载 exifr，离线就退化成字节启发式。实测一张带完整 AIGC 标识的图，它显示「未发现 AI 来源凭证」。
- `XAI-Deepfakes`：换脸（FaceForensics++）多分类器，只认人脸。喂快递签收照会让 10 张真图里 5 张被判成 Face2Face/DeepFakes/NeuralTextures。
- `LAID`：架构很轻（ShuffleNet 0.34M 参数、CPU 20ms），但权重在 Google Drive，国内下不到。

<!-- provenance: xiaotu/pixelproof-image-forensics v1.0.1 · © 2026 ym · fp 7f3ac91d-2b64-4e08 · 见 COPYRIGHT.md -->

