# Ternary Bonsai (rama gpu): llama-server del fork PrismML con backend CUDA.
# OJO: el llama.cpp/Ollama estándar NO puede ejecutar estos GGUF ternarios;
# se usa el binario precompilado oficial (Linux x64 + CUDA) del release fijado.
# La imagen base nvidia/cuda:runtime aporta cudart/cublas que libggml-cuda
# necesita (el tarball del fork NO las incluye); el driver lo inyecta el
# runtime nvidia de Docker (ver reservations.devices del compose).
FROM nvidia/cuda:13.3.0-runtime-ubuntu24.04

ARG PRISM_RELEASE=prism-b10754-2459f68
ARG PRISM_ASSET=llama-prism-b10754-2459f68-bin-linux-cuda-13.3-x64.tar.gz

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl libgomp1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/llama
RUN curl -fsSL -o /tmp/llama.tar.gz \
      "https://github.com/PrismML-Eng/llama.cpp/releases/download/${PRISM_RELEASE}/${PRISM_ASSET}" \
 && tar -xzf /tmp/llama.tar.gz -C /opt/llama --strip-components=1 \
 && rm -f /tmp/llama.tar.gz \
 && ln -s "$(find /opt/llama -type f -name llama-server | head -n1)" /usr/local/bin/llama-server

ENV LD_LIBRARY_PATH=/opt/llama/lib:/opt/llama/bin:/opt/llama

# El modelo NO se hornea en la imagen (~5.7 GB el 27B PTQ1_0): lo descarga el
# entrypoint al volumen ./bonsai/models la primera vez que se levanta el contenedor.
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
