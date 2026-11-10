# 验小图 PixelProof（image-forensics）

判断一张图是 **AI 生成**、**P 过**，还是**重复图**的全流程鉴定顾问。三层取证，从毫秒级的元数据查到可选像素模型，最后只给四档结论——包括最常见的「查不出来」。

面向电商签收图核验、售后凭证审核、平台申诉举证。

## 类型

Agent 型（单个 AI 专家）

## 功能

1. **三层取证判定**：元数据（AIGC 国标标识 / C2PA / EXIF）→ 感知哈希查重 → 可选像素模型。按成本递增，能早停就早停。
2. **AIGC 隐式标识核验**：读 PNG `eXIf` chunk / JPEG EXIF UserComment(0x9286) 里的 TC260 ASCII JSON，取 `Label`、`ContentProducer`、`ProduceID` 与 SM3/SM2 摘要。国内合规生成的图带这个，比任何模型都硬。
3. **图库查重**：pHash + dHash，容忍缩放、重压缩、二次截图；给出汉明距离和阈值依据。
4. **像素模型分诊**：Community-Forensics ViT-S/384（通用生成图）、RAIW source-classify（厂商溯源）、XAI-Deepfakes（换脸五分类）——三个模型各管一段，并明确各自不能喂什么。
5. **电商批量核验**：先建库再查单，按「重复图 / 元数据被清空 / 模型倾向 AI」三档分层出结果，对应到补拍、人工复核、拒收的处置动作。
6. **举证材料整理**：把技术结论翻译成平台申诉能用的表述，附证据条目与免责边界。

### 四档结论

| 结论 | 触发条件 | 能做什么 |
|---|---|---|
| `AI-SIGNED` | 命中 AIGC 国标标识或 C2PA 凭证 | 可直接举证 |
| `DUPLICATE` | 与图库 pHash 距离 ≤10 | 可直接判重 |
| `AI-LIKELY` | 模型高分或生成器指纹 | 只当线索 |
| `NO-EVIDENCE` | 三层都没找到 | **不等于真图** |

> `NO-EVIDENCE` 是最常见的输出。说"查不出来"是专业，硬给一个结论是不专业。

### 附带技能：ai-image-forensics

可直接运行的脚本，全部本地跑，不上传图片：

| 文件 | 用途 |
|---|---|
| `scripts/probe.py` | 三层编排，支持单文件 / 目录 / 图库比对 / JSON 输出 |
| `scripts/exif_c2pa.py` | AIGC 标识、C2PA、EXIF、JPEG 质量估计 |
| `scripts/phash.py` | pHash + dHash，纯 numpy，不依赖 OpenCV |
| `scripts/run_commfor.py` | 通用生成图判别，默认 384 版 |
| `scripts/run_raiw.py` | 厂商溯源，10 类 + unknown |
| `scripts/run_xai.py` | 换脸五分类，**只喂人脸** |
| `tests/selftest.py` | 8 条断言，现场合成素材，不依赖第三方图片 |
| `references/thresholds.md` | 所有阈值的来源与 17 张图的实测数字 |

前两层只要 `Pillow` + `numpy`；像素层需要 `torch` + `timm`，权重不随包分发。

## 使用示例

- 帮我看看这张图是 AI 生成还是 P 的
- 这批订单签收图里有没有重复上传或者盗用别人图的
- 我要拿这张图去平台申诉，帮我把证据链和话术整理出来

## 三条边界（专家会主动说明）

1. **没有标识 ≠ 真图。** Pillow 重存一次、微信转发一次、截个图，AIGC 字段就没了。
2. **像素模型不能单独定罪。** 实测对 DALL·E 2 官方测试图 5/5 命中，对 7 张 2026 年新生成图 0/7（p_fake 0.0000–0.0019）；iPhone 拍的纸箱照反而被判 0.896。
3. **要可追溯就得上业务手段。** 上传时存原图字节哈希、记录设备指纹、比对同一订单的历史图，比任何检测模型都可靠。

## 头像

`avatars/expert.png`，512×512，程序化生成（`gen_avatar.py`，4 倍超采样）。

## 安装

```bash
cp -r image-forensics ~/.workbuddy/plugins/marketplaces/my-experts/plugins/
python3 scripts/register_expert.py ~/.workbuddy/plugins/marketplaces/my-experts/plugins/image-forensics
```

## 打包分享

```bash
zip -r image-forensics.zip image-forensics/
```

## 引用

Community-Forensics (CVPR 2025) · RAIW source-classify · XAI-Deepfakes (ICMR 2024 workshop) · LAID (PST 2025) · FSD / UnivFD · TC260《人工智能生成合成内容标识方法》· C2PA / JUMBF
