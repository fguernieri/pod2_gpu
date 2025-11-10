import os
os.environ["IMAGEIO_FFMPEG_EXE"] = "/usr/bin/ffmpeg"

from fastapi import FastAPI, UploadFile, File, Form, Body
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import subprocess
import whisper
from whisper.utils import get_writer
from moviepy.editor import *
import uuid, glob, json, tempfile, shutil, time, math, random
from threading import Thread
from pathlib import Path


# ======================
# 🎬 CONFIGURAÇÃO GERAL
# ======================

# Força o MoviePy a usar o ffmpeg do sistema
os.environ["IMAGEIO_FFMPEG_EXE"] = "/usr/bin/ffmpeg"

# ======================
# ⚙️ IMPORTAÇÕES FASTAPI
# ======================
from fastapi import FastAPI, UploadFile, File, Form, Body
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

# Bibliotecas principais
import whisper
from whisper.utils import get_writer
from moviepy.editor import *

# ======================
# 🚀 CONFIGURAÇÃO DA API
# ======================
app = FastAPI(
    title="FFmpeg + Whisper API",
    description="Serviço HTTP unificado para conversão, transcrição e geração de vídeos com Ken Burns",
    version="2.0.0"
)

# Monta pasta estática para acessar os arquivos gerados
app.mount("/output", StaticFiles(directory="/workspace/output"), name="output")

# ======================
# 📂 CONFIGURAÇÕES DE DIRETÓRIO
# ======================
UPLOAD_DIR = "/workspace/uploads"
OUTPUT_DIR = "/workspace/output"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ======================
# ❤️ HEALTHCHECK
# ======================
@app.get("/")
def healthcheck():
    return {
        "status": "ok",
        "message": "API FFmpeg + Whisper ativa 🚀",
        "routes": ["/upload", "/ffmpeg", "/ffmpeg_ken", "/ffmpeg_burn", "/whisper"]
          }
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

# ========================
# 🎬 ENDPOINT: /ffmpeg (conversão simples)
# ========================
@app.post("/ffmpeg")
async def convert_media(
    file: UploadFile = File(...),
    output_format: str = Form("mp3")
):
    """
    Converte qualquer arquivo de mídia usando FFmpeg.
    Exemplo: POST /ffmpeg com 'file=@video.mp4' e 'output_format=wav'
    """
    try:
        input_path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}_{file.filename}")
        output_path = f"{os.path.splitext(input_path)[0]}.{output_format}"

        with open(input_path, "wb") as f:
            f.write(await file.read())

        cmd = ["ffmpeg", "-y", "-i", input_path, output_path]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        os.remove(input_path)
        return FileResponse(output_path, filename=os.path.basename(output_path))

    except subprocess.CalledProcessError as e:
        return JSONResponse({"error": f"Erro FFmpeg: {e.stderr.decode('utf-8')}"}, status_code=500)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ========================
# 📤 ENDPOINT: /upload
# ========================
@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    filename: str = Form(...)
):
    """
    Salva um arquivo em /workspace/uploads/ com o nome especificado pelo usuário
    """
    try:
        # Usa o nome informado pelo usuário
        safe_filename = os.path.basename(filename)
        filepath = os.path.join(UPLOAD_DIR, safe_filename)

        with open(filepath, "wb") as f:
            f.write(await file.read())

        return JSONResponse({
            "status": "success",
            "original_filename": file.filename,
            "saved_as": safe_filename,
            "path": filepath
        })

    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

