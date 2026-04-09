#!/usr/bin/env python3
"""画中画服务 - 视频叠加效果"""

import subprocess
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

@dataclass
class PIPPosition:
    """画中画位置配置"""
    x: int      # X坐标
    y: int      # Y坐标
    width: int  # 画中画宽度
    height: int # 画中画高度

# 预设位置
POSITIONS = {
    "左上角": PIPPosition(x=20, y=20, width=320, height=180),
    "右上角": PIPPosition(x="W-w-20", y=20, width=320, height=180),
    "左下角": PIPPosition(x=20, y="H-h-20", width=320, height=180),
    "右下角": PIPPosition(x="W-w-20", y="H-h-20", width=320, height=180),
}

def add_pip(
    main_video: str,
    pip_video: str,
    position: str = "右下角",
    output_path: Optional[str] = None,
    pip_width: Optional[int] = None,
    pip_height: Optional[int] = None
) -> str:
    """添加画中画效果

    Args:
        main_video: 主视频路径
        pip_video: 画中画视频路径
        position: 位置 ("左上角"/"右上角"/"左下角"/"右下角")
        output_path: 输出路径
        pip_width: 画中画宽度(覆盖预设)
        pip_height: 画中画高度(覆盖预设)

    Returns:
        输出视频路径
    """
    if output_path is None:
        output_path = str(Path(main_video).with_suffix('_pip.mp4'))

    pos = POSITIONS.get(position, POSITIONS["右下角"])

    # 允许覆盖宽高
    width = pip_width or pos.width
    height = pip_height or pos.height

    # FFmpeg filter_complex 构建画中画
    # main input: [0:v], pip input: [1:v]
    filter_str = f"[1:v]scale={width}:{height}[pip];[0:v][pip]overlay=x={pos.x}:y={pos.y}:shortest=1:format=yuv420p"

    cmd = [
        'ffmpeg', '-y',
        '-i', main_video,
        '-i', pip_video,
        '-filter_complex', filter_str,
        '-c:a', 'copy',
        output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"画中画处理失败: {result.stderr}")

    print(f">>> 画中画完成: {output_path}")
    return output_path

def add_multiple_pips(
    main_video: str,
    pip_videos: list,
    output_path: Optional[str] = None
) -> str:
    """添加多个画中画（最多4个）

    Args:
        main_video: 主视频
        pip_videos: 画中画视频列表
        output_path: 输出路径

    Returns:
        输出视频路径
    """
    if len(pip_videos) > 4:
        raise ValueError("最多支持4个画中画")

    if output_path is None:
        output_path = str(Path(main_video).with_suffix('_multi_pip.mp4'))

    # 构建输入
    cmd = [
        'ffmpeg', '-y',
        '-i', main_video
    ]

    # 添加所有画中画输入
    positions = ["左上角", "右上角", "左下角", "右下角"]
    for pip_video in pip_videos:
        cmd.extend(['-i', pip_video])

    # 构建filter
    filters = []
    for i, pos_name in enumerate(positions[:len(pip_videos)]):
        pos = POSITIONS[pos_name]
        filters.append(f"[{i+1}:v]scale={pos.width}:{pos.height}[pip{i}]")

    # 叠加
    filters.append(f"[0:v]")
    for i in range(len(pip_videos)):
        filters.append(f"[pip{i}]overlay=0:0:shortest=1:format=yuv420p")

    cmd.extend(['-filter_complex', ';'.join(filters), '-c:a', 'copy', output_path])

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"多画中画处理失败: {result.stderr}")

    print(f">>> 多画中画完成: {output_path}")
    return output_path


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("用法: python3 pip.py <主视频> <画中画视频> [位置]")
        print("  位置: 左上角/右上角/左下角/右下角 (默认右下角)")
        sys.exit(1)

    main = sys.argv[1]
    pip = sys.argv[2]
    position = sys.argv[3] if len(sys.argv) > 3 else "右下角"

    result = add_pip(main, pip, position)
    print(f"\n>>> 完成: {result}")
