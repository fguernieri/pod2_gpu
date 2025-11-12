#!/bin/bash
echo "🚀 Iniciando ambiente..."

# ============================
# ⚙️ Correção de ambiente CUDA
# ============================
export PYTHONHOME="/usr"
export PYTHONPATH="/usr/local/lib/python3.10/dist-packages:/app/app:/app:$PYTHONPATH"
export DEBIAN_FRONTEND=noninteractive
export TZ=Etc/UTC

# ==================================
# 🧠 Reinstala OpenCV CUDA (sempre)
# ==================================
echo "📦 Reinstalando OpenCV CUDA otimizado..."
pip install --no-cache-dir --upgrade \
  https://github.com/cudawarped/opencv-python-cuda-wheels/releases/download/4.13.0.20250811/opencv_contrib_python_rolling-4.13.0.20250811-cp37-abi3-linux_x86_64.whl \
  && echo "✅ OpenCV CUDA instalado com sucesso!" \
  || echo "⚠️ Falha ao instalar OpenCV CUDA (prosseguindo com versão CPU)"

# ==================================
# 🧠 Reinstala Torch GPU
# ==================================
  pip install --no-cache-dir -r /app/requirements-gpu.txt
  

# 🔍 Verifica CUDA ativo
python3 - <<'EOF'
import cv2
print(f"Versão: {cv2.__version__}")
try:
    n = cv2.cuda.getCudaEnabledDeviceCount()
    print(f"🎮 Dispositivos CUDA disponíveis: {n}")
except Exception as e:
    print(f"⚠️ CUDA não detectado: {e}")
EOF

# ===============================
# 📁 Estrutura e sincronização
# ===============================
mkdir -p /workspace/output /workspace/uploads /workspace/temp
chmod -R 777 /workspace

echo "🔄 Sincronizando /app → /workspace..."
rsync -a --exclude 'output' --exclude 'uploads' /app/ /workspace/

if [ ! -d "/workspace/app" ]; then
    echo "❌ Erro: diretório /workspace/app não encontrado."
    exit 1
fi

echo "📂 Estrutura de /workspace/app:"
ls -la /workspace/app

# =======================================
# 🧩 Cria __init__.py se estiver faltando
# =======================================
[ -f /workspace/app/__init__.py ] || touch /workspace/app/__init__.py

# ======================================
# 🧠 Verifica dependências críticas
# ======================================
echo "🔍 Verificando dependências principais..."
python3 - <<'EOF'
import importlib
deps = ["fastapi", "uvicorn", "moviepy.editor", "torch"]
for lib in deps:
    try:
        importlib.import_module(lib)
        print(f"✅ {lib} OK")
    except ImportError:
        print(f"❌ {lib} faltando!")
EOF

# ======================================
# 📓 Inicia JupyterLab em background
# ======================================
echo "📓 Iniciando JupyterLab na porta 8888..."
nohup jupyter lab --ip=0.0.0.0 --port=8888 --no-browser --allow-root \
  --ServerApp.token='' \
  --ServerApp.password='' \
  --ServerApp.allow_origin='*' \
  --ServerApp.allow_remote_access=True \
  --ServerApp.root_dir='/workspace' >/workspace/jupyter.log 2>&1 &

# ======================================
# 🚀 Inicialização da API FastAPI
# ======================================
cd /workspace/app
echo "🚀 Iniciando aplicação na porta 8090..."
exec python3 -m uvicorn main:app --host 0.0.0.0 --port=8090 --reload
