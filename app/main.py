from fastapi import FastAPI, Query, Body
import subprocess, json, os, glob, random, cv2, numpy as np, soundfile as sf, pysubs2

app = FastAPI(title="🎬 Video & Karaoke API", version="2.0")

# ======================================================
# 🧩 Funções auxiliares
# ======================================================
def get_audio_duration(audio_path):
    data, samplerate = sf.read(audio_path)
    return len(data) / samplerate
    

def write_frame(video, gpu_frame):
    if gpu_frame is None:
        return
    frame_cpu = gpu_frame.download()
    if frame_cpu is None:
        return
    if len(frame_cpu.shape) == 2:
        frame_cpu = cv2.cvtColor(frame_cpu, cv2.COLOR_GRAY2BGR)
    video.write(frame_cpu)

def kenburns_zoom_in(gpu_img, frames, w, h, zoom_factor, start_zoom=1.0):
    for i in range(frames):
        s = start_zoom + (zoom_factor - start_zoom) * (i / (frames - 1))
        dx, dy = w / 2 - (w / 2) * s, h / 2 - (h / 2) * s
        M = np.array([[s, 0, dx], [0, s, dy]], np.float32)
        yield cv2.cuda.warpAffine(gpu_img, M, (w, h))

def crossfade_transition_smooth(gpu_a, gpu_b, w, h, zoom_factor, frames=30):
    """
    Crossfade suave entre duas imagens com leve movimento para evitar 'pulos'.
    """
    # gera uma sequência curta de movimento para ambas
    seq_a = list(kenburns_zoom_in(gpu_a, frames, w, h, zoom_factor * 0.98, zoom_factor))
    seq_b = list(kenburns_zoom_in(gpu_b, frames, w, h, zoom_factor * 0.98, zoom_factor))

    for i in range(frames):
        alpha = i / (frames - 1)
        blended = cv2.cuda.addWeighted(seq_a[i], 1 - alpha, seq_b[i], alpha, 0)
        yield blended


def sync_legenda_with_audio(subtitle_input, audio_input, subtitle_output):
    """Sincroniza a legenda .ass com a duração real do áudio"""
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", audio_input]
    result = subprocess.run(cmd, capture_output=True, text=True)
    duration_audio = float(json.loads(result.stdout)["format"]["duration"])
    subs = pysubs2.load(subtitle_input, encoding="utf-8")

    end_times = [ev.end for ev in subs.events if ev.end > 0]
    if not end_times:
        raise ValueError("❌ Nenhum evento válido na legenda.")
    duration_legenda = max(end_times) / 1000.0
    diff = duration_audio - duration_legenda
    drift_percent = (diff / duration_audio) * 100

    print(f"🎧 Áudio: {duration_audio:.2f}s | 💬 Legenda: {duration_legenda:.2f}s | Δ {diff:+.2f}s ({drift_percent:+.2f}%)")

    if abs(diff) > 0.2:
        scale = duration_audio / duration_legenda
        for ev in subs.events:
            ev.start = int(ev.start * scale)
            ev.end = int(ev.end * scale)
        print(f"✅ Corrigido drift proporcional ({scale:.4f}x).")

    first_sub = min(ev.start for ev in subs.events)
    if first_sub > 500:
        offset = -first_sub + 200
        subs.shift(s=offset / 1000)
        print(f"🔧 Offset inicial ajustado em {offset/1000:.2f}s.")

    subs.save(subtitle_output)
    return subtitle_output

