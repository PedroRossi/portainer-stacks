# RustingStrata for GTX 16xx cards, built from the PedroRossi/RustingStrata fork: upstream
# github.com/RustingStudio/RustingStrata plus a CUDA-core path for Turing cards without tensor cores
# (the GTX 16 series still runs tensor-core instructions, but far slower than its CUDA cores).
# The CUDA kernels compile at run time with NVRTC, so the image carries the CUDA 12.4 NVRTC library; the driver
# comes from the NVIDIA container runtime. To update: change RS_COMMIT and bump the image tag in docker-compose.yaml.
ARG RS_REPO=https://github.com/PedroRossi/RustingStrata.git
ARG RS_COMMIT=f71f8575c50f02e24887dd130d17608a9077954c

FROM rust:1-bookworm AS build
ARG RS_REPO
ARG RS_COMMIT
WORKDIR /src
RUN git init -q . && git remote add origin "$RS_REPO" \
 && git fetch -q --depth 1 origin "$RS_COMMIT" && git checkout -q FETCH_HEAD
RUN cargo build --release && strip target/release/rustingstrata

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates wget \
 && wget -q https://developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64/cuda-keyring_1.1-1_all.deb \
 && dpkg -i cuda-keyring_1.1-1_all.deb && rm cuda-keyring_1.1-1_all.deb \
 && apt-get update && apt-get install -y --no-install-recommends cuda-nvrtc-12-4 \
 && apt-get purge -y wget && apt-get autoremove -y && rm -rf /var/lib/apt/lists/* \
 && echo /usr/local/cuda-12.4/targets/x86_64-linux/lib > /etc/ld.so.conf.d/cuda-nvrtc.conf && ldconfig
ENV NVIDIA_VISIBLE_DEVICES=all NVIDIA_DRIVER_CAPABILITIES=compute,utility
COPY --from=build /src/target/release/rustingstrata /usr/local/bin/rustingstrata
ENTRYPOINT ["rustingstrata"]
CMD ["serve", "--help"]