# ========================
#  Ken Burns Sei lá
# ========================
@app.post("/ffmpeg_ken_simple")
async def gerar_video_kenburns_simples(
    audio_file: str = Form(...),
    image_pattern: str = Form(...),
    output_name: str = Form("video_simple.mp4"),
    zoom_start: float = Form(1.0),
    zoom_end: float = Form(1.1),
    pan_strength: float = Form(20),
    fps_final: int = Form(30),
    delay_start: float = Form(0.0),
    fade: bool = Form(True),
    audio_delay: float = Form(0.0),
    codec: str = Form("h264_nvenc"),
    preset: str = Form("p5")
):
    """
    Gera vídeo com efeito Ken Burns leve (zoom + pan suave via MoviePy),
    processando em background (não bloqueia a requisição HTTP)
    e grava status em arquivo JSON.
    """
    status_path = os.path.join(OUTPUT_DIR, f"{Path(output_name).stem}_status.json")

    def salvar_status(data: dict):
        """Atualiza arquivo de status JSON no disco."""
        with open(status_path, "w") as f:
            json.dump({**data, "timestamp": time.time()}, f)

    def render_task():
        try:
            salvar_status({"status": "processing", "output": output_name})

            audio_path = os.path.join(UPLOAD_DIR, audio_file)
            imagens_glob = os.path.join(UPLOAD_DIR, image_pattern)
            output_path = os.path.join(OUTPUT_DIR, output_name)
            os.makedirs(OUTPUT_DIR, exist_ok=True)

            imagens = sorted(glob.glob(imagens_glob))
            if not imagens:
                salvar_status({"status": "error", "message": f"Nenhuma imagem encontrada em {imagens_glob}"})
                return

            if not os.path.exists(audio_path):
                salvar_status({"status": "error", "message": f"Áudio não encontrado: {audio_path}"})
                return

            audio = AudioFileClip(audio_path)
            if audio_delay > 0:
                audio = audio.set_start(audio_delay)

            num_imagens = len(imagens)
            duracao_por_imagem = max(audio.duration / num_imagens, 0.1)

            def kenburns(img_path, duration=4, zoom_start=1.0, zoom_end=1.1, pan_strength=20, fps=30):
                base = ImageClip(img_path).resize(height=1080).set_duration(duration)
                w, h = base.size
                target_w, target_h = 1920, 1080

                def make_frame(t):
                    progress = max(0, min(t / duration, 1))
                    smooth = 0.5 - 0.5 * math.cos(math.pi * progress)
                    zoom = round(zoom_start + (zoom_end - zoom_start) * smooth, 8)
                    frame = base.resize(zoom).get_frame(t)

                    fw, fh = int(w * zoom), int(h * zoom)
                    x_offset = int((fw - target_w) / 2 + pan_strength * math.sin(progress * math.pi))
                    y_offset = int((fh - target_h) / 2 + (pan_strength / 2) * math.cos(progress * math.pi))
                    x_offset = max(0, min(x_offset, fw - target_w))
                    y_offset = max(0, min(y_offset, fh - target_h))
                    cropped = frame[y_offset:y_offset + target_h, x_offset:x_offset + target_w]
                    return cropped

                clip = VideoClip(make_frame, duration=duration).set_fps(fps)
                if fade:
                    clip = clip.fadein(0.5).fadeout(0.5)
                return clip

            clips = []
            for i, img in enumerate(imagens):
                if os.path.exists(img):
                    if i % 2 == 0:
                        current_zoom_start, current_zoom_end = zoom_start, zoom_end
                    else:
                        current_zoom_start, current_zoom_end = zoom_end, zoom_start

                    clip = kenburns(
                        img,
                        duration=duracao_por_imagem,
                        zoom_start=current_zoom_start,
                        zoom_end=current_zoom_end,
                        pan_strength=pan_strength,
                        fps=fps_final
                    )
                    clips.append(clip)

            if not clips:
                salvar_status({"status": "error", "message": "Nenhum clipe válido gerado."})
                return

            video = concatenate_videoclips(clips, method="compose").set_fps(fps_final)
            if delay_start > 0:
                video = video.set_start(delay_start)

            safe_duration = max(0, audio.duration - 0.2)
            final = video.set_audio(audio).subclip(0, safe_duration)

            final.write_videofile(
                output_path,
                fps=fps_final,
                codec=codec,
                audio_codec="aac",
                preset=preset,
                ffmpeg_params=["-pix_fmt", "yuv420p", "-vsync", "1"],
                threads=2,
                logger=None
            )

            salvar_status({
                "status": "done",
                "output": output_name,
                "tamanho_mb": round(os.path.getsize(output_path) / (1024 * 1024), 2)
            })
            print(f"✅ Vídeo concluído: {output_path}")

        except Exception as e:
            salvar_status({"status": "error", "message": str(e)})
            print(f"[ERRO] {e}")

    Thread(target=render_task).start()

    return JSONResponse({
        "status": "processing",
        "message": "🎬 Renderização iniciada em segundo plano.",
        "output_file": output_name,
        "status_path": f"/workspace/output/{Path(output_name).stem}_status.json"
    })

# ========================
# ❤️ Ken Burns 2D
# ========================
def limpar_arquivos(out_dir: str, manter: str):
    """
    Remove arquivos temporários e diretórios de segmentos,
    preservando apenas o arquivo final.
    """
    print(f"🧹 Limpando temporários em {out_dir} ...")
    try:
        for item in os.listdir(out_dir):
            caminho = os.path.join(out_dir, item)
            # Mantém apenas o vídeo final
            if caminho == manter:
                continue
            # Remove diretórios de segmentos
            if os.path.isdir(caminho) and item.startswith("seg_"):
                shutil.rmtree(caminho, ignore_errors=True)
            # Remove arquivos auxiliares (list.txt, logs etc.)
            elif os.path.isfile(caminho) and not caminho.endswith(".mp4"):
                os.remove(caminho)
        print("✅ Limpeza concluída com sucesso!")
    except Exception as e:
        print(f"⚠️ Erro ao limpar: {e}")

