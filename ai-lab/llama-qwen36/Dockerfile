# llama.cpp server for GTX 16xx (TU116/TU117: Turing without tensor cores), CUDA 12.4 (driver 550 compatible)
#  - upstream llama.cpp, no patches
#  - CC 7.2 code compiled straight to sm_75 SASS (no runtime JIT) + GGML_CUDA_FORCE_MMQ:
#    fast FP16 stays on, and no tensor-core path is taken (Volta MMA needs exactly CC 7.0 code, Turing MMA needs 7.5),
#    so FlashAttention runs the FP16 tile kernel and quantized matmuls run the dp4a MMQ kernels
#  - the launcher (serve_qwen36.sh) is baked in; the stack mounts only absolute host paths (models, mode file)
# Build on the host before deploying the stack (it only references the tag):
#   docker build -t llama-qwen36:51831d4 llama-qwen36/
ARG CUDA_VERSION=12.4.1
FROM docker.io/nvidia/cuda:${CUDA_VERSION}-devel-ubuntu22.04 AS build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake git ca-certificates libssl-dev curl \
 && rm -rf /var/lib/apt/lists/*
ARG LLAMA_COMMIT=51831d47d0a47b8a7d07c9ff262ebe4b0a211790
WORKDIR /src
RUN git init -q . && git remote add origin https://github.com/ggml-org/llama.cpp \
 && git fetch -q --depth 1 origin ${LLAMA_COMMIT} && git checkout -q FETCH_HEAD
RUN cmake -B build -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=OFF \
      -DCMAKE_CUDA_FLAGS="-gencode=arch=compute_72,code=sm_75" -DGGML_CUDA_FORCE_MMQ=ON \
      -DGGML_NATIVE=OFF -DGGML_AVX=ON -DGGML_AVX2=ON -DGGML_FMA=ON -DGGML_F16C=ON -DGGML_BMI2=ON \
      -DBUILD_SHARED_LIBS=OFF -DLLAMA_BUILD_TESTS=OFF \
 && cmake --build build -j$(nproc) --target llama-server llama-bench llama-perplexity

FROM docker.io/nvidia/cuda:${CUDA_VERSION}-runtime-ubuntu22.04
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libssl3 curl && rm -rf /var/lib/apt/lists/*
COPY --from=build /src/build/bin/llama-server /src/build/bin/llama-bench /src/build/bin/llama-perplexity /usr/local/bin/
COPY serve_qwen36.sh /usr/local/bin/serve_qwen36.sh
ENV BIN=/usr/local/bin/llama-server
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s CMD curl -sf http://localhost:8080/health || exit 1
ENTRYPOINT ["bash", "/usr/local/bin/serve_qwen36.sh"]
