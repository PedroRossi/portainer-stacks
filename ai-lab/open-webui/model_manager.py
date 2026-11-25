"""
title: Model manager
description: Download, load, unload and delete models on the stack's llama.cpp router (llama-server). Pick "Model manager" in the model list and type a command; "help" lists them.
version: 1.0.0
required_open_webui_version: 0.6.0
"""

# Open WebUI "pipe" function: it shows up as a model named "Model manager". Each message is a command,
# run directly (no LLM). Install: Admin Panel > Functions > + (paste this file) > enable it.

import asyncio
import json
import re
import time

import aiohttp
from pydantic import BaseModel, Field

HF = "https://huggingface.co"
SPLIT = re.compile(r"-\d{5}-of-\d{5}$")
# Files that ride along with a model, not models: vision projectors and speculative-decoding draft heads
SIDECAR = re.compile(r"(?i)mmproj|(?:^|[-_/])(?:mtp|dflash|eagle3?|dspark|draft)(?:[-_./]|$)")
QUANT = re.compile(
    r"(?i)(?:^|[-_.])((?:UD-)?(?:I?Q[1-8](?:_[0-9A-Z]+)*|BF16|F16|F32|MXFP4(?:_MOE)?|TQ[12]_0))$"
)

HELP = """**Model manager**: one command per message.

| command | what it does |
|---|---|
| `list` | the models on the server, and which one is loaded |
| `search <words>` | find GGUF models on Hugging Face, e.g. `search gemma 4` |
| `quants <user>/<repo>` | a repo's quantizations, with sizes and whether they fit |
| `pull <user>/<repo>:<quant>` | download, e.g. `pull unsloth/gemma-4-E4B-it-GGUF:Q8_0` (a Hugging Face link works too) |
| `load <model>` | load a model now (the current one is unloaded first) |
| `unload` | unload the current model and free the GPU |
| `rm <model>` | delete a downloaded model; also cancels a download |

To chat with a model, pick it in the model list: it loads on the first message. New downloads appear
in the list after a page refresh. Stopping this message doesn't stop a download; `rm` cancels it."""


def quant_of(filename):
    stem = re.sub(r"(?i)\.gguf$", "", filename.rsplit("/", 1)[-1])
    m = QUANT.search(SPLIT.sub("", stem))
    return m.group(1).upper() if m else None


def parse_ref(text):
    """'user/repo:QUANT', 'hf.co/user/repo:QUANT' or a huggingface.co URL -> (repo, QUANT or None)."""
    s = text.strip().strip("`'\"<>")
    s = re.sub(r"^(?:https?://)?(?:www\.)?(?:huggingface\.co|hf\.co)/", "", s)
    s = s.split("?")[0].split("#")[0]
    quant = None
    if ":" in s:
        s, quant = s.rsplit(":", 1)
    parts = [p for p in s.split("/") if p]
    if len(parts) < 2 or " " in s:
        return None, None
    if not quant and parts[-1].lower().endswith(".gguf"):
        quant = quant_of(parts[-1])
    return f"{parts[0]}/{parts[1]}", (quant.upper() if quant else None)


def gb(n):
    return f"{n / 1e9:.1f} GB"


