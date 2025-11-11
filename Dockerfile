# ==========================================
# 🧩 BASE CUDA + CUDNN (para Whisper, Torch e OpenCV CUDA)
# ==========================================
FROM nvidia/cuda:13.0.2-cudnn-runtime-ubuntu22.04

# ==========================================
# ⚙️ VARIÁVEIS DE AMBIENTE ESSENCIAIS
# ==========================================
ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC \
    PYTHONUNBUFFERED=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    PYTHONHOME="/usr" \
    PYTHONPATH="/usr/local/lib/python3.10/dist-packages:/app/app:/app" \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,video,utility

# ==========================================
# 🔧 DEPENDÊNCIAS DO SISTEMA
# ==========================================
RUN apt update && apt install -y \
    python3 python3-pip git curl wget rsync nano \
    ffmpeg libsm6 libxext6 libgl1 \
    fonts-dejavu-core fonts-freefont-ttf \
    && rm -rf /var/lib/apt/lists/*

# ==========================================
# 📁 ESTRUTURA DO APP
# ==========================================
WORKDIR /app

# Copia e instala dependências Python
COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt && \
    python3 -c "import fastapi, uvicorn, cv2; print('✅ Dependências principais OK')"

# Copia código-fonte e scripts
COPY app ./app
COPY models ./models
COPY scripts ./scripts

# Garante permissão de execução para scripts
RUN chmod +x /app/scripts/*.sh

# ==========================================
# 📦 CONFIGURAÇÃO DE VOLUME PERSISTENTE
# ==========================================
VOLUME ["/workspace"]

# ==========================================
# 🚀 COMANDO PADRÃO
# ==========================================
CMD ["bash", "-c", "${START_CMD:-/app/scripts/boot_env.sh}"]
