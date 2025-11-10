#!/bin/bash
set -e
echo "🔧 Instalando dependências..."
pip install --upgrade pip
pip install -r /workspace/requirements.txt
echo "✅ Setup concluído!"
