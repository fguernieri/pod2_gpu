# ==========================================
# 🧩 BASE CUDA + CUDNN (para Whisper e Torch)
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
    PYTHONPATH="/usr/local/lib/python3.10/dist-packages:/app/app:/app"

# ==========================================
# 🔧 DEPENDÊNCIAS DO SISTEMA
# ==========================================
RUN apt update && apt install -y \
    python3 python3-pip ffmpeg git curl wget rsync nano jq \
    libsm6 libxext6 libxrender1 libgl1 \
    && rm -rf /var/lib/apt/lists/*

# ==========================================
# 📁 ESTRUTURA DO APP
# ==========================================
WORKDIR /app

# Copia o requirements.txt e instala dependências base (CPU-safe)
COPY requirements.txt /app/requirements.txt

RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /app/requirements.txt && \
    python3 - <<'EOF'
import importlib
for lib in ["fastapi", "uvicorn", "cv2"]:
    try:
        importlib.import_module(lib)
        print(f"✅ {lib} OK")
    except Exception as e:
        print(f"⚠️ Falha ao importar {lib}: {e}")
EOF

# ==========================================
# 📦 COPIA RESTANTE DO PROJETO
# ==========================================
COPY app /app/app
COPY models /app/models
COPY scripts /app/scripts

# Permissões
RUN chmod +x /app/scripts/*.sh || true

# ==========================================
# 🧠 Instala OpenCV CUDA no runtime (RunPod)
# ==========================================
RUN echo '#!/bin/bash\n\
echo "🧠 Verificando OpenCV CUDA..."\n\
if ! python3 -c "import cv2; print(cv2.getBuildInformation())" 2>/dev/null | grep -q CUDA; then\n\
  echo "📦 Instalando OpenCV CUDA..."\n\
  pip install --no-cache-dir https://github.com/cudawarped/opencv-python-cuda-wheels/releases/download/4.13.0.20250811/opencv_contrib_python_rolling-4.13.0.20250811-cp37-abi3-linux_x86_64.whl || echo "⚠️ Falha ao instalar OpenCV CUDA, prosseguindo..."\n\
else\n\
  echo "✅ OpenCV já tem suporte CUDA."\n\
fi\n\
exec \"$@\"' > /usr/local/bin/boot_env.sh && chmod +x /usr/local/bin/boot_env.sh

# ==========================================
# 📦 CONFIGURAÇÃO DE VOLUME PERSISTENTE
# ==========================================
VOLUME ["/workspace"]

# ==========================================
# 🚀 COMANDO PADRÃO
# ==========================================
CMD ["bash", "-c", "${START_CMD:-/app/scripts/boot_env.sh}"]