@app.post("/kenburns_auto")
async def kenburns_auto(
    audio_file: str = Form(...),
    image_pattern: str = Form(...),
    zoom: float = Form(1.08),
    shiftx: float = Form(0.02),
    shifty: float = Form(-0.01),
    fps: int = Form(30),
    out_dir: str = Form("/workspace/output"),
    limpar: bool = Form(True)
):
    try:
        # =====================================================
        # 1️⃣ Entradas
        # =====================================================
        audio_path = f"/workspace/uploads/{audio_file}"
        image_paths = sorted(glob.glob(f"/workspace/uploads/imagens/{image_pattern}"))
        assert len(image_paths) > 0, "Nenhuma imagem encontrada no padrão informado"
        os.makedirs(out_dir, exist_ok=True)

        # =====================================================
        # 2️⃣ Duração total do áudio
        # =====================================================
        cmd_dur = [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path
        ]
        duration = float(subprocess.check_output(cmd_dur).decode().strip())
        tempo_por_img = duration / len(image_paths)
        print(f"🎧 Áudio: {duration:.2f}s | {len(image_paths)} imagens | {tempo_por_img:.2f}s/img")

        # =====================================================
        # 3️⃣ Gera vídeos individuais (Ken Burns)
        # =====================================================
        seg_videos = []
        for i, img in enumerate(image_paths):
            seg_dir = f"{out_dir}/seg_{i:03d}"
            os.makedirs(seg_dir, exist_ok=True)
            out_seg = f"{seg_dir}/video_out_smooth.mp4"

            cmd = [
                "python", "/workspace/kenburns_2d/kenburns_2d_smooth.py",
                "--image", img,
                "--out", seg_dir,
                "--zoom", str(zoom),
                "--shiftx", str(shiftx),
                "--shifty", str(shifty),
                "--frames", str(int(fps * tempo_por_img)),
                "--fps", str(fps)
            ]
            subprocess.run(cmd, check=True)
            seg_videos.append(out_seg)

        assert len(seg_videos) > 0, "Nenhum trecho de vídeo gerado"

        # =====================================================
        # 4️⃣ Cria lista para concatenação
        # =====================================================
        list_file = f"{out_dir}/list.txt"
        with open(list_file, "w") as f:
            for seg in seg_videos:
                f.write(f"file '{seg}'\n")

        # =====================================================
        # 5️⃣ Junta tudo + áudio
        # =====================================================
        output_final = f"{out_dir}/final_kenburns.mp4"

        nvenc_check = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True
        )
        encoder = "h264_nvenc" if "h264_nvenc" in nvenc_check.stdout else "libx264"

        cmd_concat = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_file,
            "-i", audio_path,
            "-c:v", encoder,
            "-c:a", "aac",
            "-shortest",
            output_final
        ]
        subprocess.run(cmd_concat, check=True)

        # =====================================================
        # 6️⃣ Limpa arquivos temporários
        # =====================================================
        if limpar:
            limpar_arquivos(out_dir, manter=output_final)

        # =====================================================
        # ✅ Retorno final
        # =====================================================
        return {
            "status": "ok",
            "message": "🎬 Vídeo final gerado e arquivos temporários limpos!",
            "output": output_final,
            "tempo_total_audio": round(duration, 2),
            "tempo_por_imagem": round(tempo_por_img, 2),
            "encoder": encoder,
            "imagens_usadas": len(image_paths),
            "limpeza": "executada" if limpar else "mantida"
        }

    except Exception as e:
        return {"status": "error", "details": str(e)}

