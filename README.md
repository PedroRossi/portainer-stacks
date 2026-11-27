# portainer-stacks

Docker Compose stacks, deployed with **Portainer** (Git-backed stacks) or plain `docker compose`.

- **`ai-lab/`**: a local AI stack: RustingStrata serving Qwen3.6-35B-A3B (the llama.cpp router stays available
  behind a profile), Open WebUI with Postgres/pgvector for its documents (RAG), and Open Terminal, plus ComfyUI/Forge
  behind a profile.
  **This setup is aimed at NVIDIA GTX 16xx cards for now.**
- **`search/`**: self-hosted web search and page reading for the AI: wallcrawler (search, fetch, MCP, and Open
  WebUI's web search) with SearXNG, Tor, headless Chromium and Byparr.

---

## `ai-lab/`

In Portainer, add it as a Git-backed stack with compose path `ai-lab/docker-compose.yaml`. After a push, use
"Pull and redeploy" if auto-update hasn't picked it up. A redeploy recreates all of the stack's containers.

| service | profile | port | what it is |
|---|---|---|---|
| `rustingstrata` | default | 8080 | RustingStrata serving Qwen3.6-35B-A3B (262K window, vision); OpenAI/Anthropic API |
| `llama-server` | `llamacpp` | 8080 | llama.cpp router built for GTX 16xx cards: one model at a time; OpenAI/Anthropic API; web UI with Hugging Face downloads and a Models page. Off by default: only one engine fits on the GPU |
| `open-webui` | default | 11435 | chat front end, wired to `rustingstrata` |
| `pgvector` | default | none | Postgres 18 with pgvector: Open WebUI's vector store (documents, knowledge bases, web search results) |
| `open-terminal` | default | 18800 | shell/code sandbox for the AI; every request needs its bearer key |
| `comfyui`, `forge` | `image` | 8188, 17860 | image generation; disabled for now |

### Default engine: RustingStrata

[RustingStrata](https://github.com/RustingStudio/RustingStrata) is a Rust engine for mixture-of-experts GGUFs.
- Experts that don't fit in VRAM run on the CPU *at the same time* as the GPU work, where llama.cpp makes them take turns.
- An expert cache fills the spare VRAM with the most-used experts.

The image builds from the [PedroRossi/RustingStrata](https://github.com/PedroRossi/RustingStrata) fork. It adds a
CUDA-core path for Turing cards without tensor cores: the GTX 16 series runs tensor-core instructions, but far slower
than its CUDA cores.

Measured on a GTX 1660 SUPER with 32 GB of RAM, on Qwen3.6-35B-A3B UD-Q2_K_XL and the same real text, with the GPU
clocks locked at 1200 MHz:

| | prefill, ~4K / ~16K prompt | decode after it |
|---|---|---|
| llama.cpp router (this stack's `qwen3.6-35b-a3b` preset) | 365 / 328 tok/s | 28.5 / 24.8 tok/s |
| RustingStrata, 262K window + q4 KV + vision (this service) | 201 / 160 tok/s | 45.1 / 38.7 tok/s |

- **The trade-off:** replies come about 55-60% faster, and long prompts are read about half as fast. In chat and
  coding sessions most of a prompt is cached, so the faster replies dominate.
- **Images:** they work, but take about 4.5x longer than on llama.cpp (27 s and 61 s for the two test images).
- **APIs:** the OpenAI API returns the reasoning in `reasoning_content`. On the Anthropic API the reasoning
  currently comes inside the text block, with a literal `</think>` before the answer.
- **Access:** the API only answers requests whose Host is localhost or a listed name.
  - Open WebUI's `rustingstrata` is listed by default.
  - To reach it by IP address or host name, set the Portainer stack variable `STRATA_ALLOWED_HOSTS` to
    `rustingstrata,<address>,<name>`.
- **Data:** compiled kernels, the expert profile and the calibration file live in `$LLM_HOME/ai-lab/rustingstrata-data`.
- **Switching back to llama.cpp:**
  1. Stop `rustingstrata`, then set the stack variable `COMPOSE_PROFILES=llamacpp`.
  2. In Open WebUI (Admin Panel → Settings → Connections), set the URL to `http://llama-server:8080/v1` and the
     Provider to `llama.cpp`.

### Models (llama.cpp router, profile `llamacpp`)

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

### RAG: documents and knowledge bases

Open WebUI keeps its vectors in `pgvector` (Postgres 18 with pgvector 0.8.7), embeds on the CPU with
`BAAI/bge-small-en-v1.5`, and has hybrid search off. Before the first deploy, create the database password: a host
file kept out of git and Portainer, which both containers read.

```bash
head -c 64 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32 > "$LLM_HOME/ai-lab/pgvector.password"
chmod 640 "$LLM_HOME/ai-lab/pgvector.password"
sudo chown 999:"$(id -g)" "$LLM_HOME/ai-lab/pgvector.password"   # uid 999 is Postgres in its image
```

The vector length (384) is fixed when the table is first made. A model with another length needs
`PGVECTOR_INITIALIZE_MAX_VECTOR_LENGTH` changed and the table emptied, and then knowledge bases re-indexed.

**Why these choices.** Measured on this setup on 2026-11-27 with BEIR SciFact (5,183 scientific abstracts, 300
questions with known answers). The questions searched one knowledge base inside a table of 30,840 chunks, since
Open WebUI keeps every knowledge base in one table. pgvector ran through Open WebUI's own code; Turso ran the
queries a Turso backend would make (Open WebUI has none).

| | pgvector, as Open WebUI ships it | Turso (pyturso 0.8.4) |
|---|---|---|
| Vector search, nDCG@10 | 0.720 (99% of the exact top 10), 6 ms | 0.720 (exact search), 14 ms |
| Keyword search, nDCG@10 | 0.013: 296 of 300 questions found nothing | 0.658 (Tantivy BM25), 3 ms |
| Hybrid search, nDCG@10 | 0.722, right answers in the top 10: 84.5% | 0.725, 86.5% |
| Right answers in a reranker's top 30 | 90.3% | 93.9% |

- **Hybrid search is off** because, with pgvector, its keyword half finds nothing for question-like queries:
  Open WebUI's query needs every word to match. Matching any word with English stemming did no better (0.325 alone,
  and it pulled hybrid down to 0.645). Open WebUI's in-process BM25, which Chroma and Qdrant get, scored 0.518 and
  also pulled hybrid below vector search alone (0.678).
- **pgvector over Turso:** Turso comes out ahead only through its keyword search, and only by a little. To use it,
  we'd build and maintain an Open WebUI backend on a pre-1.0 database. Its exact search slows as knowledge bases grow
  (about 110 ms per 100,000 chunks here). Its experimental full-text search showed two bugs: `fts_score` is 0 when the
  query is a bound parameter, and wrong when the same query also filters another column.
- **pgvector over Chroma:** pgvector's backend is maintained by Open WebUI's core team and searches inside the
  database. Chroma needed its server pinned to Open WebUI's client: a 0.6.3 server failed to create collections
  against the 1.5.9 client. It was replaced on 2026-11-27.
- **Embedding model** (same questions, exact search, 8 CPU threads): Open WebUI's default `all-MiniLM-L6-v2` scored
  0.645 at 47 chunks/s; `bge-small-en-v1.5` scored 0.720 at 17 chunks/s. The embedding model, not the database,
  limits how fast documents go in.

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
  `ai-lab/open-terminal.key`, `ai-lab/pgvector.password`, and the ComfyUI/Forge data in `ai-lab/`.
- **Data volumes:** `ollama_open-webui` (Open WebUI's data) and `ollama_open-terminal` (Open Terminal's home) are
  external; `pgvector-data` (the vectors) is the stack's own.
- `picoclaw-config.json` and `chromadb.yaml` are kept for later; nothing mounts them now.

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
   docker build --target app -t wallcrawler:0.6.1 .
   docker build -t wallcrawler-tor:0.6.1 docker/tor
   docker build -t wallcrawler-chromium:1.65.1-2 docker/chromium
   ```

2. Copy this folder to `$LLM_HOME/search` (Portainer CE can't mount repo files) and add SearXNG's secret key,
   a file kept out of git and Portainer:

   ```bash
   rsync -a search/ "$LLM_HOME/search/"
   head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' > "$LLM_HOME/search/searxng.secret"
   chmod 600 "$LLM_HOME/search/searxng.secret"
   ```

### Using it

- **Open WebUI** (Admin Panel → Settings → Web Search):
  - Web Search Engine `external`, with `http://<host>:11437/openwebui/search`;
  - Web Loader Engine `external`, with `http://<host>:11437/openwebui/load`;
  - Web Fetch Max Content Length `20000`, since the loader hands over whole pages.

  The Web Search button and the model's `search_web` and `fetch_url` tools (native function calling) then use
  wallcrawler. A page attached with `#` and a link is read through it too. Unless the model has File Context on, the
  model reads that page only through `fetch_url`.
- **A Researcher model** in Open WebUI:
  - add `http://<host>:11437/mcp` as an MCP server in Admin Panel → Settings → External Tools;
  - create a model on Qwen with the wallcrawler tools, File Context on and Web Search off.

  wallcrawler's README has the steps and its system prompt.
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
- **Data volumes:** `wallcrawler-data` (the page cache and the per-site memory, in SQLite) and `tor-data` (Tor's
  state). wallcrawler can keep that memory in Postgres or Turso instead (`WALLCRAWLER_DATABASE_URL`); the stack
  stays on SQLite.

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
