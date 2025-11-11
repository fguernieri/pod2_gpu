# /workspace/app/main.py

import os, glob
import numpy as np
import cv2
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

# Inicializa a API
app = FastAPI(title="Ken Burns GPU API", version="1.0")

# === Função principal ===
def generate_video(pattern: str, out: str, fps: int, zoom: float, frames_per_image: int):
    # Busca arquivos
    files = sorted(glob.glob(pattern))
    if not files:
        raise ValueError("Nenhuma imagem encontrada com o padrão informado.")

    img0 = cv2.imread(files[0])
    h, w = img0.shape[:2]
    video = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*'MJPG'), fps, (w, h))

    def zoom_frames(gpu_img, frames=60, start_zoom=1.0, end_zoom=1.1):
        """Gera frames com zoom progressivo de start_zoom → end_zoom."""
        for i in range(frames):
            s = start_zoom + (end_zoom - start_zoom) * (i / (frames - 1))
            dx, dy = w/2 - (w/2)*s, h/2 - (h/2)*s
            M = np.array([[s, 0, dx],
                          [0, s, dy]], np.float32)
            gpu_dst = cv2.cuda.warpAffine(gpu_img, M, (w, h))
            yield gpu_dst

    # Carrega imagens na GPU
    gpu_images = []
    for f in files:
        img = cv2.imread(f)
        gpu_mat = cv2.cuda_GpuMat()
        gpu_mat.upload(img)
        gpu_images.append(gpu_mat)

    # Gera frames de cada imagem
    for gpu_img in gpu_images:
        for frame in zoom_frames(gpu_img, frames_per_image, start_zoom=1.0, end_zoom=zoom):
            video.write(frame.download())

    video.release()


# === ENDPOINT HTTP ===
@app.post("/render")
def render_video(
    pattern: str = Query("uploads/*.png", description="Padrão de arquivos (glob)"),
    out: str = Query("output/out.avi", description="Caminho do vídeo de saída"),
    fps: int = Query(30, description="Frames por segundo"),
    zoom: float = Query(1.05, description="Fator final de zoom (ex: 1.1 = +10%)"),
    frames_per_image: int = Query(150, description="Duração de cada imagem em frames")
):
    """
    Renderiza um vídeo com efeito Ken Burns (zoom suave) usando GPU CUDA.
    """
    try:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        generate_video(pattern, out, fps, zoom, frames_per_image)
        return JSONResponse({"status": "ok", "output": out})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)})


@app.get("/")
def root():
    return {"message": "Ken Burns GPU API ativa 🚀. Use POST /render para gerar vídeos."}