class Pipe:
    class Valves(BaseModel):
        LLAMA_URL: str = Field(default="http://llama-server:8080", description="The llama.cpp router, as Open WebUI reaches it")
        GPU_GB: float = Field(default=6, description="GPU memory, for the size hints")
        RAM_GB: float = Field(default=32, description="System RAM, for the size hints")

    def __init__(self):
        self.valves = self.Valves()

    async def pipe(self, body: dict, __event_emitter__=None, __task__=None):
        if __task__:  # Open WebUI's background tasks (chat title, tags, follow-ups): no model behind this pipe
            task = str(getattr(__task__, "value", __task__))
            if "title" in task:
                return '{"title": "Model manager"}'
            if "tags" in task:
                return '{"tags": []}'
            if "follow" in task:
                return '{"follow_ups": []}'
            return ""

        async def emit(description, done=False):
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": description, "done": done}})

        text = self._last_user_text(body)
        cmd, _, arg = text.partition(" ")
        cmd, arg = cmd.lower().strip(), arg.strip()
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as s:
                if cmd in ("", "help", "?", "/help"):
                    return HELP
                if cmd in ("list", "ls", "models"):
                    return await self.list(s)
                if cmd == "search":
                    return await self.search(s, arg)
                if cmd in ("quants", "files"):
                    return await self.quants(s, arg)
                if cmd in ("pull", "download"):
                    return await self.pull(s, emit, arg)
                if cmd == "load":
                    return await self.load(s, emit, arg)
                if cmd == "unload":
                    return await self.unload(s, arg)
                if cmd in ("rm", "delete", "remove", "cancel"):
                    return await self.rm(s, arg)
                repo, quant = parse_ref(text)  # a pasted "user/repo:quant" or Hugging Face link
                if repo:
                    return await (self.pull(s, emit, text) if quant else self.quants(s, text))
                return f"Unknown command `{cmd}`.\n\n{HELP}"
        except aiohttp.ClientConnectorError as e:
            return f"Can't reach llama-server at {self.valves.LLAMA_URL}: {e}"
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"

    # ---- helpers ----
    @staticmethod
    def _last_user_text(body):
        for m in reversed(body.get("messages") or []):
            if m.get("role") == "user":
                c = m.get("content", "")
                if isinstance(c, list):
                    c = " ".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
                return str(c).strip()
        return ""

    @property
    def url(self):
        return self.valves.LLAMA_URL.rstrip("/")

    def _fit(self, size):
        if size <= (self.valves.GPU_GB - 1) * 1e9:
            return "fits on the GPU"
        if size <= self.valves.RAM_GB * 0.75 * 1e9:
            return "GPU + RAM"
        return "too big for this RAM"

    @staticmethod
    async def _error(r):
        try:
            d = await r.json(content_type=None)
            return (d.get("error") or {}).get("message") or json.dumps(d)[:300]
        except Exception:
            return (await r.text())[:300]

    async def _models(self, s):
        async with s.get(f"{self.url}/models") as r:
            r.raise_for_status()
            return (await r.json())["data"]

    async def _entry(self, s, mid):
        return next((m for m in await self._models(s) if m["id"] == mid), None)

    async def _status(self, s, mid):
        m = await self._entry(s, mid)
        return (m.get("status") or {}).get("value") if m else None

    # ---- commands ----
    async def list(self, s):
        names = {"loaded": "**loaded**", "unloaded": "ready", "loading": "loading", "downloading": "downloading",
                 "incomplete": "incomplete (`pull` it again to resume)"}
        rows = []
        for m in sorted(await self._models(s), key=lambda m: (m.get("source") != "preset", m["id"].lower())):
            st = m.get("status") or {}
            state = names.get(st.get("value"), st.get("value", "?")) + (" (last load failed)" if st.get("failed") else "")
            inputs = ", ".join((m.get("architecture") or {}).get("input_modalities") or ["text"])
            source = "preset" if m.get("source") == "preset" else "download"
            rows.append(f"| `{m['id']}` | {source} | {state} | {inputs} |")
        return ("| model | from | state | inputs |\n|---|---|---|---|\n" + "\n".join(rows)
                + "\n\nPick a model in the model list to chat with it; `unload` frees the GPU.")

    async def search(self, s, words):
        if not words:
            return "Usage: `search <words>`, e.g. `search gemma 4`."
        found = []
        for q in dict.fromkeys([words, words.replace(" ", "-")]):
            params = {"search": q, "filter": "gguf", "sort": "downloads", "direction": "-1", "limit": "15"}
            async with s.get(f"{HF}/api/models", params=params) as r:
                r.raise_for_status()
                found = await r.json()
            if found:
                break
        if not found:
            return f"No GGUF repos on Hugging Face match `{words}`."
        rows = "\n".join(f"| `{m['id']}` | {m.get('downloads', 0):,} | {m.get('likes', 0):,} |" for m in found)
        return (f"GGUF repos matching `{words}`, most downloaded first:\n\n| repo | downloads | likes |\n|---|---|---|\n"
                f"{rows}\n\nNext: `quants <repo>` lists a repo's quantizations and sizes.")

    async def _quants(self, s, repo):
        async with s.get(f"{HF}/api/models/{repo}", params={"blobs": "true"}) as r:
            if r.status in (401, 403, 404):
                return None, None
            r.raise_for_status()
            info = await r.json()
        groups, mmproj = {}, {}
        for f in info.get("siblings") or []:
            name = f.get("rfilename", "")
            if not name.lower().endswith(".gguf"):
                continue
            size = f.get("size") or (f.get("lfs") or {}).get("size") or 0
            base = name.rsplit("/", 1)[-1]
            if SIDECAR.search(name):
                if "mmproj" in base.lower():
                    mmproj[base] = size
                continue
            q = quant_of(base)
            if q:
                groups[q] = groups.get(q, 0) + size
        return groups, mmproj

    async def quants(self, s, arg, ask=False):
        repo, _ = parse_ref(arg)
        if not repo:
            return "Usage: `quants <user>/<repo>`, e.g. `quants unsloth/gemma-4-E4B-it-GGUF`."
        groups, mmproj = await self._quants(s, repo)
        if groups is None:
            return f"Hugging Face has no public repo `{repo}` (gated and private repos need a token, which isn't set up)."
        if not groups:
            return f"`{repo}` has no GGUF files with a recognizable quantization."
        half = [v for k, v in mmproj.items() if "f16" in k.lower()]
        vision = min(half or mmproj.values()) if mmproj else 0
        rows = "\n".join(f"| `{q}` | {gb(size)} | {self._fit(size + vision)} | `pull {repo}:{q}` |"
                         for q, size in sorted(groups.items(), key=lambda kv: kv[1]))
        note = (f"\n\nIt has a vision projector (mmproj, about {gb(vision)}), downloaded with the model." if mmproj else "")
        head = f"Which quantization of `{repo}`?" if ask else f"Quantizations in `{repo}`:"
        return (f"{head}\n\n| quant | size | here | download with |\n|---|---|---|---|\n{rows}{note}\n\n"
                f"Size hints assume {self.valves.GPU_GB:g} GB of GPU memory and {self.valves.RAM_GB:g} GB of RAM. "
                "Mixture-of-experts models stay fast with their experts in RAM; dense models slow down once they spill.")

    async def pull(self, s, emit, arg):
        repo, quant = parse_ref(arg)
        if not repo:
            return "Usage: `pull <user>/<repo>:<quant>`, e.g. `pull unsloth/gemma-4-E4B-it-GGUF:Q8_0`."
        if not quant:
            return await self.quants(s, repo, ask=True)
        mid = f"{repo}:{quant}"
        before = await self._status(s, mid)
        async with s.post(f"{self.url}/models", json={"model": mid}) as r:
            if r.status != 200:
                return f"llama-server won't download `{mid}`: {await self._error(r)}\n\nCheck the name with `quants {repo}`."
        if before in ("unloaded", "loaded", "loading"):
            await asyncio.sleep(2)
            if await self._status(s, mid) != "downloading":
                return f"`{mid}` is already downloaded: pick it in the model list."
        await emit(f"Downloading {mid}")
        t0 = time.time()
        result, total = await self._follow(s, emit, mid)
        minutes = (time.time() - t0) / 60
        if result.startswith("failed"):
            await emit(f"Download of {mid} failed", done=True)
            return f"The download of `{mid}` failed: {result[8:]}"
        if result == "incomplete":
            await emit(f"Download of {mid} stopped", done=True)
            return f"The download of `{mid}` stopped before finishing; `pull {mid}` resumes it."
        m = await self._entry(s, mid) or {}
        inputs = ", ".join((m.get("architecture") or {}).get("input_modalities") or ["text"])
        await emit(f"Downloaded {mid}", done=True)
        size = f" ({gb(total)})" if total else ""
        return (f"Downloaded `{mid}`{size} in {minutes:.1f} min. Inputs: {inputs}.\n\n"
                "Refresh the page, then pick it in the model list. It runs with the stack's shared settings "
                "(`[*]` in `models.ini`); add a section for it there to tune it.")

    async def _follow(self, s, emit, mid):
        """Follow the router's event stream until mid's download ends: ('finished'|'incomplete'|'failed: ...', bytes)."""
        total, shown, last = 0, 0.0, time.time()
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=15)
        while True:
            try:
                async with s.get(f"{self.url}/models/sse", timeout=timeout) as sse:
                    async for raw in sse.content:
                        line = raw.decode(errors="replace").strip()
                        ev = {}
                        if line.startswith("data:"):
                            try:
                                ev = json.loads(line[5:])
                            except ValueError:
                                pass
                        if ev.get("model") == mid:
                            last = time.time()
                            kind = ev.get("event")
                            if kind == "download_progress":
                                files = ((ev.get("data") or {}).get("progress") or {}).values()
                                done = sum(f.get("done", 0) for f in files)
                                total = max(total, sum(f.get("total", 0) for f in files))
                                if total and time.time() - shown >= 2:
                                    await emit(f"Downloading {mid}: {done / 1e9:.2f} of {total / 1e9:.2f} GB ({100 * done / total:.0f}%)")
                                    shown = time.time()
                            elif kind == "download_finished":
                                return "finished", total
                            elif kind == "download_failed":
                                return "failed: " + json.dumps(ev.get("data"))[:300], total
                        if time.time() - last > 20:
                            break  # quiet for a while: check the status below
            except (asyncio.TimeoutError, aiohttp.ClientPayloadError, aiohttp.ServerDisconnectedError):
                pass
            st = await self._status(s, mid)
            if st != "downloading":
                return ("incomplete" if st == "incomplete" else "finished"), total
            last = time.time()

    async def load(self, s, emit, arg):
        mid = arg.strip("` ")
        if not mid:
            return "Usage: `load <model>` (see `list`)."
        if not await self._entry(s, mid):
            return f"There's no model `{mid}` on the server; see `list`."
        async with s.post(f"{self.url}/models/load", json={"model": mid}) as r:
            if r.status != 200:
                return f"Couldn't load `{mid}`: {await self._error(r)}"
        t0, seen = time.time(), False
        while time.time() - t0 < 900:
            st = await self._status(s, mid)
            if st == "loaded":
                await emit(f"Loaded {mid}", done=True)
                return f"`{mid}` is loaded ({time.time() - t0:.0f} s). Pick it in the model list to chat with it."
            if st == "loading":
                seen = True
            elif st == "unloaded" and seen:
                await emit(f"{mid} failed to load", done=True)
                return f"`{mid}` failed to load; the server log has the reason (`docker logs llama-server`)."
            await emit(f"Loading {mid} ({time.time() - t0:.0f} s)")
            await asyncio.sleep(2)
        return f"`{mid}` still isn't loaded after 15 minutes; check the server log."

    async def unload(self, s, arg):
        if arg:
            targets = [arg.strip("` ")]
        else:
            targets = [m["id"] for m in await self._models(s) if (m.get("status") or {}).get("value") in ("loaded", "loading")]
        if not targets:
            return "Nothing is loaded; the GPU is free."
        for mid in targets:
            async with s.post(f"{self.url}/models/unload", json={"model": mid}) as r:
                if r.status != 200:
                    return f"Couldn't unload `{mid}`: {await self._error(r)}"
        return "Unloaded " + ", ".join(f"`{t}`" for t in targets) + ". The GPU is free until a chat message loads a model."

    async def rm(self, s, arg):
        mid = arg.strip("` ")
        if not mid:
            return "Usage: `rm <model>` (see `list`)."
        models = await self._models(s)
        m = next((x for x in models if x["id"] == mid), None)
        if not m:
            return f"There's no model `{mid}` on the server; see `list`."
        if m.get("source") == "preset" or m.get("can_remove") is False:
            return f"`{mid}` is a preset from `models.ini`, not a download: remove its section there instead."
        st = (m.get("status") or {}).get("value")
        if st in ("loaded", "loading"):
            async with s.post(f"{self.url}/models/unload", json={"model": mid}):
                pass
            await asyncio.sleep(2)
        sidecars = m.get("sidecars") or []
        repo = mid.split(":")[0]
        sharing = [x["id"] for x in models if x["id"] != mid and x["id"].split(":")[0] == repo]
        if sidecars and not sharing:  # the router keeps sidecar files unless asked
            for kind in sidecars:
                async with s.delete(f"{self.url}/models", params={"model": mid, "sidecar": kind}):
                    pass
        async with s.delete(f"{self.url}/models", params={"model": mid}) as r:
            if r.status != 200:
                return f"Couldn't delete `{mid}`: {await self._error(r)}"
        what = "Cancelled the download of" if st in ("downloading", "incomplete") else "Deleted"
        extra = ""
        if sidecars:
            extra = (" and its vision file" if not sharing
                     else f"; kept its vision file, which {', '.join(f'`{x}`' for x in sharing)} also uses")
        return f"{what} `{mid}`{extra}."