# ======================================================
# 🎥 Endpoint 1: Gerar vídeo base
# ======================================================
@app.post("/gera-video")
def gera_video(
    audio_name: str = Body(...),
    image_pattern: str = Body("VID*.png"),
    output_name: str = Body("out.avi"),
    fps: int = Body(30),
    zoom_factor: float = Body(1.05),
):
    uploads = "/workspace/uploads"
    output = "/workspace/output"
    os.makedirs(output, exist_ok=True)
    audio_path = os.path.join(uploads, audio_name)
    files = sorted(glob.glob(os.path.join(uploads, image_pattern)))

    if not os.path.exists(audio_path):
        return {"erro": f"Áudio não encontrado: {audio_path}"}
    if not files:
        return {"erro": f"Nenhuma imagem encontrada com padrão {image_pattern}"}

    audio_duration = get_audio_duration(audio_path)
    img0 = cv2.imread(files[0])
    h, w = img0.shape[:2]
    video_path = os.path.join(output, output_name)
    video = cv2.VideoWriter(video_path, cv2.VideoWriter_fourcc(*'MJPG'), fps, (w, h))

    frames_total = int(fps * audio_duration)
    frames_por_img = frames_total // len(files)
    transition_frames = int(frames_por_img * 0.2)
    frames_por_img = int(frames_por_img * 0.8)

    gpu_images = []
    for f in files:
        img = cv2.imread(f)
        g = cv2.cuda_GpuMat()
        g.upload(img)
        gpu_images.append(g)

    for i, gpu_img in enumerate(gpu_images):
        start_zoom = 1.0
        end_zoom = zoom_factor
        if i > 0:
            # começa a próxima imagem com o zoom do final da anterior
            start_zoom = zoom_factor * 0.98  # ligeiro recuo para suavizar
        for frame in kenburns_zoom_in(gpu_img, frames_por_img, w, h, zoom_factor, start_zoom):
            write_frame(video, frame)
    
        if i + 1 < len(gpu_images):
            for f in crossfade_transition_smooth(gpu_img, gpu_images[i + 1], w, h, zoom_factor, transition_frames):
                write_frame(video, f)



    video.release()
    return {"status": "✅ Vídeo base gerado", "path": video_path, "duração": round(audio_duration, 2)}

# ======================================================
# 🔀 Endpoint 2: Merge com áudio e legenda sincronizada
# ======================================================
@app.post("/merge-video")
def merge_video(
    video_name: str = Body(...),
    audio_name: str = Body(...),
    subtitle_name: str = Body(...),
    output_name: str = Body("final_karaoke.mp4"),
    preset: str = Body("p5"),
    bitrate: str = Body("8M"),
    font_dir: str = Body("/usr/share/fonts")
):
    uploads = "/workspace/uploads"
    output = "/workspace/output"
    os.makedirs(output, exist_ok=True)
    video_input = os.path.join(output, video_name)
    audio_input = os.path.join(uploads, audio_name)
    subtitle_input = os.path.join(uploads, subtitle_name)
    subtitle_sync = os.path.join(uploads, "legenda_sync.ass")
    output_file = os.path.join(output, output_name)

    if not os.path.exists(video_input) or not os.path.exists(audio_input):
        return {"erro": "❌ Arquivo de vídeo ou áudio não encontrado"}

    # 🔄 Sincroniza a legenda
    sync_legenda_with_audio(subtitle_input, audio_input, subtitle_sync)

    # 🎬 FFmpeg NVENC
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "json", audio_input
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    duration_audio = float(json.loads(result.stdout)["format"]["duration"])

    subtitle_path = subtitle_sync.replace(":", "\\:")
    filter_complex = (
        f"[0:v]format=yuv420p,"
        f"tpad=stop_mode=clone:stop_duration={duration_audio},"
        f"ass={subtitle_path}:fontsdir={font_dir}[v]"
    )

    cmd_merge = [
        "ffmpeg", "-hide_banner", "-v", "warning", "-stats", "-y",
        "-i", video_input, "-i", audio_input,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "1:a",
        "-c:v", "h264_nvenc",
        "-preset", preset,
        "-b:v", bitrate,
        "-maxrate", bitrate,
        "-bufsize", "20M",
        "-c:a", "aac",
        "-b:a", "192k",
        "-to", str(duration_audio),
        "-movflags", "+faststart",
        output_file
    ]

    print("🎬 Gerando vídeo final com GPU NVENC...")
    result = subprocess.run(cmd_merge, text=True, capture_output=True)

    if result.returncode == 0:
        return {"status": "✅ Merge completo", "output": output_file, "duration": duration_audio}
    else:
        return {"erro": result.stderr}
