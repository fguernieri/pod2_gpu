from fastapi import FastAPI, Query, Body, File, UploadFile, Form
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import subprocess, json, os, glob, asyncio, time, cv2, numpy as np, soundfile as sf, pysubs2, aiofiles
from pathlib import Path

# Bibliotecas Whisper
import whisper
from whisper.utils import get_writer
from moviepy.editor import *

app = FastAPI(title="🎬 Video & Karaoke API", version="2.0")

# Monta pasta estática para acessar os arquivos gerados
app.mount("/output", StaticFiles(directory="/workspace/output"), name="output")

# ======================
# 📂 CONFIGURAÇÕES DE DIRETÓRIO
# ======================
UPLOAD_DIR = "/workspace/uploads"
OUTPUT_DIR = "/workspace/output"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

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


def whisper_worker(job_id, input_path, language, model_name, output_format):
    status_file = os.path.join(OUTPUT_DIR, f"{job_id}_status.json")

    # Inicia status
    with open(status_file, "w") as f:
        f.write(json.dumps({
            "status": "🔄 iniciando modelo",
            "arquivo": input_path,
            "timestamp": time.time()
        }, ensure_ascii=False))

    try:
        # Modelo
        model = whisper.load_model(model_name)

        # Atualiza status
        with open(status_file, "w") as f:
            f.write(json.dumps({
                "status": "🎙️ transcrevendo",
                "arquivo": input_path,
                "timestamp": time.time()
            }, ensure_ascii=False))

        kwargs = {}
        if language:
            kwargs["language"] = language

        result = model.transcribe(input_path, **kwargs)

        # Output final
        output_path = os.path.splitext(input_path)[0] + f".{output_format}"

        writer = get_writer(output_format, OUTPUT_DIR)
        writer(result, input_path)

        # Lê conteúdo final
        with open(output_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Finaliza status — aqui o /status já entende normalmente
        with open(status_file, "w") as f:
            f.write(json.dumps({
                "status": "✅ concluído",
                "arquivo": os.path.basename(output_path),
                "content": content,
                "timestamp": time.time()
            }, ensure_ascii=False))

        os.remove(input_path)
        os.remove(output_path)

    except Exception as e:
        with open(status_file, "w") as f:
            f.write(json.dumps({
                "status": "❌ erro",
                "mensagem": str(e),
                "arquivo": input_path,
                "timestamp": time.time()
            }, ensure_ascii=False))


# ========================
# 🧠 ENDPOINT: /whisper async
# ========================
@app.post("/whisper_async")
async def whisper_async(
    file: UploadFile = File(...),
    language: str = Form(None),
    model_name: str = Form("small"),
    output_format: str = Form("text")
):
    try:
        # job_id no mesmo padrão dos vídeos
        job_id = str(uuid.uuid4())
        input_path = os.path.join(UPLOAD_DIR, f"{job_id}_{file.filename}")

        # salva o áudio
        async with aiofiles.open(input_path, "wb") as f:
            await f.write(await file.read())

        # status inicial
        status_file = os.path.join(OUTPUT_DIR, f"{job_id}_status.json")
        with open(status_file, "w") as f:
            f.write(json.dumps({
                "status": "⏳ aguardando início",
                "arquivo": input_path,
                "timestamp": time.time()
            }, ensure_ascii=False))

        # dispara job no background
        loop = asyncio.get_event_loop()
        loop.run_in_executor(
            EXECUTOR,
            whisper_worker,
            job_id,
            input_path,
            language,
            model_name,
            output_format,
        )

        # resposta imediata
        return {
            "job_id": job_id,
            "status": "⏳ iniciado",
            "check": f"/status/{job_id}"
        }

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)



