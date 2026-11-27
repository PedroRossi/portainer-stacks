# portainer-stacks

Docker Compose stacks, deployed with **Portainer** (Git-backed stacks) or plain `docker compose`.

- **`ai-lab/`**: a local AI stack: llama.cpp serving one model at a time (with downloads from Hugging Face),
  Open WebUI, ChromaDB and Open Terminal, plus ComfyUI/Forge behind a profile.
  **This setup is aimed at NVIDIA GTX 16xx cards for now.**
- **`search/`**: self-hosted web search and page reading for the AI: wallcrawler (search, fetch, MCP, and Open
  WebUI's web search) with SearXNG, Tor, headless Chromium and Byparr.

---

## `ai-lab/`

In Portainer, add it as a Git-backed stack with compose path `ai-lab/docker-compose.yaml`. After a push, use
"Pull and redeploy" if auto-update hasn't picked it up. A redeploy recreates all of the stack's containers.

| service | profile | port | what it is |
|---|---|---|---|
| `llama-server` | default | 8080 | llama.cpp router built for GTX 16xx cards: one model at a time; OpenAI/Anthropic API; web UI with Hugging Face downloads and a Models page |
| `open-webui` | default | 11435 | chat front end, wired to `llama-server`; downloads, loads, ejects and deletes its models |
| `chromadb` | default | 11436 | vector store for Open WebUI |
| `open-terminal` | default | 18800 | shell/code sandbox for the AI; every request needs its bearer key |
| `comfyui`, `forge` | `image` | 8188, 17860 | image generation; disabled for now |

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
  The picker marks the loaded model with a green dot. Admin Panel → Settings → Models → **Actions → Manage** lists
  every model with a loaded/unloaded badge, load, unload and delete buttons, and a field to download by name.
- **API**: `POST /models` with `{"model": "<user>/<repo>:<quant>"}`; progress comes on `GET /models/sse`.

Downloads go to `$LLM_HOME/models/hf-cache` and run with the `[*]` defaults from `models.ini`: mixture-of-experts
models keep their experts in RAM (`n-cpu-moe`), and `--fit` sizes the GPU layers and the context. Vision models
come with their projector (`mmproj`): the router picks the file closest in precision to the model, which on
Unsloth repos is the BF16 one, which is also the faster one on these cards (see `models.ini`). To tune a download,
add a section named after its id to `models.ini`.

Deleting a model from either web UI leaves its vision file in the cache (the router keeps sidecar files
unless asked for them by name). To remove both through the API, delete the sidecar first
(`DELETE /models?model=<id>&sidecar=mmproj`), then the model (`DELETE /models?model=<id>`).

### Notes

- **Image generation is disabled for now:** the `image` profile isn't enabled, and Open WebUI's image generation
  is off. To use it, set `COMPOSE_PROFILES=image` on the stack and turn image generation back on in Open WebUI
  (Admin Panel → Settings → Images; its connection to Forge is kept).
- **GPU memory:** on a 6 GB card the loaded model holds 4-5.5 GB. Start the `image` services
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
- **Data volumes** (external): `ollama_open-webui` (Open WebUI's data), `ollama_open-terminal` (Open Terminal's
  home) and `chromadb`.
- `picoclaw-config.json` and `chromadb.yaml` are kept for later; nothing mounts them now.
- **Chroma's server version follows Open WebUI's client:** Open WebUI v0.13.5 ships chromadb 1.5.9, so the server
  is `chromadb/chroma:1.5.9`. With an older server (0.6.3), creating a collection failed, which broke file uploads,
  knowledge bases and RAG web search. Check the pair when upgrading Open WebUI.

Without Portainer:

```bash
cd ai-lab
docker compose config --quiet                       # validate
docker compose up -d                                # the default services
docker compose --profile image up -d comfyui forge  # image generation (unload the model first)
```

---

## `search/`

In Portainer, add it as a Git-backed stack with compose path `search/docker-compose.yaml`. It serves the LAN:
never forward its ports to the internet.

| service | port | what it is |
|---|---|---|
| `wallcrawler` | 11437 | search and read the web for AI: REST (`/fetch`, `/search`), MCP (`/mcp`), and Open WebUI's external web search and loader (`/openwebui/search`, `/openwebui/load`) |
| `searxng` | 11438 | the metasearch engine behind `/search`, with its own web UI |
| `tor` | 9050, 9080 | a Tor client (SOCKS, HTTP CONNECT) for wallcrawler and the LAN; private networks only |
| `chromium`, `byparr` | none | headless Chromium and Byparr (Cloudflare challenges), used by wallcrawler |

### Before the first deploy

1. Build wallcrawler's images on the host, from the wallcrawler repo (the compose file names these tags, with
   `pull_policy: never`):

   ```bash
   docker build --target app -t wallcrawler:0.4.0 .
   docker build -t wallcrawler-tor:0.4.0 docker/tor
   docker build -t wallcrawler-chromium:1.65.1 docker/chromium
   ```

2. Copy this folder to `$LLM_HOME/search` (Portainer CE can't mount repo files) and add SearXNG's secret key,
   a file kept out of git and Portainer:

   ```bash
   rsync -a search/ "$LLM_HOME/search/"
   head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' > "$LLM_HOME/search/searxng.secret"
   chmod 600 "$LLM_HOME/search/searxng.secret"
   ```

### Using it

- **Open WebUI** (Admin Panel → Settings → Web Search): Web Search Engine `external` with
  `http://<host>:11437/openwebui/search`, and Web Loader Engine `external` with `http://<host>:11437/openwebui/load`.
  The Web Search button and the model's `search_web` and `fetch_url` tools (native function calling) then use
  wallcrawler.
- **Coding tools** over MCP: `http://<host>:11437/mcp`, for example
  `claude mcp add --transport http wallcrawler http://<host>:11437/mcp`. The tools are `search` and `fetch`.
- **SearXNG** answers at `http://<host>:11438` in a browser too. Its settings (`search/searxng/settings.yml`) turn
  on the engines that answer a home connection and turn off those that deny it; edits need a redeploy
  (or `rsync --inplace` and a restart).
- **Tor** for other apps: SOCKS `socks5h://<host>:9050` or an HTTP proxy at `<host>:9080`.

### Notes

- **Images:** after building new wallcrawler images, bump the tags in the compose file and redeploy.
- **Health:** wallcrawler starts once the others have started, not when they're healthy, since it copes without
  any of them. Tor's health check needs a working circuit, which can take a few minutes after a start.
- **Data volumes:** `wallcrawler-data` (the page cache and the per-site memory) and `tor-data` (Tor's state).

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
