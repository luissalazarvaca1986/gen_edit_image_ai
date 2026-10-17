# Etapa 1: compila stable-diffusion.cpp con CUDA (GTX 1650 = sm_75)
FROM nvidia/cuda:12.6.3-devel-ubuntu24.04 AS build
ARG SD_REF=master-973-f0aac52
ARG CUDA_ARCH=75
ARG EXTRA_CMAKE=
RUN apt-get update && apt-get install -y --no-install-recommends git cmake build-essential ca-certificates && rm -rf /var/lib/apt/lists/*
RUN git clone --recursive https://github.com/leejet/stable-diffusion.cpp /src && cd /src && git checkout ${SD_REF} && git submodule update --init --recursive
WORKDIR /src
RUN cmake -B build -DCMAKE_BUILD_TYPE=Release -DSD_CUDA=ON -DGGML_STATIC=ON -DGGML_CUDA_NCCL=OFF -DBUILD_SHARED_LIBS=OFF \
      -DCMAKE_CUDA_ARCHITECTURES="${CUDA_ARCH}" ${EXTRA_CMAKE} \
 && cmake --build build --config Release -j$(nproc)
RUN mkdir -p /out && find build -type f -name 'sd-cli' -exec cp {} /out/ \; && find build -type f -name 'sd-server' -exec cp {} /out/ \; ; ls -la /out

# Etapa 2: API FastAPI. sd-cli es autocontenido, solo necesita libcuda (la inyecta el runtime nvidia)
FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv libgomp1 ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /venv
ENV PATH=/venv/bin:$PATH PYTHONUNBUFFERED=1 SD_CLI=/usr/local/bin/sd-cli
COPY --from=build /out/sd-cli /usr/local/bin/sd-cli
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
