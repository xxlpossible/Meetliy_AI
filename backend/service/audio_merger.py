"""
音频合并工具：将各参会者的 PCM 录音合并为单个 MP3 文件。

流程：
    1. 每路 PCM → WAV（手写 44 字节 RIFF/WAVE 头，16kHz mono Int16）
    2. 单人：直接 ffmpeg 转 MP3
    3. 多人：ffmpeg amix + adelay 按 join_offset 对齐时间轴后混音

adelay 对齐说明：
    参会者 B 比 host 晚加入 N 秒，其录音文件从其加入时刻开始。
    混音时需将 B 的流延迟 N*1000 ms，使其在时间轴上与 host 对齐。
"""
import os
import struct
import subprocess
import uuid

from loguru import logger

from service.meeting_manager import AUDIO_DIR

# PCM 参数（与前端 AudioContext 16000Hz 单声道 Int16 一致）
SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # Int16 = 2 bytes


def _write_wav_header(f, data_size: int):
    """写 44 字节标准 WAV 头。"""
    byte_rate = SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH
    block_align = CHANNELS * SAMPLE_WIDTH
    f.write(struct.pack(
        '<4sI4s4sIHHIIHH4sI',
        b'RIFF',
        36 + data_size,
        b'WAVE',
        b'fmt ',
        16,
        1,  # PCM
        CHANNELS,
        SAMPLE_RATE,
        byte_rate,
        block_align,
        SAMPLE_WIDTH * 8,
        b'data',
        data_size,
    ))


def _pcm_to_wav(pcm_path: str, wav_path: str):
    """将裸 PCM 文件转为 WAV 文件（补 44 字节头）。"""
    pcm_size = os.path.getsize(pcm_path)
    with open(wav_path, "wb") as wav:
        _write_wav_header(wav, pcm_size)
        # 追加 PCM 数据
        with open(pcm_path, "rb") as pcm:
            while True:
                chunk = pcm.read(8192)
                if not chunk:
                    break
                wav.write(chunk)


def merge(participants_info: list[dict]) -> str:
    """
    合并多路 PCM 录音为单个 MP3。

    参数:
        participants_info: [{user_id, username, audio_file_path, join_offset_seconds}]

    返回:
        合并后的 MP3 文件绝对路径。
    """
    if not participants_info:
        raise ValueError("无录音可合并")

    # 过滤掉文件不存在或为空的录音
    valid = [p for p in participants_info
             if os.path.exists(p["audio_file_path"]) and os.path.getsize(p["audio_file_path"]) > 0]

    if not valid:
        raise ValueError("所有录音文件为空或不存在")

    task_id = uuid.uuid4().hex

    # 1. 每路 PCM → WAV
    wav_paths = []
    for p in valid:
        wav_path = os.path.join(AUDIO_DIR, f"{task_id}_{p['user_id']}.wav")
        _pcm_to_wav(p["audio_file_path"], wav_path)
        wav_paths.append((wav_path, p["join_offset_seconds"]))
        logger.info(f"PCM→WAV: {p['audio_file_path']} → {wav_path}")

    output_path = os.path.join(AUDIO_DIR, f"{task_id}_merged.mp3")

    # 2. ffmpeg 合并
    if len(wav_paths) == 1:
        # 单人：直接转 MP3
        cmd = ["ffmpeg", "-y", "-i", wav_paths[0][0], "-codec:a", "libmp3lame", "-qscale:a", "2", output_path]
        logger.info(f"单人转码: {' '.join(cmd)}")
    else:
        # 多人：amix + adelay
        cmd = ["ffmpeg", "-y"]
        # 输入文件
        inputs = []
        filter_parts = []
        mix_labels = []
        for idx, (wav_path, offset) in enumerate(wav_paths):
            cmd.extend(["-i", wav_path])
            inputs.append(wav_path)
            delay_ms = int(max(0.0, offset) * 1000)
            label = f"s{idx}"
            if delay_ms > 0:
                filter_parts.append(
                    f"[{idx}:a]adelay={delay_ms}|{delay_ms}[{label}]"
                )
                mix_labels.append(f"[{label}]")
            else:
                # 不延迟的直接用输入流
                mix_labels.append(f"[{idx}:a]")

        amix_input = "".join(mix_labels)
        n = len(wav_paths)
        filter_parts.append(
            f"{amix_input}amix=inputs={n}:duration=longest:dropout_transition=0"
        )
        filter_complex = ";".join(filter_parts)
        cmd.extend(["-filter_complex", filter_complex, "-codec:a", "libmp3lame", "-qscale:a", "2", output_path])
        logger.info(f"多人混音: filter_complex={filter_complex}")

    # 执行 ffmpeg
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        logger.error(f"ffmpeg 失败 (returncode={result.returncode}):\n{result.stderr}")
        raise RuntimeError(f"ffmpeg 合并失败: {result.stderr[-500:]}")

    logger.info(f"合并完成: {output_path}")

    # 3. 清理临时 WAV 文件（保留 PCM 原始文件以备排查，后续可手动清理）
    for wav_path, _ in wav_paths:
        try:
            os.remove(wav_path)
        except Exception:
            pass

    return output_path
