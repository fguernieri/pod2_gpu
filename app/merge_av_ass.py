import os
import subprocess
import json

# === CONFIGURAÇÕES ===
video_input = "output/out.avi"
audio_input = "uploads/audio.mp3"
subtitle_input = "uploads/legenda.ass"   # gerado pelo srt2ass_karaoke.py
output_file = "output/final_karaoke_gpu.mp4"

# === VERIFICAÇÕES ===
for f in [video_input, audio_input]:
    if not os.path.exists(f):
        raise FileNotFoundError(f"❌ Arquivo não encontrado: {f}")

# === OBTÉM DURAÇÃO EXATA DO ÁUDIO ===
cmd_dur = [
    "ffprobe", "-v", "error",
    "-show_entries", "format=duration",
    "-of", "json", audio_input
]
result = subprocess.run(cmd_dur, capture_output=True, text=True)
duration_audio = float(json.loads(result.stdout)["format"]["duration"])
print(f"🎧 Duração do áudio: {duration_audio:.2f}s")

# === VERIFICAÇÃO DE LEGENDA ===
if not os.path.exists(subtitle_input):
    print("⚠️ Nenhuma legenda .ass encontrada — vídeo será gerado sem texto.")
    subtitle_filter = f"[0:v]tpad=stop_mode=clone:stop_duration={duration_audio}[v]"
    map_video = "[v]"
else:
    print(f"💬 Aplicando legenda: {subtitle_input}")
    subtitle_path = subtitle_input.replace(":", "\\:")
    subtitle_filter = (
        f"[0:v]tpad=stop_mode=clone:stop_duration={duration_audio},"
        f"ass={subtitle_path}:fontsdir=/usr/share/fonts[v]"
    )
    map_video = "[v]"

# === COMANDO FFmpeg COM NVENC ===
cmd = [
    "ffmpeg", "-hide_banner", "-v", "warning", "-stats", "-y",
    "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",  # aceleração GPU
    "-i", video_input,
    "-i", audio_input,
    "-filter_complex", subtitle_filter,
    "-map", map_video, "-map", "1:a",
    "-c:v", "h264_nvenc",
    "-preset", "p4",              # perfil de qualidade/velocidade da NVIDIA
    "-b:v", "8M",                 # taxa de bits sugerida (ajustável)
    "-maxrate", "10M",
    "-bufsize", "20M",
    "-c:a", "aac",
    "-b:a", "192k",
    "-to", str(duration_audio),
    "-movflags", "+faststart",
    output_file
]

print("🎬 Renderizando vídeo final com GPU NVENC + áudio + legenda ASS...")
result = subprocess.run(cmd, text=True, capture_output=True)

if result.returncode == 0:
    print(f"✅ Vídeo final criado com sucesso: {output_file}")
else:
    print("❌ Erro durante o merge:")
    print(result.stderr)
