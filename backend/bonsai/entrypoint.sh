#!/bin/sh
set -e

# Descarga el GGUF solo si no existe (una única vez; persiste en el volumen ./bonsai/models)
MODEL_DIR=/models
GGUF="${BONSAI_GGUF:-Ternary-Bonsai-2-27B-PTQ1_0.gguf}"
HF_REPO="${BONSAI_HF_REPO:-prism-ml/Ternary-Bonsai-2-27B-gguf}"
MODEL_FILE="${MODEL_DIR}/${GGUF}"

if [ ! -s "$MODEL_FILE" ]; then
  echo ">> Descargando ${GGUF} desde ${HF_REPO} (solo la primera vez)..."
  mkdir -p "$MODEL_DIR"
  curl -fL --retry 5 --retry-delay 5 --continue-at - \
    -o "${MODEL_FILE}.part" \
    "https://huggingface.co/${HF_REPO}/resolve/main/${GGUF}"
  mv "${MODEL_FILE}.part" "$MODEL_FILE"
fi

# Perfil del repo oficial Bonsai-demo para Bonsai 2 27B (gen-2, Qwen3.8-27B):
# --jinja activa el template nativo de la familia. El modelo PIENSA por defecto
# (esfuerzo xhigh): para el pipeline de ecuaciones de WISPERTEXT preferimos
# respuestas rápidas, así que BONSAI_THINKING=0 (default) lo apaga con
# --reasoning-budget 0 y usa el muestreo "instruct" del model-card
# (temp 0.7 / top-p 0.80 / presence-penalty 1.5).
# BONSAI_THINKING=1 activa el perfil "thinking" del model-card
# (temp 1.0 / top-p 0.95 / min-p 0.05) y BONSAI_REASONING_BUDGET acota los
# tokens de razonamiento (ej. 768 ~ esfuerzo medio; vacío = sin límite).
set -- llama-server \
  -m "$MODEL_FILE" \
  --host 0.0.0.0 \
  --port 8080 \
  -ngl "${BONSAI_NGL:-99}" \
  -fa on \
  -c "${BONSAI_CTX:-8192}" \
  -np 1 \
  --jinja \
  --alias "${BONSAI_ALIAS:-ternary-bonsai-2-27b}"

if [ "${BONSAI_THINKING:-0}" = "1" ]; then
  set -- "$@" \
    --temp "${BONSAI_TEMP:-1.0}" \
    --top-p 0.95 \
    --top-k 20 \
    --min-p 0.05 \
    --presence-penalty 0 \
    --reasoning-format deepseek
  if [ -n "${BONSAI_REASONING_BUDGET:-}" ]; then
    set -- "$@" --reasoning-budget "$BONSAI_REASONING_BUDGET"
  fi
else
  # --reasoning-format deepseek manda cualquier <think> residual a
  # reasoning_content (content queda limpio para el parser JSON del worker).
  set -- "$@" \
    --temp "${BONSAI_TEMP:-0.7}" \
    --top-p 0.80 \
    --top-k 20 \
    --min-p 0 \
    --presence-penalty 1.5 \
    --reasoning-budget 0 \
    --reasoning-format deepseek \
    --chat-template-kwargs '{"enable_thinking": false}'
fi

if [ -n "${BONSAI_THREADS:-}" ]; then
  set -- "$@" -t "$BONSAI_THREADS"
fi

echo ">> Iniciando: $*"
exec "$@"
