#!/usr/bin/env python3
"""在GPU服务器上测试加载标准Wav2Lip模型"""
import sys
sys.path.insert(0, '/root/livetalking')

import torch
import torch.nn as nn
import numpy as np

# 标准Wav2Lip架构（来自wav2lip/models/wav2lip.py）
class Conv2D(nn.Module):
    def __init__(self, in_ch, out_ch, kernel_size=3, stride=1, padding=1):
        super().__init__()
        self.conv = nn.Conv2d(in_ch, out_ch, kernel_size, stride, padding)
        self.bn = nn.BatchNorm2d(out_ch)
        self.relu = nn.ReLU(inplace=True)

    def forward(self, x):
        return self.relu(self.bn(self.conv(x)))

class ResBlock(nn.Module):
    def __init__(self, in_ch, out_ch):
        super().__init__()
        self.conv1 = Conv2D(in_ch, out_ch)
        self.conv2 = nn.Conv2d(out_ch, out_ch, 3, 1, 1)
        self.bn2 = nn.BatchNorm2d(out_ch)
        self.skip = nn.Conv2d(in_ch, out_ch, 1) if in_ch != out_ch else nn.Identity()

    def forward(self, x):
        residual = self.skip(x)
        out = self.conv1(x)
        out = self.bn2(self.conv2(out))
        return torch.relu(out + residual)

class AudioEncoder(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv1 = Conv2D(1, 32, 3, 1, 1)    # [B, 1, 80, T] -> [B, 32, 80, T]
        self.conv2 = Conv2D(32, 32, 3, 1, 1)
        self.conv3 = Conv2D(32, 64, 3, 1, 1)    # -> [B, 64, 80, T]
        self.conv4 = Conv2D(64, 64, 3, 1, 1)
        self.conv5 = Conv2D(64, 128, 3, (2,1), 1) # 时间维度减半
        self.conv6 = Conv2D(128, 128, 3, 1, 1)
        self.conv7 = Conv2D(128, 256, 3, (2,1), 1)
        self.conv8 = Conv2D(256, 512, 3, 1, 1)

    def forward(self, x):
        x = self.conv1(x)
        x = self.conv2(x)
        x = self.conv3(x)
        x = self.conv4(x)
        x = self.conv5(x)
        x = self.conv6(x)
        x = self.conv7(x)
        x = self.conv8(x)
        return x

class FaceEncoderBlock(nn.Module):
    def __init__(self, in_ch, out_ch):
        super().__init__()
        self.conv_block = ResBlock(in_ch, out_ch)

    def forward(self, x):
        return self.conv_block(x)

class FaceEncoder(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv1 = Conv2D(6, 16, 3, 1, 1)
        self.blocks = nn.ModuleList([
            FaceEncoderBlock(16, 16),
            FaceEncoderBlock(16, 32),
            FaceEncoderBlock(32, 64),
            FaceEncoderBlock(64, 128),
            FaceEncoderBlock(128, 256),
            FaceEncoderBlock(256, 512),
        ])
        self.pad = nn.ZeroPad2d((0, 0, 1, 0))

    def forward(self, x):
        x = self.conv1(x)
        for block in self.blocks:
            x = block(x)
        x = self.pad(x)
        return x  # [B, 512, 6, W]

class FaceDecoder(nn.Module):
    def __init__(self):
        super().__init__()
        self.ups1 = nn.Upsample(scale_factor=(2, 1), mode='bilinear', align_corners=False)
        self.conv1 = Conv2D(512+512, 512)
        self.ups2 = nn.Upsample(scale_factor=(2, 1), mode='bilinear', align_corners=False)
        self.conv2 = Conv2D(512, 256)
        self.ups3 = nn.Upsample(scale_factor=(2, 1), mode='bilinear', align_corners=False)
        self.conv3 = Conv2D(256, 128)
        self.ups4 = nn.Upsample(scale_factor=(2, 1), mode='bilinear', align_corners=False)
        self.conv4 = Conv2D(128, 64)
        self.final = nn.Conv2d(64, 3, 1)

    def forward(self, x):
        x = self.ups1(x)
        x = self.conv1(x)
        x = self.ups2(x)
        x = self.conv2(x)
        x = self.ups3(x)
        x = self.conv3(x)
        x = self.ups4(x)
        x = self.conv4(x)
        return torch.sigmoid(self.final(x))

class Wav2Lip(nn.Module):
    def __init__(self):
        super().__init__()
        self.audio_encoder = AudioEncoder()
        self.face_encoder = FaceEncoder()
        self.face_decoder = FaceDecoder()

    def forward(self, face, mel):
        face_feat = self.face_encoder(face)
        audio_feat = self.audio_encoder(mel)
        # 时间维度对齐
        if audio_feat.shape[-1] != face_feat.shape[-1]:
            audio_feat = nn.functional.interpolate(audio_feat, size=face_feat.shape[2:], mode='bilinear', align_corners=False)
        x = torch.cat([face_feat, audio_feat], dim=1)
        return self.face_decoder(x)

def test_load():
    print("加载检查点...")
    ckpt = torch.load('/root/livetalking/models/wav2lip.pth', map_location='cpu')
    sd = ckpt['state_dict']
    print(f"检查点键数量: {len(sd)}")

    print("\n创建模型...")
    model = Wav2Lip()

    print("\n尝试加载检查点...")
    try:
        model.load_state_dict(sd, strict=True)
        print("✅ 加载成功！")
        return True
    except RuntimeError as e:
        print(f"❌ 加载失败: {e}")
        return False

if __name__ == "__main__":
    success = test_load()
    sys.exit(0 if success else 1)
