#!/root/miniconda3/bin/python
import sys, os, cv2, numpy as np, torch, pickle, glob, math, subprocess
from tqdm import tqdm
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
sys.path.insert(0, '/root/livetalking')

print('='*60)
print('MuseTalk - fp32 precision test v2')
print('='*60)

device = torch.device('cuda')
print(f'设备: {device}')

# 1. 加载模型
print('\n[1] 加载模型...')
from musetalk.utils.utils import load_all_model
vae, unet, pe = load_all_model(
    unet_model_path='/root/livetalking/models/musetalkV15/unet.pth',
    vae_type='sd-vae',
    unet_config='/root/livetalking/models/musetalkV15/musetalk.json',
    device=device
)
# fp32 (不用 half())
print('模型加载成功 (fp32)!')

# 2. 音频处理
print('\n[2] 音频处理...')
from musetalk.whisper.audio2feature import Audio2Feature
audio_path = '/root/livetalking/user_voice.wav'
audio_processor = Audio2Feature(model_path='/root/livetalking/models/whisper/tiny.pt')
audio_feats = audio_processor.audio2feat(audio_path)
print(f'Audio feats: {audio_feats.shape}')

NUM_FRAMES = 150
whisper_chunks_raw = audio_processor.feature2chunks(
    audio_feats, fps=25, batch_size=NUM_FRAMES, audio_feat_length=[2, 2], start=0
)
whisper_chunks = [torch.from_numpy(w).float() for w in whisper_chunks_raw]
print(f'Whisper chunks: {len(whisper_chunks)}')

# 3. Avatar 数据
print('\n[3] Avatar 数据...')
avatar_path = '/root/livetalking/data/avatars/musetalk_avatar1'
img_list = sorted(glob.glob(f'{avatar_path}/full_imgs/*.png'))
print(f'帧数: {len(img_list)}')

with open(f'{avatar_path}/coords.pkl', 'rb') as f:
    coords_list = pickle.load(f)
with open(f'{avatar_path}/mask_coords.pkl', 'rb') as f:
    mask_coords_list = pickle.load(f)
latents_list = torch.load(f'{avatar_path}/latents.pt')
print(f'Latents: {len(latents_list)}, shape: {latents_list[0].shape}')

# 4. 生成视频
print('\n[4] 生成视频 (fp32)...')
FPS = 25
BATCH_SIZE = 4
NUM_TEST_FRAMES = 150

frame_list = [cv2.imread(p) for p in img_list[:NUM_TEST_FRAMES]]
mask_list = [cv2.imread(f'{avatar_path}/mask/{i:08d}.png') for i in range(NUM_TEST_FRAMES)]

H, W = frame_list[0].shape[:2]
fourcc = cv2.VideoWriter_fourcc(*'mp4v')
output_path = '/root/livetalking/fp32_test_output.mp4'
out = cv2.VideoWriter(output_path, fourcc, FPS, (W, H))

def mirror_index(size, idx):
    turn = idx // size
    res = idx % size
    return res if turn % 2 == 0 else size - res - 1

num_frames = NUM_TEST_FRAMES
num_batches = math.ceil(num_frames / BATCH_SIZE)
print(f'生成 {num_frames} 帧 ({num_batches} batches)...')

# 确保所有输入都是 fp32
timesteps = torch.tensor([0], device=device, dtype=torch.float32)

for batch_idx in tqdm(range(num_batches)):
    start_idx = batch_idx * BATCH_SIZE
    end_idx = min(start_idx + BATCH_SIZE, num_frames)
    batch_size_actual = end_idx - start_idx

    latent_batch_list = []
    for i in range(start_idx, end_idx):
        idx = mirror_index(num_frames, i)
        latent_batch_list.append(latents_list[idx])
    # 确保是 fp32
    latent_batch = torch.cat(latent_batch_list, dim=0).float().to(device)

    whisper_batch_list = []
    for i in range(start_idx, end_idx):
        if i < len(whisper_chunks):
            whisper_batch_list.append(whisper_chunks[i])
        else:
            whisper_batch_list.append(whisper_chunks[-1])
    # 确保是 fp32
    whisper_batch = torch.stack(whisper_batch_list).float().to(device)

    audio_prompt = pe(whisper_batch).float()

    with torch.no_grad():
        pred_latents = unet.model(latent_batch, timesteps.expand(batch_size_actual), audio_prompt).sample
        gen_frames = vae.vae.decode(pred_latents / vae.vae.config.scaling_factor).sample
        gen_frames = (gen_frames * 0.5 + 0.5).clamp(0, 1)
        gen_frames_np = gen_frames.detach().cpu().numpy()

    for i in range(gen_frames_np.shape[0]):
        gen_frame = gen_frames_np[i].transpose(1, 2, 0)
        gen_frame = (gen_frame * 255).astype(np.uint8)

        frame_idx = mirror_index(num_frames, start_idx + i)
        bbox = coords_list[frame_idx]
        mask_img = mask_list[frame_idx]
        crop_box = mask_coords_list[frame_idx]

        x1, y1, x2, y2 = bbox
        face_w, face_h = x2 - x1, y2 - y1
        gen_frame_resized = cv2.resize(gen_frame, (face_w, face_h))

        from musetalk.utils.blending import get_image_blending
        combined = get_image_blending(frame_list[frame_idx], gen_frame_resized, bbox, mask_img, crop_box)
        out.write(combined)

out.release()
print(f'输出: {output_path}')

# 5. 合成音频
print('\n[5] 合成音频...')
final_path = '/root/livetalking/fp32_test_final.mp4'
cmd = f'ffmpeg -y -i {output_path} -i {audio_path} -c:v libx264 -c:a aac -shortest {final_path}'
subprocess.run(cmd, shell=True, capture_output=True)
print(f'最终视频: {final_path}')

print('\n' + '='*60)
print('完成!')
print('='*60)