# ========================
# 🧠 ENDPOINT: /whisper
# ========================
@app.post("/whisper")
async def transcribe_audio(
    file: UploadFile = File(...),
    language: str = Form(None),
    model_name: str = Form("small"),
    output_format: str = Form("text")
):
    """
    Transcreve áudio com o modelo Whisper.
    Suporta formatos: text, srt, vtt, json.
    Garante UTF-8 em qualquer idioma (pt, es, en...).
    """
    try:
        # Caminhos base
        input_path = os.path.join(UPLOAD_DIR, f"{file.filename}")
        with open(input_path, "wb") as f:
            f.write(await file.read())

        # Carrega modelo
        model = whisper.load_model(model_name)

        # Parâmetros opcionais
        kwargs = {}
        if language:
            kwargs["language"] = language

        # Transcreve
        result = model.transcribe(input_path, **kwargs)

        # Writer oficial do Whisper
        writer = get_writer(output_format, UPLOAD_DIR)
        writer(result, input_path)

        # Caminho de saída
        output_path = os.path.splitext(input_path)[0] + f".{output_format}"

        # 🔧 Normaliza o arquivo para UTF-8
        # Corrige casos onde o writer grava em latin-1 (pt/es quebrado)
        if output_format in ["srt", "vtt", "text"]:
            try:
                with open(output_path, "r", encoding="utf-8", errors="ignore") as f:
                    content_utf8 = f.read()
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(content_utf8)
                print(f"✅ [{output_format.upper()}] Normalizado para UTF-8 → {os.path.basename(output_path)}")
            except Exception as e:
                print(f"⚠️ Falha ao normalizar UTF-8: {e}")

        # Lê o conteúdo final
        with open(output_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Limpeza opcional (comentada a remoção do áudio)
        # os.remove(input_path)
        os.remove(output_path)

        return JSONResponse({
            "format": output_format,
            "language": result.get("language", language or "auto"),
            "content": content
        })

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)



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
# 🎥 Endpoint: Gerar vídeo base - Async
# ======================================================

@app.post("/gera-video-async")
async def gera_video_async(
    audio_name: str = Body(...),
    image_pattern: str = Body("VID*.png"),
    output_name: str = Body("out.avi"),
    fps: int = Body(30),
    zoom_factor: float = Body(1.05),
):
    """
    Gera vídeo base em background (GPU CUDA + Ken Burns + Crossfade)
    e salva progresso em JSON para acompanhamento via /status/{output_name}.
    """
    uploads = "/workspace/uploads"
    output = "/workspace/output"
    os.makedirs(output, exist_ok=True)

    base_name = Path(output_name).stem
    status_file = os.path.join(output, f"{base_name}_status.json")

    async def salvar_status(etapa, progresso=None, mensagem=None):
        """Grava status incremental assíncrono"""
        data = {
            "etapa": etapa,
            "progresso": progresso,
            "mensagem": mensagem,
            "timestamp": time.time(),
        }
        async with aiofiles.open(status_file, "w") as f:
            await f.write(json.dumps(data, ensure_ascii=False, indent=2))

    # Cria status inicial
    await salvar_status("inicializando", 0, "Preparando geração de vídeo...")

    async def processar_video():
        try:
            audio_path = os.path.join(uploads, audio_name)
            files = sorted(glob.glob(os.path.join(uploads, image_pattern)))

            if not os.path.exists(audio_path):
                await salvar_status("erro", 0, f"Áudio não encontrado: {audio_path}")
                return
            if not files:
                await salvar_status("erro", 0, f"Nenhuma imagem encontrada com padrão {image_pattern}")
                return

            # 🎧 Calcula duração do áudio
            audio_duration = get_audio_duration(audio_path)

            # 🎞️ Prepara estrutura do vídeo
            img0 = cv2.imread(files[0])
            h, w = img0.shape[:2]
            video_path = os.path.join(output, output_name)
            video = cv2.VideoWriter(video_path, cv2.VideoWriter_fourcc(*"MJPG"), fps, (w, h))

            frames_total = int(fps * audio_duration)
            frames_por_img = frames_total // len(files)
            transition_frames = int(frames_por_img * 0.2)
            frames_por_img = int(frames_por_img * 0.8)

            # 🔥 Carrega imagens na GPU
            gpu_images = []
            for idx, f in enumerate(files):
                img = cv2.imread(f)
                if img is None:
                    await salvar_status("erro", 0, f"Falha ao ler imagem: {f}")
                    return
                g = cv2.cuda_GpuMat()
                g.upload(img)
                gpu_images.append(g)
                await salvar_status("carregando", round((idx+1)/len(files)*10, 2), f"Imagem {idx+1}/{len(files)} carregada")

            # 🌀 Processa imagens (Ken Burns + Crossfade)
            frame_count = 0
            total_frames = len(gpu_images) * (frames_por_img + transition_frames)
            await salvar_status("renderizando", 15, "Iniciando composição...")

            for i, gpu_img in enumerate(gpu_images):
                start_zoom = 1.0
                if i > 0:
                    start_zoom = zoom_factor * 0.98  # leve recuo para suavizar
                # Ken Burns (movimento interno)
                for frame in kenburns_zoom_in(gpu_img, frames_por_img, w, h, zoom_factor, start_zoom):
                    write_frame(video, frame)
                    frame_count += 1
                    if frame_count % (fps * 2) == 0:
                        perc = round((frame_count / total_frames) * 100, 2)
                        await salvar_status("renderizando", perc, f"{perc}% concluído...")

                # Transição crossfade
                if i + 1 < len(gpu_images):
                    for f in crossfade_transition_smooth(
                        gpu_img, gpu_images[i + 1], w, h, zoom_factor, transition_frames
                    ):
                        write_frame(video, f)
                        frame_count += 1

            video.release()
            await salvar_status("concluido", 100, f"✅ Vídeo base gerado com sucesso ({round(audio_duration,2)}s)")
        except Exception as e:
            await salvar_status("erro", 0, f"Exceção: {str(e)}")

    # 🚀 Dispara task assíncrona em background
    asyncio.create_task(processar_video())

    return {
        "status": "🟢 render iniciado",
        "output": os.path.join(output, output_name),
        "status_file": status_file,
        "mensagem": "Processamento em background. Consulte /status/{output_name}.",
    }

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

