# AI视频生成平台 - 技术验证计划

## 验证目标

验证以下开源方案在云GPU上的可行性：
1. **Wav2Lip** - 唇形同步
2. **SadTalker** - 照片驱动头像
3. **Coqui XTTS** - 声音克隆
4. **EdgeTTS** - 免费TTS
5. **千问Qwen** - 文案改写（DashScope API）
6. **Whisper** - 音频转文字

## 验证标准

| 指标 | 合格 | 优秀 |
|------|------|------|
| 处理速度 | <2分钟/条 | <1分钟/条 |
| 视频质量 | 唇形基本同步 | 自然无违和感 |
| 声音克隆 | 能听懂说的是什么 | 和原声相似度高 |
| API响应 | <5秒 | <2秒 |

---

## 一、云GPU准备

### 推荐云GPU服务商

| 服务商 | GPU型号 | 价格 | 特点 |
|--------|---------|------|------|
| **autoDL** | 4090/A100 | ¥1-3/小时 | 国内便宜，按量付费 |
| **阿里云GPU** | V100/A100 | ¥10-20/小时 | 稳定，但贵 |
| **腾讯云GPU** | V100/P40 | ¥8-15/小时 | 国内可选 |
| **Lambda Lab** | A100/H100 | $0.50-1/小时 | 海外，信用卡即可 |
| **RunPod** | 4090/A100 | $0.2-0.5/小时 | 海外，Serverless |

### 推荐配置
- **最低**：RTX 4090 24GB 或 A100 40GB
- **推荐**：A100 40GB（多卡并行）
- **系统**：Ubuntu 22.04
- **Python**：3.10+

### 租用步骤（autoDL为例）

1. 注册 autoDL：https://www.autodl.com/
2. 选择镜像：`PyTorch 2.0 + CUDA 11.8`
3. 租用GPU（4090约¥1.5/小时）
4. SSH连接后开始测试

---

## 二、环境准备脚本

```bash
# 连接云GPU后执行
sudo apt update && sudo apt upgrade -y

# 安装基础依赖
sudo apt install -y git wget ffmpeg libsm6 libxext6 python3.10-venv

# 创建conda环境（推荐）
conda create -n video-ai python=3.10
conda activate video-ai

# 安装PyTorch（CUDA 11.8）
pip install torch==2.0.1 torchvision==0.15.2 --index-url https://download.pytorch.org/whl/cu118

# 安装基础库
pip install numpy opencv-python pillow scipy
```

---

## 三、Wav2Lip 验证

### 3.1 安装

```bash
cd /home/admin
git clone https://github.com/Rudrabha/Wav2Lip.git
cd Wav2Lip

# 下载预训练模型
gdown https://drive.google.com/uc?id=1_zE1x0FtwE0vDZ9jNKTX3V74mEHVsCBB
mv wav2lip_gan.pth checkpoints/

gdown https://drive.google.com/uc?id=1c0i0oaPdMUxG2T3zMQq6SV9K0X0x2R0e
mv face_detection.pth checkpoints/
```

### 3.2 测试命令

```bash
# 准备测试素材（需要一个人脸视频+音频）
# 方法1: 下载测试视频
wget https://test-videos.com/samplevideo.mp4 -O test_video.mp4

# 方法2: 用ffmpeg从油管提取（需要yt-dlp）
pip install yt-dlp
yt-dlp -f 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]' -o test_video.mp4 "VIDEO_URL"

# 准备音频（用EdgeTTS生成测试音频，后面有）
python -m edge_tts -t "这是一段测试语音，用于验证唇形同步效果" -vo "zh-CN-XiaoxiaoNeural" -o test_audio.mp3

# 运行Wav2Lip
python inference.py \
  --checkpoint_path checkpoints/wav2lip_gan.pth \
  --face test_video.mp4 \
  --audio test_audio.mp3 \
  --pads 0 0 0 0 \
  --resize_factor 2 \
  --outfile output.mp4
```

### 3.3 验证检查点

- [ ] 安装成功，无报错
- [ ] 模型下载完成
- [ ] 运行完成，生成output.mp4
- [ ] 视频长度与音频一致
- [ ] 唇形基本同步
- [ ] 处理时间记录

### 3.4 质量评估

