import os, glob, random
import numpy as np
import cv2
import soundfile as sf

# === CONFIGURAÇÕES ===
pattern = "uploads/*.png"
audio_path = "uploads/audio.mp3"
out = "output/out.avi"
fps = 30
zoom_factor = 1.05
tolerancia = 0.05  # ±5% de margem

# === FUNÇÃO: duração do áudio ===
def get_audio_duration(audio_path):
    """Retorna duração total do áudio em segundos."""
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Áudio não encontrado: {audio_path}")
    data, samplerate = sf.read(audio_path)
    return len(data) / samplerate

# === EFEITOS DE MOVIMENTO ===
def write_frame(video, gpu_frame):
    if gpu_frame is None:
        print("⚠️ Frame inválido ignorado (NoneType)")
        return
    frame_cpu = gpu_frame.download()
    if frame_cpu is None:
        print("⚠️ Frame vazio ignorado (falha no download)")
        return
    if len(frame_cpu.shape) == 2:
        frame_cpu = cv2.cvtColor(frame_cpu, cv2.COLOR_GRAY2BGR)
    video.write(frame_cpu)


def kenburns_zoom_in(gpu_img, frames, start_zoom=1.0, end_zoom=1.05):
    for i in range(frames):
        s = start_zoom + (end_zoom - start_zoom) * (i / (frames - 1))
        dx, dy = w/2 - (w/2)*s, h/2 - (h/2)*s
        M = np.array([[s, 0, dx], [0, s, dy]], np.float32)
        yield cv2.cuda.warpAffine(gpu_img, M, (w, h))

def kenburns_zoom_out(gpu_img, frames):
    for i in range(frames):
        s = zoom_factor - (zoom_factor - 1.0) * (i / (frames - 1))
        dx, dy = w/2 - (w/2)*s, h/2 - (h/2)*s
        M = np.array([[s, 0, dx], [0, s, dy]], np.float32)
        yield cv2.cuda.warpAffine(gpu_img, M, (w, h))

def kenburns_pan(gpu_img, frames):
    direction = random.choice([-1, 1])
    desloc = 60
    for i in range(frames):
        s = 1.0 + (zoom_factor - 1.0) * (i / (frames - 1))
        dx = direction * desloc * (i / (frames - 1))
        dy = 0
        M = np.array([[s, 0, dx], [0, s, dy]], np.float32)
        yield cv2.cuda.warpAffine(gpu_img, M, (w, h))

# === TRANSIÇÕES ===
def crossfade_transition(gpu_a, gpu_b, frames):
    for i in range(frames):
        alpha = i / frames
        blended = cv2.cuda.addWeighted(gpu_a, 1 - alpha, gpu_b, alpha, 0)
        yield blended

def slide_transition(gpu_a, gpu_b, frames):
    """
    Slide lateral 100% estável:
    - Move imagem A -> B de forma contínua
    - Evita ROI fora de faixa e garante preenchimento completo
    """
    cols_total = w * 2
    for i in range(frames):
        offset = int(round((w * i) / frames))
        offset = max(0, min(offset, w))  # deslocamento de 0 até w

        # Cria tela destino do tamanho final
        frame = cv2.cuda_GpuMat(h, w, gpu_a.type())

        # Regiões da imagem A e B
        src_a_x = offset
        src_b_x = offset - w

        # Parte da imagem A ainda visível
        if src_a_x < w:
            width_a = w - src_a_x
            if width_a > 0:
                roi_src_a = gpu_a.colRange(0, width_a)
                roi_dst_a = frame.colRange(src_a_x, src_a_x + width_a)
                roi_src_a.copyTo(roi_dst_a)

        # Parte da imagem B já entrando
        if src_b_x < 0:
            width_b = w + src_b_x
            if width_b > 0:
                roi_src_b = gpu_b.colRange(-src_b_x, -src_b_x + width_b)
                roi_dst_b = frame.colRange(0, width_b)
                roi_src_b.copyTo(roi_dst_b)

        yield frame



def cut_transition(gpu_a, gpu_b, frames):
    for _ in range(frames):
        yield gpu_b

# === INÍCIO DO PROCESSO ===
files = sorted(glob.glob(pattern))
if not files:
    raise ValueError("Nenhuma imagem encontrada.")

audio_duration = get_audio_duration(audio_path)
print(f"🎧 Duração do áudio: {audio_duration:.2f}s")

num_images = len(files)
print(f"🖼️ Total de imagens: {num_images}")

# Frames totais que o vídeo precisa ter
frames_total = int(fps * audio_duration)
frames_por_imagem = frames_total // num_images

# Reserva ~20% do tempo de cada imagem para transições
transition_frames = int(frames_por_imagem * 0.2)
frames_por_imagem = int(frames_por_imagem * (1 - 0.2))
print(f"🎬 {frames_por_imagem} frames por imagem + {transition_frames} frames de transição")

# === PREPARO DO VÍDEO ===
img0 = cv2.imread(files[0])
h, w = img0.shape[:2]
video = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*'MJPG'), fps, (w, h))

# Carrega todas as imagens na GPU
gpu_images = []
for f in files:
    img = cv2.imread(f)
    gpu_mat = cv2.cuda_GpuMat()
    gpu_mat.upload(img)
    gpu_images.append(gpu_mat)

# === LOOP PRINCIPAL ===
for i, gpu_img in enumerate(gpu_images):
    next_img = gpu_images[i + 1] if i + 1 < len(gpu_images) else None

    # Escolhe o efeito de movimento aleatoriamente
    efeito = random.choice(["zoom_in", "zoom_out", "pan"])
    print(f"🎥 Efeito {i+1}: {efeito}")

    if efeito == "zoom_in":
        frames_iter = kenburns_zoom_in(gpu_img, frames_por_imagem)
    elif efeito == "zoom_out":
        frames_iter = kenburns_zoom_out(gpu_img, frames_por_imagem)
    else:
        frames_iter = kenburns_pan(gpu_img, frames_por_imagem)

    for frame in frames_iter:
        write_frame(video, frame)

    # Escolhe a transição aleatória (se houver próxima imagem)
    if next_img is not None:
        transicao = random.choice(["cut", "fade", "slide"])
        print(f"🎞️ Transição {i+1}: {transicao}")

        if transicao == "fade":
            for f in crossfade_transition(gpu_img, next_img, transition_frames):
                write_frame(video, f)
        elif transicao == "slide":
            for f in slide_transition(gpu_img, next_img, transition_frames):
                write_frame(video, f)
        else:
            for f in cut_transition(gpu_img, next_img, transition_frames):
                write_frame(video, f)

video.release()
print(f"✅ Vídeo sincronizado com o áudio ({audio_duration:.2f}s) salvo como: {out}")