# ======================================================
# 🔀 Endpoint: Merge com áudio e legenda sincronizada - Async
# ======================================================
@app.post("/merge-video-async")
async def merge_video_async(
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
    base_name = Path(output_name).stem
    status_file = os.path.join(output, f"{base_name}_status.json")

    async def salvar_status(etapa, progresso=None, mensagem=None):
        data = {
            "etapa": etapa,
            "progresso": progresso,
            "mensagem": mensagem,
            "timestamp": time.time(),
        }
        async with aiofiles.open(status_file, "w") as f:
            await f.write(json.dumps(data, ensure_ascii=False, indent=2))

    await salvar_status("inicializando", 0, "Preparando merge...")

    async def processar_merge():
        try:
            if not os.path.exists(video_input) or not os.path.exists(audio_input):
                await salvar_status("erro", 0, "❌ Arquivo de vídeo ou áudio não encontrado")
                return

            # Sincroniza legenda
            sync_legenda_with_audio(subtitle_input, audio_input, subtitle_sync)
            await salvar_status("legenda sincronizada", 10, "Legenda sincronizada com áudio.")

            # Calcula duração do áudio
            cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                   "-of", "json", audio_input]
            result = subprocess.run(cmd, capture_output=True, text=True)
            duration_audio = float(json.loads(result.stdout)["format"]["duration"])

            # Comando FFmpeg
            subtitle_path = subtitle_sync.replace(":", "\\:")
            filter_complex = (
                f"[0:v]format=yuv420p,"
                f"tpad=stop_mode=clone:stop_duration={duration_audio},"
                f"ass={subtitle_path}:fontsdir={font_dir}[v]"
            )

            cmd_merge = [
                "ffmpeg", "-hide_banner", "-v", "warning", "-y",
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

            process = subprocess.Popen(cmd_merge)

            # Loop de monitoramento por tamanho do arquivo
            await salvar_status("renderizando", 20, "Render iniciado...")
            last_size = 0
            while process.poll() is None:
                await asyncio.sleep(2)
                if os.path.exists(output_file):
                    size_mb = os.path.getsize(output_file) / (1024 * 1024)
                    if size_mb != last_size:
                        last_size = size_mb
                        await salvar_status("renderizando", None,
                            f"🌀 Render ativo — {round(size_mb,2)} MB")
                    else:
                        await salvar_status("renderizando", None, "⏳ Aguardando progresso...")
            
            # Finalização
            if process.returncode == 0:
                await salvar_status("concluido", 100, f"✅ Merge completo ({round(duration_audio,2)}s)")
            else:
                await salvar_status("erro", 0, f"⚠️ FFmpeg terminou com código {process.returncode}")

        except Exception as e:
            await salvar_status("erro", 0, f"Exceção: {str(e)}")

    asyncio.create_task(processar_merge())

    return {
        "status": "🟢 merge iniciado",
        "output": output_file,
        "status_file": status_file,
        "mensagem": "Processando em background. Consulte /status/{output_name}."
    }



# ========================
# 📤 ENDPOINT: /upload
# ========================
@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    filename: str = Form(...)
):
    """
    Salva um arquivo em /workspace/uploads/ com o nome especificado pelo usuário.
    Exemplo de uso (curl):
    curl -X POST "http://localhost:8000/upload" \
         -F "file=@/caminho/arquivo.txt" \
         -F "filename=subpasta/arquivo.txt"
    """
    try:
        # Caminho completo (mantém subpastas)
        file_path = os.path.normpath(os.path.join(UPLOAD_DIR, filename))

        # Normaliza e valida que o caminho está dentro de UPLOAD_DIR
        if not os.path.commonpath([file_path, UPLOAD_DIR]) == UPLOAD_DIR:
            return JSONResponse(
                {"status": "error", "message": "Acesso negado."},
                status_code=403
            )

        # Cria subpastas se necessário
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        # Salva o arquivo
        with open(file_path, "wb") as f:
            f.write(await file.read())


        return JSONResponse({
            "status": "success",
            "original_filename": file.filename,
            "saved_as": filename,
        })

    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

    