```bash
# 提取帧对比
ffmpeg -i test_video.mp4 -vf fps=1/5 frames/original_%03d.jpg
ffmpeg -i output.mp4 -vf fps=1/5 frames/output_%03d.jpg

# 记录评估结果
echo "处理时间: $(tail -1 /tmp/wav2lip_time.log)"
echo "唇形同步: 1-5分评分"
echo "总体质量: 1-5分评分"
```

---

## 四、SadTalker 验证

### 4.1 安装

```bash
cd /home/admin
git clone https://github.com/OpenTalker/SadTalker.git
cd SadTalker

# 创建环境
conda create -n sadtalker python=3.10
conda activate sadtalker

# 安装依赖
pip install -r requirements.txt

# 下载预训练模型
bash scripts/download_models.sh
```

### 4.2 测试命令

```bash
# 准备测试照片（正脸照效果最好）
# 需要：单人物、正脸、清晰五官
wget https://raw.githubusercontent.com/OpenTalker/SadTalker/main/examples/driven_audio/Ben_Shakespeare.jpg -O test_photo.jpg

# 准备音频
python -m edge_tts -t "你好，这是一段测试语音" -vo "zh-CN-XiaoxiaoNeural" -o test_audio.mp3

# 运行SadTalker
python inference.py \
  --driven_audio test_audio.mp3 \
  --source_image test_photo.jpg \
  --result_dir ./results \
  --enhancer gfpgan \
  --still \
  --preprocess crop \
  --expression_scale 1.0
```

### 4.3 验证检查点

- [ ] 安装成功，无报错
- [ ] 预训练模型下载完成
- [ ] 生成视频成功
- [ ] 头部有自然动作
- [ ] 面部表情自然
- [ ] 处理时间记录

### 4.4 质量对比

对比不同 `--expression_scale` 值的效果：
- 0.8：动作较小
- 1.0：标准
- 1.2：动作夸张

---

## 五、Coqui XTTS 声音克隆验证

### 5.1 安装

```bash
pip install xtts
# 或从源码安装
git clone https://github.com/coqui-ai/TTS
cd TTS
pip install -e .
```

### 5.2 测试命令

```bash
# 准备训练音频（用户需要录10-20秒）
# 这里用测试音频代替
wget https://github.com/coqui-ai/TTS/raw/dev/tests/data/ljspeech/wavs/LJ001-0001.wav -O ref_audio.wav

# 克隆音色
python -c "
from TTS.api import TTS
tts = TTS('xtts')
tts.tts_to_file(
    text='这是一段克隆声音的测试文本，测试克隆效果是否逼真。',
    speaker_wav='ref_audio.wav',
    language='zh',
    file_path='cloned_voice.wav'
)
"
```

### 5.3 验证检查点

- [ ] 安装成功
- [ ] 模型下载完成（约400MB）
- [ ] 生成音频成功
- [ ] 能听出克隆了原声特征
- [ ] 中文发音基本正确
- [ ] 处理时间记录

### 5.4 质量评估标准

| 评分 | 描述 |
|------|------|
| 1 | 完全听不懂 |
| 2 | 能听懂，但有明显机械感 |
| 3 | 基本自然，能接受 |
| 4 | 比较像真人 |
| 5 | 和原声几乎一样 |

---

## 六、EdgeTTS 验证（中文）

### 6.1 安装

```bash
pip install edge-tts
```

### 6.2 测试命令

```bash
# 列出所有中文声音
python -m edge_tts --list-voices | grep "zh-"

# 测试不同声音
python -m edge_tts \
  -t "你好，这是一段测试语音，测试EdgeTTS的中文效果。" \
  -vo "zh-CN-XiaoxiaoNeural" \
  -o output_xiaoxiao.mp3

python -m edge_tts \
  -t "你好，这是一段测试语音，测试EdgeTTS的中文效果。" \
  -vo "zh-CN-YunxiNeural" \
  -o output_yunxi.mp3

python -m edge_tts \
  -t "你好，这是一段测试语音，测试EdgeTTS的中文效果。" \
  -vo "zh-CN-YunyangNeural" \
  -o output_yunyang.mp3
```

### 6.3 验证检查点

- [ ] 中文语音生成成功
- [ ] XiaoXiao（女声）效果
- [ ] YunXi（男声）效果
- [ ] 语速可调节
- [ ] 停顿处理自然

---

## 七、千问Qwen (DashScope API) 验证

