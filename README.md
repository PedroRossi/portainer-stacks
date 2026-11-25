# portainer-stacks

Docker Compose stacks, deployed with **Portainer** (Git-backed stacks) or plain `docker compose`.

- **`ai-lab/`**: a local AI stack: llama.cpp serving one model at a time (with downloads from Hugging Face),
  Open WebUI, ChromaDB and Open Terminal, plus Ollama and ComfyUI/Forge behind profiles.
  **This setup is aimed at NVIDIA GTX 16xx cards for now.**

---

## `ai-lab/`

In Portainer, add it as a Git-backed stack with compose path `ai-lab/docker-compose.yaml`. After a push, use
"Pull and redeploy" if auto-update hasn't picked it up. A redeploy recreates all of the stack's containers.

| service | profile | port | what it is |
|---|---|---|---|
| `llama-server` | default | 8080 | llama.cpp router built for GTX 16xx cards: one model at a time; OpenAI/Anthropic API; web UI with a model manager |
| `open-webui` | default | 11435 | chat front end, wired to `llama-server`; downloads, loads, ejects and deletes its models |
| `chromadb` | default | 11436 | vector store for Open WebUI |
| `open-terminal` | default | 18800 | shell/code sandbox for the AI; every request needs its bearer key |
| `ollama` | `ollama` | 11434 | Ollama |
| `comfyui`, `forge` | `image` | 8188, 17860 | image generation |

### Models

The router loads whichever model a request names, unloading the current one first (about 8 s to switch).
The presets in `ai-lab/llama-server/models.ini` are tuned for a 6 GB card with 32 GB of RAM:

| model id | what |
|---|---|
| `qwen3.6-35b-a3b` | Qwen3.6-35B-A3B, Unsloth UD-Q2_K_XL (2.83 bits/weight), vision, 262,144-token window; loaded at startup |
| `qwen3.6-35b-a3b-512k` | the same model with a 524,288-token window (YaRN x2; spills to RAM past ~400K tokens) |
| `gemma-4-26b-a4b` | Gemma 4 26B-A4B, Google's QAT 4-bit (Unsloth UD-Q4_K_XL), vision, 131,072-token window |

Their files go in `$LLM_HOME/models` (the `model` and `mmproj` paths in `models.ini`). Pick a model in
Open WebUI's model list, or send its id as `model` in an API request: every request must name one (the router
answers 400 without it). Nothing unloads on its own: unload it from either web UI, or with
`POST /models/unload`, to free the GPU.

The router reads `$LLM_HOME/ai-lab/llama-server/models.ini` (the host copy). Apply edits without a restart with
`GET /models?reload=1`: a loaded model whose section changed is unloaded, and loads with the new settings on its
next request.

### Downloading models

- **llama.cpp's web UI** (`http://<host>:8080`): open **Search** (Ctrl/⌘+K), type a model name, and pick a
  result under "On Hugging Face". The **Discover** dialog lists the repo's quantizations with their sizes;
  click one to download it (the button shows progress and can cancel). The **Models** page (Ctrl/⌘+M) loads, unloads
  and deletes models. The stack turns these options on with `--ui-config`; llama.cpp ships them off.
- **Open WebUI** (v0.13+, with the connection's Provider set to `llama.cpp` in Admin Panel → Settings →
  Connections): type `<user>/<repo>:<quant>` in the model picker and choose **Download** (progress and cancel).
  Admin Panel → Settings → Models → **Manage Models** shows which model is loaded, with **Eject** and delete.
- **Open WebUI's "Model manager"** (optional): an Open WebUI function, `ai-lab/open-webui/model_manager.py`,
  that adds what the built-in panel lacks: `search gemma 4` (Hugging Face search) and
  `quants unsloth/gemma-4-E4B-it-GGUF` (quantizations, sizes, and whether they fit), plus `pull`, `list`,
  `load`, `unload` and `rm`. Install it in Admin Panel → Functions, and enable it.
- **API**: `POST /models` with `{"model": "<user>/<repo>:<quant>"}`; progress comes on `GET /models/sse`.

Downloads go to `$LLM_HOME/models/hf-cache` and run with the `[*]` defaults from `models.ini`: mixture-of-experts
models keep their experts in RAM (`n-cpu-moe`), and `--fit` sizes the GPU layers and the context. Vision models
come with their projector (`mmproj`): the router picks the file closest in precision to the model, which on
Unsloth repos is the BF16 one, which is also the faster one on these cards (see `models.ini`). To tune a download,
add a section named after its id to `models.ini`.

Deleting a model from either web UI leaves its vision file in the cache (the router keeps sidecar files
unless asked for them by name). The Model manager's `rm` removes both.

### Notes

- **GPU memory:** on a 6 GB card the loaded model holds 4-5.5 GB. Start the `ollama`/`image` services
  only after unloading it. In Portainer, enable profiles with the stack variable `COMPOSE_PROFILES`.
- **The build:** upstream llama.cpp `51831d47d`, no patches, compiled as CC 7.2 code into sm_75
  machine code with `GGML_CUDA_FORCE_MMQ`. On GTX 16xx cards (Turing without tensor cores) this keeps
  fast FP16 and avoids the tensor-core paths, so prompt processing is up to ~3x faster than with the
  default build. The image `llama-server:<tag>` builds from `ai-lab/llama-server/` only when the tag is
  missing, so bump the tag to rebuild.
- **Host paths:** Portainer CE can't bind-mount files from the repo, so every mount is an absolute
  path under `LLM_HOME` (default `/home/pedro/llm`). That covers the models and the download cache,
  the presets folder `ai-lab/llama-server/` (mounted as a folder, so an edited `models.ini` is always seen),
  `ai-lab/open-terminal.key`, and the ComfyUI/Forge data in `ai-lab/`.
- **Data volumes** (external): `ollama_open-webui`, `ollama_open-terminal`, `chromadb`, `ollama`.
- `picoclaw-config.json` and `chromadb.yaml` are kept for later; nothing mounts them now.

Without Portainer:

```bash
cd ai-lab
docker compose config --quiet                       # validate
docker compose up -d                                # the default services
docker compose --profile image up -d comfyui forge  # image generation (unload the model first)
```

---

## GPU / NVIDIA

- The image is built on CUDA 12.4, so the host needs NVIDIA driver 550 or newer, plus
  `nvidia-container-toolkit` with Docker configured for it
  (`sudo nvidia-ctk runtime configure --runtime=docker`, then restart Docker).
- An old `nvidia-container-toolkit` can fail under a newer driver with `nvml error: unknown error`:
  upgrade the toolkit.
- If the GPU locks up (`nvidia-smi` shows `Unknown Error`; the kernel logs
  `RC watchdog: GPU is probably locked`), reset it with `sudo nvidia-smi --gpu-reset -i 0`, or reboot.

## Conventions
- Pinned image tags in the AI stack; services on the same stack talk by container name; host
  ports are published.
- `TZ = America/Recife`.
- See `CLAUDE.md` for agent/operator notes.
