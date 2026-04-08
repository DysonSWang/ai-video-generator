# AI口播视频生成平台

**日期**: 2026-04-08
**状态**: 技术验证完成，口型同步核心问题待解决

---

## 项目概述

复制类似D-ID的AI口播视频生成工具：
- 输入文案 → 克隆音色 → 生成数字人口播视频 → 一键发布

### 目标用户
- 个人创业者
- 中小实体商家

### 商业模式
- 按生成量收费
- 免费试用+付费解锁

---

## 目录结构

```
ai-video-generator/
├── README.md              # 本文件
├── docs/                  # 技术文档
│   ├── TECH_VALIDATION_PLAN.md
│   └── TECH_VALIDATION_REPORT.md
├── scripts/               # 脚本
│   ├── test_voice_clone.py      # 语音克隆测试
│   ├── test_wav2lip_load.py    # Wav2Lip测试
│   ├── run_av1_gpu.py          # MuseTalk推理(150帧)
│   ├── run_av1_fp32_v2.py      # MuseTalk推理(fp32)
│   └── run_av1_full.py         # MuseTalk推理(550帧完整版)
├── assets/               # 源素材
│   ├── user_voice.wav          # 用户参考音频 (317KB)
│   ├── sun.mp4                 # Avatar源视频-完整 (2.2MB)
│   ├── sun_short.mp4           # Avatar源视频-短版 (565KB)
│   ├── cloned_voice_test.mp3   # 克隆音色测试音频
│   └── VOICE_CLONE_README.md  # 语音克隆经验
├── results/              # 输出结果
│   ├── av1_full_final.mp4      # MuseTalk完整版 (蓝色伪影)
│   ├── final_wav2lip_gan.mp4  # Wav2Lip版 (模糊)
│   └── cloned_voice_test.mp3   # 克隆语音测试
└── notes/                # 经验笔记 (待创建)
```

---

## 技术Pipeline

```
竞品视频/文案
    ↓
Whisper音频转文字
    ↓
千问GPT改写
    ↓
硅基流动TTS + 音色克隆
    ↓
Wav2Lip / MuseTalk 口型同步
    ↓
FFmpeg视频合成
    ↓
发布到抖音
```

---

## 组件验证状态

| 组件 | 状态 | 备注 |
|------|------|------|
| Whisper 音频转文字 | ✅ | 本地GPU |
| 千问GPT改写 | ✅ | 阿里云百炼API |
| 硅基流动TTS | ✅ | IndexTTS-2 |
| 语音克隆 | ✅ | 音色克隆成功 |
| Wav2Lip | ⚠️ | 面部模糊 |
| MuseTalk | ⚠️ | 蓝色伪影问题 |

---

## 核心问题

### MuseTalk 蓝色伪影

**现象**: UNet生成的面部有蓝色/青色伪影

**根因**: UNet在潜在空间生成时产生颜色通道偏差
- 已排除：精度(fp32/fp16)、avatar、blending问题
- 代码已支持v1.5，但GAN模型未公开下载

**验证结果**:
- fp32 vs fp16 → 都有伪影
- musetalk_avatar_v2 vs musetalk_avatar1 → 都有伪影
- 550帧全长测试 → 仍有伪影
- musetalk_avatar1 (官方avatar) → 同样有伪影

**MuseTalk版本现状**:
- 代码版本: v1.5 (2025.7.26更新，支持GAN训练代码)
- 模型版本: 基础DDPM UNet (3.4GB)，无GAN损失
- GAN模型: 商业版提供，开源版本未发布

**解决方案**:
1. MuseTalk V1.5 GAN模型 (商业版) - 根本解决
2. bbox_shift调优 - 需重新预处理avatar，成本高
3. Wav2Lip备选 - 稳定但面部模糊

### Wav2Lip 模糊

**现象**: 生成的视频面部模糊，"都花了"

**方案**: 
- 使用GAN版本 (wav2lip_gan.pth)
- 提供高清Avatar源视频
- 调整分辨率参数

---

## API配置

| 服务 | Key | 用途 |
|------|-----|------|
| 阿里云百炼 | `sk-d4d0824db5e847de8ddbef4cda0b4e34` | 千问改写 |
| 硅基流动 | `sk-cnfczetwmgwynbwezbadzhvceilpivocpaltgwtodnukpwpd` | TTS+音色克隆 |

---

## 服务器

### 当前GPU服务器 (即将弃用)
- 地址: `connect.bjb2.seetacloud.com:38840`
- Python: `/root/miniconda3/bin/python`
- 项目: `/root/livetalking/`
- 状态: MuseTalk已安装但存在蓝色伪影问题

### 新服务器(待配置)
1. 安装MuseTalk V1.5 (代码已支持)
2. 获取MuseTalk GAN模型 (商业版渠道)
3. 准备好高清正脸源视频
4. 微调bbox_shift参数
5. 或探索SadTalker照片驱动方案

---

## 下一步

1. [ ] 新服务器部署
2. [ ] 获取MuseTalk GAN模型或商业版
3. [ ] 准备好高清Avatar源视频 (正脸、清晰口型)
4. [ ] 微调bbox_shift到最佳值
5. [ ] 测试SadTalker照片驱动方案
6. [ ] 完整推理生成最终视频

---

## 成本预估

| 组件 | 费用 |
|------|------|
| Whisper | ¥0 (本地) |
| 千问改写 | ¥0.02/千tokens |
| TTS配音 | ¥0.3/千次 |
| 音色克隆 | ¥0.3/千次 |
| 口型同步 | ¥0 (本地GPU) |
| **单条成本** | **≈¥0.05** |

---

## 服务器Avatar预处理流程

MuseTalk需要专用avatar格式，不是普通视频：

```
源视频 (mp4)
    ↓ ffmpeg提取帧
帧序列 (full_imgs/*.png)
    ↓ FaceAlignment人脸检测
坐标文件 (coords.pkl)
    ↓ VAE编码
潜向量文件 (latents.pt, 8通道)
    ↓ FaceParsing面部解析
遮罩文件 (mask/*.png + mask_coords.pkl)
```

**预处理产物**:
- `full_imgs/` - 原始帧
- `coords.pkl` - 人脸边界框
- `latents.pt` - VAE编码潜向量 (torch.Size([1, 8, 32, 32]))
- `mask/` - 面部解析遮罩
- `mask_coords.pkl` - 遮罩坐标
- `avator_info.json` - avatar配置

**关键参数**:
- `bbox_shift` - 控制面部区域上边界，正值下移/负值上移
- 参考范围: -9 ~ 9 (从日志获取)

---

## 关键文件路径

### 服务器端
```
/root/livetalking/                    # 项目根目录
/root/livetalking/models/             # 模型文件
/root/livetalking/models/musetalkV15/unet.pth  # UNet模型(3.4GB)
/root/livetalking/models/sd-vae/     # VAE模型
/root/livetalking/data/avatars/       # Avatar数据
/root/livetalking/user_voice.wav       # 用户音频
/root/miniconda3/bin/python            # Python解释器
```

### 本地项目
```
/home/admin/ai-video-generator/
├── README.md                    # 项目总览
├── docs/                       # 技术文档
├── scripts/                    # 推理脚本
├── assets/                     # 源素材
└── results/                    # 输出结果
```