### 7.1 申请API

1. 开通阿里云百炼：https://bailian.console.aliyun.com/
2. 申请开通 Qwen API
3. 获取 API Key

### 7.2 安装SDK

```bash
pip install dashscope
```

### 7.3 测试命令

```python
import os
from dashscope import Generation
from dashscope.api_entities.dashscope_response import DashScopeResponse

os.environ['DASHSCOPE_API_KEY'] = 'your-api-key'

def test_qwen_rewrite(original_text):
    """测试千问改写功能"""
    prompt = f"""你是一个专业的短视频文案改写专家。
把下面的竞品视频文案改写成原创版本，保持爆款结构，但完全重写表达方式。

原文：
{original_text}

要求：
1. 保持同样的主题和信息
2. 换一种表达方式，避免重复
3. 语言口语化，适合短视频
4. 长度控制在原文的80%-120%

改写后的文案："""

    response = Generation.call(
        model='qwen-max',
        prompt=prompt,
        max_tokens=500,
        temperature=0.7
    )

    if response.status_code == 200:
        return response.output['text']
    else:
        return f"Error: {response.message}"

# 测试
original = "今天给大家分享一个装修行业的大坑，很多业主都不知道。装修的时候，工人让你买这5种材料，一定要亲自去建材市场，不要让他们包料，否则你可能要多花好几万冤枉钱。"

rewritten = test_qwen_rewrite(original)
print("原文:", original)
print("改写:", rewritten)
```

### 7.4 验证检查点

- [ ] API调用成功
- [ ] 改写质量可接受
- [ ] 响应时间 <5秒
- [ ] 费用符合预期

### 7.5 费用预估

| 模型 | 价格 | 备注 |
|------|------|------|
| qwen-turbo | ¥0.002/千tokens | 便宜，快速 |
| qwen-plus | ¥0.02/千tokens | 中等 |
| qwen-max | ¥0.2/千tokens | 最强 |

**预估**：一条视频文案约500tokens，qwen-plus费用 ¥0.01/条

---

## 八、Whisper 验证

### 8.1 安装

```bash
pip install openai-whisper
```

### 8.2 测试命令

```bash
# 下载测试视频的音频
ffmpeg -i test_video.mp4 -vn -acodec pcm_s16le -ar 16000 -ac 1 audio.wav

# 测试不同模型
time whisper audio.wav --model tiny --language zh --fp16 False
time whisper audio.wav --model base --language zh --fp16 False
time whisper audio.wav --model medium --language zh --fp16 False
```

### 8.3 验证检查点

- [ ] tiny模型：速度快，但准确率一般
- [ ] base模型：速度和质量平衡
- [ ] medium模型：质量最好，但慢
- [ ] 中文识别准确率 >90%
- [ ] 处理时间记录

### 8.4 模型对比

| 模型 | 参数量 | 速度 (1分钟音频) | 准确率 |
|------|--------|------------------|--------|
| tiny | 39M | ~10秒 | ~80% |
| base | 74M | ~20秒 | ~90% |
| small | 244M | ~40秒 | ~95% |
| medium | 769M | ~80秒 | ~98% |

**推荐**：medium模型（4090约2分钟，100秒处理1分钟音频）

---

## 九、完整流程串联测试

### 9.1 测试脚本

```bash
#!/bin/bash
# test_pipeline.sh - 完整流程测试

set -e

echo "========== 开始完整流程测试 =========="
START_TIME=$(date +%s)

# 1. 提取音频
echo "[1/6] 提取音频..."
ffmpeg -i test_video.mp4 -vn -acodec pcm_s16le -ar 16000 -ac 1 audio.wav

# 2. Whisper转写
echo "[2/6] Whisper转写..."
whisper audio.wav --model medium --language zh --fp16 False --output_json --output_dir . 2>/dev/null
TRANSCRIPT=$(cat audio.json | jq -r '.text')

# 3. 千问改写
echo "[3/6] 千问改写..."
python3 << EOF
import os
from dashscope import Generation

os.environ['DASHSCOPE_API_KEY'] = '${DASHSCOPE_API_KEY}'

response = Generation.call(
    model='qwen-plus',
    prompt=f'改写成原创：{transcript}',
    max_tokens=500
)
print(response.output['text'])
EOF
REWRITTEN_SCRIPT=$(python3 -c "...")

# 4. EdgeTTS配音
echo "[4/6] EdgeTTS配音..."
python -m edge_tts -t "$REWRITTEN_SCRIPT" -vo "zh-CN-XiaoxiaoNeural" -o dubbed_audio.mp3

# 5. Wav2Lip生成
echo "[5/6] Wav2Lip唇形同步..."
python inference.py \
  --checkpoint_path checkpoints/wav2lip_gan.pth \
  --face test_video.mp4 \
  --audio dubbed_audio.mp3 \
  --outfile final_output.mp4

# 6. FFmpeg合成
echo "[6/6] FFmpeg合成最终视频..."
ffmpeg -i final_output.mp4 -i bgm.mp3 -shortest -c:v libx264 -c:a aac final_video.mp4

END_TIME=$(date +%s)
echo "========== 测试完成，耗时 $((END_TIME - START_TIME)) 秒 =========="
```

