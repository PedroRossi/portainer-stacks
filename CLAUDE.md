# CLAUDE.md

Docker Compose stacks, deployed via **Portainer** (or plain `docker compose`): the local-AI stack **`ai-lab/`**,
aimed at NVIDIA **GTX 16xx** cards for now, and **`search/`**, web search and page reading for it.

## `ai-lab/`
Deployed by Portainer from Git (compose path `ai-lab/docker-compose.yaml`). After a push, "Pull and redeploy"
if auto-update hasn't picked it up. A redeploy recreates every container in the stack.
- **Default services:** `rustingstrata` (:8080, RustingStrata serving Qwen3.6-35B-A3B; image built from the
  PedroRossi/RustingStrata fork in `ai-lab/rustingstrata/`), `open-webui` (:11435, wired to rustingstrata),
  `pgvector` (no port), `open-terminal` (:18800, bearer key from a host file).
- **Profile `llamacpp`:** `llama-server` (the llama.cpp router below, :8080). Off by default: only one engine fits on
  the 6 GB GPU. To switch, stop one engine before starting the other, and change Open WebUI's connection URL/Provider.
- **Router:** one model at a time (`--models-max 1`); a request's `model` field picks it, unloading the current one.
  Presets in `ai-lab/llama-server/models.ini`: `qwen3.6-35b-a3b` (loaded at startup), `qwen3.6-35b-a3b-512k`,
  `gemma-4-26b-a4b`. Nothing unloads automatically. Requests must name a model (400 without one).
  The router reads the host copy, `$LLM_HOME/ai-lab/llama-server/models.ini`; `GET /models?reload=1` applies edits.
- **Open WebUI** v0.13.5; its OpenAI connection points at `http://rustingstrata:8080/v1` with the default Provider
  (stored in its database). With `llama-server`, use Provider `llama.cpp`.
- **Downloads** go to the cache (`LLAMA_CACHE=/cache`, host `$LLM_HOME/models/hf-cache`): llama.cpp's web UI
  (Search → "On Hugging Face"; enabled with `--ui-config`), Open WebUI v0.13+ (connection Provider `llama.cpp`:
  model picker Download and a green dot on the loaded model; Admin → Models → Actions → Manage: load/unload/delete), or `POST /models`.
  Web UI deletes leave the vision file: `DELETE /models?model=<id>&sidecar=mmproj` removes it.
- **Presets** are mounted as a folder (`$LLM_HOME/ai-lab/llama-server` → `/config`): a single-file bind mount
  keeps the old inode when an editor or rsync replaces the file. Vision projectors are BF16 (cuBLAS FP16 GEMM is
  ~6x slower than FP32 on GTX 16xx).
- **Profile:** `image` (`comfyui` + `forge`), disabled for now (COMPOSE_PROFILES unset; Open WebUI's image
  generation off, its Forge connection kept). Enable it with `COMPOSE_PROFILES` in Portainer. llama.cpp is the only
  model runner: there's no Ollama service, and Open WebUI's Ollama connection is off.
- **GPU:** on a 6 GB card the loaded model holds 4-5.5 GB. Run the profile services only after unloading it.
- **Image:** `llama-server:<tag>`, from `ai-lab/llama-server/`. That's upstream llama.cpp `51831d47d`,
  CC 7.2 code compiled to sm_75 + `GGML_CUDA_FORCE_MMQ`. Compose builds it only when the tag is
  missing, so bump the tag to rebuild.
- **Host paths:** Portainer CE can't mount repo files, so bind mounts are absolute paths under
  `LLM_HOME` (default `/home/pedro/llm`). `$LLM_HOME/ai-lab` mirrors this folder (including
  `llama-server/models.ini`), plus the data dirs and the secret files (`open-terminal.key`, `pgvector.password`).
- **Volumes:** external `ollama_open-webui` (Open WebUI) and `ollama_open-terminal` (Open Terminal); the stack's own
  `pgvector-data`.
- `picoclaw-config.json` and `chromadb.yaml` are kept for later; nothing mounts them now.
- **RAG** (since 2026-11-27): `VECTOR_DB=pgvector` (`pgvector/pgvector:0.8.7-pg18`, user and database `openwebui`,
  password from `$LLM_HOME/ai-lab/pgvector.password`, uid 999 with the host user's group, mode 640). Open WebUI
  builds `PGVECTOR_DB_URL` from that file in a wrapped entrypoint, since it has no `_FILE` variant.
  - Settings: HNSW index, vector length 384 (fixed when the table is first made), embeddings
    `BAAI/bge-small-en-v1.5`, hybrid search off.
  - Measured against Turso and Chroma; the README has the numbers. Hybrid stays off because pgvector's keyword
    query needs every word to match, so question-like queries find nothing.
  - Chroma was removed: a 0.6.3 server had broken collection creation against Open WebUI's 1.5.9 client.

## `search/`
Deployed by Portainer from Git (compose path `search/docker-compose.yaml`). LAN only: never forward its ports.
- **Services:** `wallcrawler` (:11437: `/fetch`, `/search`, MCP at `/mcp`, Open WebUI's external search and loader
  at `/openwebui/search` and `/openwebui/load`), `searxng` (:11438), `tor` (:9050 SOCKS, :9080 HTTP CONNECT;
  private networks only), `chromium` and `byparr` (no ports).
- **Images:** `wallcrawler:<version>`, `wallcrawler-tor:<version>` and
  `wallcrawler-chromium:<playwright version>-<revision>` are built on the host from the wallcrawler repo
  (`docker build --target app .`, `docker/tor`, `docker/chromium`), with `pull_policy: never`. Bump the tags in the
  compose file after building new ones.
- **Host paths:** `$LLM_HOME/search` mirrors this folder (`searxng/settings.yml`, a read-only single-file mount:
  a replaced copy shows up after a redeploy), plus `searxng.secret` (SearXNG's key; kept out of git and Portainer,
  read by a wrapped entrypoint into `SEARXNG_SECRET`).
- **Open WebUI** (ai-lab) uses it: Web Search Engine `external` → `http://<host>:11437/openwebui/search`, Web
  Loader Engine `external` → `http://<host>:11437/openwebui/load` (in its database, via the admin settings).
- **wallcrawler** waits for the others to start, not to be healthy (it copes without them; Tor's health check
  needs a working circuit).

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
Secrets stay out of git. open-terminal's key is a file on the host (`$LLM_HOME/ai-lab/open-terminal.key`), as
are pgvector's password (`$LLM_HOME/ai-lab/pgvector.password`) and SearXNG's key (`$LLM_HOME/search/searxng.secret`),
and `ai-lab/.env` is git-ignored.
