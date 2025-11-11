import os
import subprocess
import json

# === CONFIGURAÇÕES ===
video_input = "output/out.avi"
audio_input = "uploads/audio.mp3"
output_file = "output/final_video.mp4"

# === VERIFICAÇÕES ===
if not os.path.exists(video_input):
    raise FileNotFoundError(f"❌ Vídeo não encontrado: {video_input}")
if not os.path.exists(audio_input):
    raise FileNotFoundError(f"❌ Áudio não encontrado: {audio_input}")

# === PEGA DURAÇÃO EXATA DO ÁUDIO (em segundos) ===
cmd_duration = [
    "ffprobe", "-v", "error", "-show_entries",
    "format=duration", "-of", "json", audio_input
]
result = subprocess.run(cmd_duration, capture_output=True, text=True)
duration_audio = float(json.loads(result.stdout)["format"]["duration"])
print(f"🎧 Duração do áudio: {duration_audio:.2f}s")

# === COMANDO FFmpeg ===
# O filtro tpad agora usa stop_duration calculado com base no áudio - vídeo
# Assim o vídeo é clonado apenas o necessário
cmd = [
    "ffmpeg",
    "-y",
    "-i", video_input,
    "-i", audio_input,
    "-filter_complex",
    f"[0:v]tpad=stop_mode=clone:stop_duration={duration_audio}[v]",
    "-map", "[v]",
    "-map", "1:a",
    "-c:v", "libx264",
    "-preset", "medium",
    "-crf", "18",
    "-c:a", "aac",
    "-b:a", "192k",
    "-to", str(duration_audio),  # força a duração final = áudio
    output_file
]

print("🎬 Mesclando vídeo e áudio (sincronizando exatamente com o áudio)...")
result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

# === RESULTADO ===
if result.returncode == 0:
    print(f"✅ Vídeo final sincronizado com o áudio: {output_file}")
else:
    print("❌ Erro ao unir vídeo e áudio:")
    print(result.stderr)