### 9.2 验证清单

- [ ] 全流程跑通
- [ ] 最终视频生成成功
- [ ] 总耗时记录
- [ ] 视频质量自评
- [ ] 每个环节耗时拆解

---

## 十、验证报告模板

```markdown
# 技术验证报告

## 测试环境
- GPU: RTX 4090 24GB / A100 40GB
- 系统: Ubuntu 22.04
- Python: 3.10

## 测试结果

### Wav2Lip
| 指标 | 结果 | 评分 |
|------|------|------|
| 安装难度 | 易/中/难 | ⭐⭐ |
| 处理速度 | X秒/条 | - |
| 唇形同步质量 | 1-5分 | X分 |
| 总体评价 | | 可用/需优化/不可用 |

### SadTalker
| 指标 | 结果 | 评分 |
|------|------|------|
| 安装难度 | 易/中/难 | ⭐⭐⭐ |
| 处理速度 | X秒/条 | - |
| 头像质量 | 1-5分 | X分 |
| 总体评价 | | 可用/需优化/不可用 |

### Coqui XTTS
| 指标 | 结果 | 评分 |
|------|------|------|
| 安装难度 | 易/中/难 | ⭐⭐⭐ |
| 克隆质量 | 1-5分 | X分 |
| 中文支持 | | 良好/一般/差 |
| 总体评价 | | 可用/需优化/不可用 |

### EdgeTTS
| 指标 | 结果 | 评分 |
|------|------|------|
| 声音质量 | 1-5分 | X分 |
| 中文效果 | | 良好/一般/差 |
| 总体评价 | | 可用/需优化/不可用 |

### 千问Qwen
| 指标 | 结果 | 评分 |
|------|------|------|
| API响应速度 | X秒 | - |
| 改写质量 | 1-5分 | X分 |
| 费用 | ¥X/千tokens | - |
| 总体评价 | | 可用/需优化/不可用 |

### Whisper
| 指标 | 结果 | 评分 |
|------|------|------|
| 模型选择 | medium | - |
| 中文准确率 | X% | - |
| 处理速度 | X倍速 | - |
| 总体评价 | | 可用/需优化/不可用 |

## 完整流程测试

| 指标 | 结果 |
|------|------|
| 总耗时 | X分钟 |
| 视频质量 | 1-5分 |
| 是否可接受 | 是/否 |

## 结论

### 可用方案
1. Wav2Lip + SadTalker
2. Coqui XTTS / EdgeTTS
3. 千问Qwen
4. Whisper

### 需要优化的
1. ...

### 不建议使用的
1. ...

### 成本估算
- 单条视频成本: ¥X
- 月均成本（100条）: ¥X

## 下一步建议
1. ...
2. ...
3. ...
```

---

## 附录：常见问题

### Q1: Wav2Lip 唇形对不上怎么办？
- 调整 `--pads` 参数
- 确保视频中人脸正对镜头
- 用 `--face_detector blast` 提高检测准确性

### Q2: SadTalker 头部变形严重？
- 使用 `--preprocess full` 而非 `crop`
- 确保照片光线充足、正脸
- 尝试不同的 `--expression_scale`

### Q3: Coqui XTTS 克隆失败？
- 确保训练音频>10秒
- 音频要清晰无噪音
- 说话要连贯，不要断断续续

### Q4: 内存不足？
```bash
# 清理显存
torch.cuda.empty_cache()

# 减小batch size
```
