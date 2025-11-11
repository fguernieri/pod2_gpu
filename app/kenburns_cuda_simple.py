import cv2, os, numpy as np, glob

# === CONFIGURAÇÕES BÁSICAS ===
pattern = "uploads/*.png"      # padrão dos nomes das imagens
out = "output/out.avi"         # vídeo de saída
fps = 30
zoom = 1.05                     # fator final de zoom
frames_per_image = 150          # quantos frames por imagem (duração)

# === PREPARO ===
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

# === LOOP PRINCIPAL ===
gpu_images = []
for f in files:
    img = cv2.imread(f)
    gpu_mat = cv2.cuda_GpuMat()
    gpu_mat.upload(img)
    gpu_images.append(gpu_mat)

for gpu_img in gpu_images:
    for frame in zoom_frames(gpu_img, frames_per_image, start_zoom=1.0, end_zoom=zoom):
        video.write(frame.download())

video.release()
print(f"✅ Vídeo salvo como: {out}")