# ========================
# 📥 ENDPOINT: /download
# ========================
@app.get("/download/{filename:path}")
async def baixar_arquivo(filename: str):
    """
    Permite baixar qualquer arquivo do diretório /workspace/output.
    Exemplo:
    GET /download/video_final.mp4
    """
    try:
        # Caminho absoluto (mantendo subpastas, se existirem)
        file_path = os.path.join(OUTPUT_DIR, filename)

        # Normaliza o caminho para evitar Path Traversal
        file_path = os.path.normpath(file_path)

        # Garante que está dentro do diretório /workspace/output
        if not file_path.startswith(OUTPUT_DIR):
            return JSONResponse(
                {"error": "Acesso negado."},
                status_code=403
            )

        # Verifica se o arquivo existe
        if not os.path.exists(file_path):
            return JSONResponse(
                {"error": f"Arquivo não encontrado: {filename}"},
                status_code=404
            )

        # Retorna o arquivo via HTTP
        return FileResponse(
            path=file_path,
            filename=os.path.basename(filename),
            media_type="application/octet-stream"
        )

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ======================================================
# 📊 ENDPOINT: STATUS (CONSULTA DE PROGRESSO)
# ======================================================
@app.get("/status/{output_name}")
async def verificar_status_video(output_name: str):
    """
    Consulta o status de um job assíncrono (gera-video ou merge-video).
    Retorna o conteúdo atualizado do _status.json correspondente, sem cache.
    """
    base_name = Path(output_name).stem.replace("_status", "")
    status_file = os.path.join(OUTPUT_DIR, f"{base_name}_status.json")

    # Detecta o arquivo final (mp4, avi, mov, etc.)
    video_path = None
    for ext in [".mp4", ".avi", ".mov"]:
        candidate = os.path.join(OUTPUT_DIR, base_name + ext)
        if os.path.exists(candidate):
            video_path = candidate
            break

    # 🔹 Caso ainda não tenha iniciado
    if not os.path.exists(status_file):
        data = {
            "status": "⏳ aguardando início" if not video_path else "✅ concluído (sem JSON)",
            "arquivo": os.path.basename(video_path) if video_path else f"{base_name}.mp4",
            "tamanho_mb": round(os.path.getsize(video_path) / (1024 * 1024), 2) if video_path else 0,
            "timestamp": time.time()
        }
        return JSONResponse(
            content=data,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )

    # 🔹 Tenta ler o JSON de status (forçando reload completo)
    try:
        async with aiofiles.open(status_file, "r") as f:
            raw = await f.read()
        # força reinterpretação a cada request
        data = json.loads(raw)
    except Exception as e:
        data = {
            "status": "⚠️ erro leitura JSON",
            "mensagem": str(e),
            "arquivo": f"{base_name}.mp4",
            "timestamp": time.time()
        }

    # 🔹 Acrescenta metadados úteis
    data["arquivo"] = os.path.basename(video_path) if video_path else f"{base_name}.mp4"
    if video_path and os.path.exists(video_path):
        data["tamanho_mb"] = round(os.path.getsize(video_path) / (1024 * 1024), 2)
    data["timestamp_resposta"] = time.time()

    return JSONResponse(
        content=data,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )
        
# ======================
# ❤️ HEALTHCHECK
# ======================
@app.get("/")
def healthcheck():
    return {
        "status": "ok",
        "message": "API ativa 🚀",
          }
