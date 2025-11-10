#!/bin/bash
echo "🚀 Iniciando ambiente..."

# ============================
# ⚙️ Correção de ambiente CUDA
# ============================
export PYTHONHOME="/usr"
export PYTHONPATH="/usr/local/lib/python3.10/dist-packages:/app/app:/app:$PYTHONPATH"
export DEBIAN_FRONTEND=noninteractive
export TZ=Etc/UTC

# ===============================
# 📁 Estrutura e sincronização
# ===============================
mkdir -p /workspace/output /workspace/uploads /workspace/temp
chmod -R 777 /workspace

echo "🔄 Sincronizando /app → /workspace..."
rsync -a --exclude 'output' --exclude 'uploads' /app/ /workspace/

# Verifica se o app existe
if [ ! -d "/workspace/app" ]; then
    echo "❌ Erro: diretório /workspace/app não encontrado."
    exit 1
fi

echo "📂 Estrutura de /workspace/app:"
ls -la /workspace/app

# =======================================
# 🧩 Cria __init__.py se estiver faltando
# =======================================
if [ ! -f /workspace/app/__init__.py ]; then
    echo "⚙️ Criando __init__.py..."
    touch /workspace/app/__init__.py
fi

# ======================================
# 🧠 Verifica dependências críticas
# ======================================
echo ""
echo "🔍 Verificando dependências principais..."
python3 - <<'EOF'
import importlib
deps = ["fastapi", "uvicorn", "moviepy.editor", "torch", "whisper"]
for lib in deps:
    try:
        importlib.import_module(lib)
        print(f"✅ {lib} OK")
    except ImportError:
        print(f"❌ {lib} faltando!")
EOF
echo ""

# ======================================
# 📓 Inicia JupyterLab em background
# ======================================
echo "📓 Iniciando JupyterLab na porta 8888..."
jupyter lab --ip=0.0.0.0 --port=8888 --no-browser --allow-root \
  --ServerApp.token='' \
  --ServerApp.password='' \
  --ServerApp.allow_origin='*' \
  --ServerApp.allow_remote_access=True \
  --ServerApp.root_dir='/workspace' &

# ======================================
# 🚀 Inicialização da API FastAPI
# ======================================
cd /workspace/app
echo "🚀 Iniciando aplicação na porta 8090..."
python3 -m uvicorn main:app --host 0.0.0.0 --port 8090
