# 阈值与实测依据

本文件记录所有阈值的来源，方便复核。测试环境：MacBook Pro M1 / 16GB、
macOS、Python 3.13.12、torch 2.12.1 CPU 8 threads。

## 样本

- 真实图 10 张（Wikimedia 原图，其中 3 张带完整相机 EXIF：iPhone 15 Pro Max、NIKON Z fc、FUJIFILM X-M5）
- 生成图 7 张（1024×1536 PNG，均带 TC260 AIGC 标识）
- 平台化变体 68 张：长边 1280/q75、900/q60、裁边 7.5%、1170 PNG→q80

## pHash 距离分布

| 变换 | pHash 距离 |
|---|---|
| 1280 + q75 | 0~2 |
| 900 + q60 | 0~2 |
| 截图式（1170 + PNG 中转 + q80） | 0~2 |
| 裁掉 7.5% 边缘 | 8~24 |
| 不同图之间（最近的一对） | 24 |

结论：阈值 10 —— 压缩类变换全部命中，不同图不误判，但裁剪会漏一部分。

## Community-Forensics 实测

权重：`OwensLab/commfor-model-384`（87MB）/ `-224`（86.7MB），HF 镜像可下。
预处理（官方 `dataloader.get_transform(mode='test')`）：
384 → Resize(440) → CenterCrop(384) → ToTensor[0,1] → ImageNet Normalize。
输入 224 时是 Resize(256) → CenterCrop(224)。

| 测试集 | 384 版 | 224 版 |
|---|---|---|
| 官方自带 DALL·E 2 图 5 张 | 5/5 判出（0.786~0.999） | 3/5（0.837~0.942） |
| 本次 7 张新生成图 | 0/7（0.0000~0.0019） | 0/7（0.0000~0.128） |
| 10 张真实照片 | 9/10（iPhone 纸箱照误判 0.896） | 9/10（同一张 0.628） |

单张耗时（CPU，8 线程）：384 版 0.19~0.75 s，224 版 0.02~0.10 s。

要点：**同一个模型，对训练分布内的老生成器全中，对新生成器全漏**。所以像素层
只能当"命中即证据"，不能当"未命中即清白"。

## RAIW multi-provider source classifier

- 仓库 `wiltodelta/raiw-source-classify`（不是流传清单里的 `raiw-models`）。
- 装法：`pip install "remove-ai-watermarks[source-classify]"`，权重
  `multi-provider-source-v3.npz` 2.03 GB，`RAIW_SOURCE_CLASSIFY_WEIGHTS` 指过去即可离线。
- 它做 10 个厂商归属 + unknown，拿不准时 **abstain**（`reason='abstained'`）。
- 本机实测：17 张图（7 生成 + 10 真实）**全部 abstain**，置信度 0.0007~0.2185。
  零误报，也零召回。论文自报 binary ROC-AUC 0.9577，在未见过的生成器上不成立。
- 下载注意：hf-mirror 单线程 curl 约 78 KB/s，2 GB 要六小时；用
  `aria2c -x 16 -s 16` 约 4 MB/s，四十分钟下完，SHA256 与仓库一致。

## 三个模型的交叉验证（同一批 7 张 2026 年生成图）

| 模型 | 结论 |
|---|---|
| image-provenance（网页） | 未发现 AI 来源凭证 |
| raiw-source-classify | 全部 abstain |
| Community-Forensics 384 | 全部判真，p_fake 0.0000~0.0019 |

三个独立实现给出同一个错误答案。同期元数据层 7/7 命中 AIGC 标识。
这就是为什么第一层必须排在第一位。


## FSD（Forensic Self-Descriptions, CVPR 2025）

- 只看真图训练，零样本打分；输出 z-score，越负越像 AI。
- 默认阈值 -2.0；本机实测把阈值放到 **-5** 才干净：8/8 正确（生成图 -6.28~-9.27，真图 -4.24~-4.39 被 -5 排除）。
- 速度：1600px 输入 44~60 s/张（float64 残差求解），4000px 原图 122~150 s。**不适合在线**。
- 压缩后归零：1280+q75 之后生成图 z 值掉到 -0.35~-0.56，全漏。
- 许可 CC BY-NC-SA 4.0，**不可商用**。

## 元数据层

- 17 个文件里 7 个带 AIGC 标识（正好是 7 张生成图），命中率 7/7。
- C2PA/JUMBF：0/17。
- 标识位置：PNG `eXIf` chunk → EXIF UserComment(0x9286)，ASCII JSON。
- 破坏测试：Pillow 另存 JPG(q92) 一次 → 字段消失；另存 PNG 一次 → 字段也消失。
