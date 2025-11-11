# =========================================================
# 🧱 BASE CUDA: imagem oficial NVIDIA com suporte a GPU
# =========================================================
FROM nvidia/cuda:13.0.2-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /workspace

# =========================================================
# ⚙️ DEPENDÊNCIAS DE SISTEMA
# =========================================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-dev \
    ffmpeg \
    git curl \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    fonts-dejavu-core fonts-freefont-ttf \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# =========================================================
# 📦 DEPENDÊNCIAS PYTHON
# =========================================================
COPY requirements.txt /workspace/
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /workspace/requirements.txt

# =========================================================
# 📁 CÓDIGO DA APLICAÇÃO
# =========================================================
COPY . /workspace/
RUN chmod +x /workspace/boot_env.sh

# =========================================================
# 🌎 VARIÁVEIS DE AMBIENTE CUDA
# =========================================================
ENV PYTHONUNBUFFERED=1
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,video,utility

# =========================================================
# 🚀 ENTRYPOINT
# =========================================================
ENTRYPOINT ["/workspace/boot_env.sh"]
