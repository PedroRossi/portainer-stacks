# CLAUDE.md

Docker Compose stacks, deployed via **Portainer** (or plain `docker compose`). One local-AI stack,
**`ai-lab/`**, aimed at NVIDIA **GTX 16xx** cards for now.

## `ai-lab/`
Deployed by Portainer from Git (compose path `ai-lab/docker-compose.yaml`). After a push, "Pull and redeploy"
if auto-update hasn't picked it up. A redeploy recreates every container in the stack.
- **Default services:** `llama-server` (llama.cpp router, :8080), `open-webui` (:11435, wired to llama-server),
  `chromadb` (:11436), `open-terminal` (:18800, bearer key from a host file).
- **Router:** one model at a time (`--models-max 1`); a request's `model` field picks it, unloading the current one.
  Presets in `ai-lab/llama-server/models.ini`: `qwen3.6-35b-a3b` (loaded at startup), `qwen3.6-35b-a3b-512k`,
  `gemma-4-26b-a4b`. Nothing unloads automatically. Requests must name a model (400 without one).
  The router reads the host copy, `$LLM_HOME/ai-lab/llama-server/models.ini`; `GET /models?reload=1` applies edits.
- **Open WebUI** v0.13.5; its OpenAI connection has Provider `llama.cpp` (set once in the UI; stored in its database).
- **Downloads** go to the cache (`LLAMA_CACHE=/cache`, host `$LLM_HOME/models/hf-cache`): llama.cpp's web UI
  (Search → "On Hugging Face"; enabled with `--ui-config`), Open WebUI v0.13+ (connection Provider `llama.cpp`:
  model picker Download, Manage Models with Eject/delete), the optional "Model manager" function
  (`ai-lab/open-webui/model_manager.py`), or `POST /models`. Web UI deletes leave the vision file; the function's `rm` doesn't.
- **Presets** are mounted as a folder (`$LLM_HOME/ai-lab/llama-server` → `/config`): a single-file bind mount
  keeps the old inode when an editor or rsync replaces the file. Vision projectors are BF16 (cuBLAS FP16 GEMM is
  ~6x slower than FP32 on GTX 16xx).
- **Profiles:** `ollama`, and `image` (`comfyui` + `forge`). Enable them with `COMPOSE_PROFILES` in Portainer.
- **GPU:** on a 6 GB card the loaded model holds 4-5.5 GB. Run the profile services only after unloading it.
- **Image:** `llama-server:<tag>`, from `ai-lab/llama-server/`. That's upstream llama.cpp `51831d47d`,
  CC 7.2 code compiled to sm_75 + `GGML_CUDA_FORCE_MMQ`. Compose builds it only when the tag is
  missing, so bump the tag to rebuild.
- **Host paths:** Portainer CE can't mount repo files, so bind mounts are absolute paths under
  `LLM_HOME` (default `/home/pedro/llm`). `$LLM_HOME/ai-lab` mirrors this folder (including
  `llama-server/models.ini`), plus the data dirs and the key file.
- **Volumes** (external): `ollama_open-webui`, `ollama_open-terminal`, `chromadb`, `ollama`.
- `picoclaw-config.json` and `chromadb.yaml` are kept for later; nothing mounts them now.

## Conventions
- Pinned image tags; services on the same stack talk by container name; host ports are published.
- `TZ = America/Recife`.
- Keep this repo free of network details (host names, IP addresses): it's public.

## GPU / NVIDIA
The image is CUDA 12.4: the host needs driver ≥ 550 and `nvidia-container-toolkit` (Docker configured with
`nvidia-ctk runtime configure --runtime=docker`). An old toolkit under a newer driver fails with
`nvml error: unknown error`: upgrade it. A locked GPU (`nvidia-smi` → `Unknown Error`, kernel log
`RC watchdog: GPU is probably locked`) needs root: `sudo nvidia-smi --gpu-reset -i 0` or `sudo reboot`.

## Common commands
```bash
cd ai-lab
docker compose config --quiet                       # validate
docker compose up -d                                # the default services, without Portainer
docker compose --profile image up -d comfyui forge  # image generation (unload the model first)
```
Secrets stay out of git. open-terminal's key is a file on the host (`$LLM_HOME/ai-lab/open-terminal.key`),
and `ai-lab/.env` is git-ignored.