# ========================
#    Verifica Status
# ========================
@app.get("/status/{output_name}")
async def verificar_status_video(output_name: str):
    """
    Verifica o status do vídeo renderizado.
    - Se o nome recebido for '_status.json', remove o sufixo automaticamente.
    - Prioriza leitura do arquivo de status JSON.
    - Usa fallback por variação de tamanho se o JSON ainda não existir.
    """
    # Remove o sufixo _status.json, caso o usuário tenha enviado ele diretamente
    base_name = Path(output_name).stem.replace("_status", "")
    video_name = f"{base_name}.mp4"

    output_path = os.path.join(OUTPUT_DIR, video_name)
    status_file = os.path.join(OUTPUT_DIR, f"{base_name}_status.json")

    # Caso ainda não tenha iniciado
    if not os.path.exists(output_path):
        return {
            "status": "⏳ aguardando início",
            "arquivo": video_name,
            "mensagem": "Arquivo ainda não foi criado."
        }

    # Se o JSON de status existe → leitura direta
    if os.path.exists(status_file):
        try:
            with open(status_file, "r") as f:
                data = json.load(f)
            data["arquivo"] = video_name
            data["path"] = output_path
            data["tamanho_mb"] = round(os.path.getsize(output_path) / (1024 * 1024), 2)
            return data
        except Exception as e:
            print(f"[WARN] Falha ao ler status JSON: {e}")

    # Fallback: mede crescimento do arquivo
    tamanhos = []
    for _ in range(3):
        tamanhos.append(os.path.getsize(output_path))
        time.sleep(1)

    if max(tamanhos) != min(tamanhos):
        return {
            "status": "🌀 processando",
            "arquivo": video_name,
            "mensagem": f"Arquivo crescendo ({round(tamanhos[-1] / (1024*1024), 2)} MB)..."
        }

    return {
        "status": "✅ concluído",
        "arquivo": video_name,
        "path": output_path,
        "tamanho_mb": round(tamanhos[-1] / (1024 * 1024), 2)
    }

# ========================
#      Burn Subs
# ========================
@app.post("/ffmpeg_burn_subs")
async def queimar_legenda(
    body: dict = Body(...)
):
    """
    Queima (embed) uma legenda ASS em um vídeo via FFmpeg.
    Executa em background e grava status JSON compatível com /status.
    Exemplo JSON:
    {
      "input": "/workspace/out/teste_final_output.mp4",
      "output": "/workspace/out/teste_final_cinematic.mp4",
      "args": [
        "-vf", "ass=/workspace/subs/VID036_final_cinematic.ass",
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", "18",
        "-c:a", "copy",
        "-movflags", "+faststart"
      ]
    }
    """
    try:
        input_file = body.get("input")
        output_file = body.get("output")
        args = body.get("args", [])

        if not input_file or not output_file:
            return JSONResponse(
                {"error": "Campos obrigatórios: 'input' e 'output'."},
                status_code=400
            )

        if not os.path.exists(input_file):
            return JSONResponse(
                {"error": f"Arquivo de entrada não encontrado: {input_file}"},
                status_code=404
            )

        status_path = os.path.join(
            OUTPUT_DIR, f"{Path(output_file)}_status.json"
        )

        def salvar_status(data: dict):
            """Salva status JSON atualizado."""
            with open(status_path, "w") as f:
                json.dump({**data, "timestamp": time.time()}, f)

        def render_task():
            try:
                salvar_status({"status": "processing", "output": output_file})
                os.makedirs(os.path.dirname(output_file), exist_ok=True)

                cmd = ["ffmpeg", "-y", "-hwaccel", "cuda", "-i", input_file] + args + [output_file]
                print(f"🧩 Executando FFmpeg:\n{' '.join(cmd)}")

                process = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )

                if process.returncode != 0:
                    salvar_status({
                        "status": "error",
                        "message": "Erro ao processar FFmpeg",
                        "details": process.stderr
                    })
                    print(process.stderr)
                    return

                salvar_status({
                    "status": "done",
                    "input": input_file,
                    "output": output_file,
                    "tamanho_mb": round(os.path.getsize(output_file) / (1024 * 1024), 2)
                })
                print(f"✅ Legenda queimada com sucesso: {output_file}")

            except Exception as e:
                salvar_status({"status": "error", "message": str(e)})
                print(f"[ERRO FFMPEG_BURN_SUBS] {e}")

        # Executa em background
        Thread(target=render_task).start()

        return JSONResponse({
            "status": "processing",
            "message": "🔥 Queima de legenda iniciada em segundo plano.",
            "input": input_file,
            "output": output_file,
            "status_path": status_path
        })

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

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
        # Garante que o nome seja seguro e dentro do diretório de saída
        safe_name = os.path.basename(filename)
        file_path = os.path.join(OUTPUT_DIR, safe_name)

        if not os.path.exists(file_path):
            return JSONResponse(
                {"error": f"Arquivo não encontrado: {safe_name}"},
                status_code=404
            )

        return FileResponse(
            path=file_path,
            filename=safe_name,
            media_type="application/octet-stream"
        )

    except Exception as e:
        return JSONResponse(
            {"error": str(e)},
            status_code=500
        )

