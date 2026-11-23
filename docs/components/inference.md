# Inference

Local model serving: the engine's client, its health check, and a dashboard for the models loaded into memory.

```bash
aegis add inference                   # Ollama on the host (the default)
aegis add inference[docker]           # Ollama as a container in the compose stack
aegis add inference[llamacpp]         # llama.cpp's llama-server on the host
aegis add inference[llamacpp,docker]  # llama-server as a container
```

The AI service's local provider of the same name pulls the component in, so `aegis init --services "ai[ollama]"` (or `ai[llamacpp]`) gets it without asking; a local provider needs the engine of its name. It also stands alone: a model server with no AI service still gets the client, the health check and the dashboard.

## Which engine

Both sit behind one interface (`get_inference_engine()`), so the health check, the dashboards, the CLI and the catalog read either the same way.

| Engine | What it is | Pick it for |
|---|---|---|
| `ollama` (default) | Pulls, loads and frees many models on request. | Trying models; switching between several. |
| `llamacpp` | `llama-server`: a router over a folder of GGUFs (`make llama`) loads and frees them on request; started on one model, it offers no load or unload. | Chat that runs long tool loops. Its prompt cache rereads a shared prefix fast: a follow-up on a 12k-token prefix takes 0.6 s, where Ollama takes 4.6 s (measured on an M4 Max, the same GGUF). |

### Running llama-server

On the host, `make llama` (`my-app inference llama`) serves every GGUF in `LLAMACPP_MODELS_DIR` (default `~/models`) as a router, with the flags chat needs. Ollama's models are linked in first when `OLLAMA_MODELS` (default `~/.ollama/models`) holds any, so one download serves both; `my-app inference link-ollama` links them without serving. It runs in the foreground: Ctrl-C stops it.

```bash
brew install llama.cpp
make llama
```

| Setting | Default | |
|---|---|---|
| `LLAMACPP_MODELS_DIR` | `~/models` | The folder it serves. |
| `LLAMACPP_BASE_URL` | port 8080 | Its port is the one it listens on. |
| `LLAMACPP_CONTEXT` | `32768` | `-c`. |
| `LLAMACPP_ARGS` | `-fa on -np 2 -kvu` | Further flags, as typed. |

To serve one model instead, start it by hand, and name the model with `--alias`, which is how the catalog shows it:

```bash
llama-server -hf ggml-org/Qwen3-1.7B-GGUF --alias qwen3:1.7b \
  --jinja -c 32768 -np 1 --metrics --port 8080
```

- `--jinja`: the model's chat template, which tool calls need.
- `-c`: the context. The catalog takes it from the server, and chat sizes its history to fit it.
- `-np 1` (or a few): context and prompt cache are per slot, so `-c 32768 -np 2` gives each slot 16k.
  With one slot, a long conversation's fold (its running summary, written on the worker as old turns leave the history) is a request of its own and replaces the chat's cached prompt, so the chat's next turn reads its prompt afresh: once per cut, not per turn. Give the `summarizer` agent row another model, or run a second slot, to keep the chat's cache.
- `--metrics`: Prometheus counters at `/metrics`.

To keep memory free on a GPU, add `--models-memory-margin <MiB>` to `LLAMACPP_ARGS`: the router unloads the least recently used model until a new one fits with that much to spare.

In docker, the `llamacpp` service is a router too:

- It serves every model in its download cache and in `/models/local` (the `llamacpp-models` volume), at `LLAMACPP_CONTEXT` (default 32768). Overseer > Inference loads and frees each one.
- It holds one model at a time (`--models-max 1`). The container's 8G holds one small model with its context, so loading another frees the last.
- On its first start it downloads `LLAMACPP_MODEL` (a Hugging Face `repo[:quant]`, default `ggml-org/Qwen3-1.7B-GGUF`) and loads it under that name, which is the `AI_MODEL` chat starts on.
- To add a `.gguf`: `docker compose cp <model.gguf> llamacpp:/models/local/`, then restart the service.

### Switching engines

The engine holds nothing of the project's (its models live where it keeps them), so an installed component switches in place. The AI service's local provider moves with it, the placement stays, and everything that branches on the engine re-renders:

```bash
aegis add inference[llamacpp]   # an Ollama project, now on llama.cpp
aegis add inference[ollama]     # and back
```

Point `LLAMACPP_BASE_URL` in `.env` at the server if it is not on the default port.

## Where it runs

| Placement | What ships | Reaches the engine at |
|---|---|---|
| `host` (default) | No container. The server runs where it already lives, with the host's GPU. | Ollama: `http://host.docker.internal:11434`; llama.cpp: `http://host.docker.internal:8080`. `localhost` from the host. |
| `docker` | An `ollama` or `llamacpp` service in the compose stack, models in a volume. | `http://ollama:11434`, `http://llamacpp:8080` |

Install Ollama from [ollama.com](https://ollama.com/) for host placement, then pull a model:

```bash
ollama pull llama3.1
```

## What you get

- **`app/components/inference/`**: `engine.py`, the one interface; `ollama.py` and `llamacpp.py`, async clients for each server's models, running models, and (Ollama) load and unload; `activity.py`, an in-memory record of models moving in and out of memory.
- **Settings:** `INFERENCE_ENGINE`; `OLLAMA_BASE_URL` or `LLAMACPP_BASE_URL` (defaulted from the placement), `OLLAMA_BASE_URL_LOCAL` for CLI commands run on the host, `OLLAMA_HOST_PORT` / `LLAMACPP_HOST_PORT` for the port `make serve` publishes, `OLLAMA_API_KEY` for a server behind auth.
- **A health check** on the system status, named `inference`, with each engine under it by name (`ollama` or `llamacpp`, and `kokoro_fastapi` where a speech server is set): reachable, installed and running models, VRAM in use.
- **Overseer > Inference** (with the htmx frontend):
    - **Overview:** a row per engine, with its job, whether it answers, what it holds, its memory and who runs on it (the agents whose model it serves, the voice that speaks or listens through it). One bar shows the memory the engines report together.
    - **Engines it lacks** are listed with the command or `.env` address that adds them, never an install button.
    - **A page per engine**, grouped by job in the menu: the text engine's Overview, Models (load and unload) and Activity, and the speech server's Overview and Voices. Container and Logs follow where the engines run in docker.
    - **An "In the app" row** appears where `ai[voice]` loads a model into the webserver (in-app Kokoro, Parakeet, faster-whisper), with the webserver's own memory.
- **The same on the CLI and API:** `my-app inference status` and `GET /api/v1/inference` list every engine as the overview does.
- **A dashboard card and modal**: installed models with load and unload, and an activity tab of recent loads and evictions.
- **The LLM catalog** lists the installed models when the AI service is present (`my-app llm sync --source local`).

Each engine reports memory its own way, and a row that reports none says why rather than show 0:

| Engine | Memory it reports |
|---|---|
| Ollama | Each loaded model's |
| llama.cpp | None (`/metrics` counts tokens and requests) |
| Kokoro-FastAPI | Its whole process, with `ENABLE_DEBUG_ENDPOINTS` on |
| In the app | The webserver's whole process, read on the webserver only |

The bar adds up what the engines report. It is not the machine's total: the webserver runs in Docker and sees the VM's memory, not the host's.

## A speech server

A speech server runs beside Ollama, where Ollama runs, and `ai[voice]` speaks through it. Kokoro-FastAPI is the one so far: Kokoro-82M, text to speech only.

```bash
aegis add inference[kokoro_fastapi]          # Kokoro-FastAPI on the host
aegis add inference[docker,kokoro_fastapi]   # a kokoro-fastapi service in the compose stack
```

An installed inference takes one later the same way: `aegis add inference[kokoro_fastapi]` keeps its engine and placement and adds the server.

| Placement | What ships | Reaches it at |
|---|---|---|
| `host` | No container. Run it yourself, with `make kokoro` (below). | `http://host.docker.internal:8880/v1` from containers, `localhost:8880` from the host |
| `docker` | A `kokoro-fastapi` service (the CPU image, 2G memory limit), started with `ALLOW_DEV_UNLOAD` and `ENABLE_DEBUG_ENDPOINTS` on. | `http://kokoro-fastapi:8880/v1` |

The answer sets `SPEECH_BASE_URL`'s default; `.env` can point it anywhere. With an address set:

- **Overseer > Inference > Kokoro-FastAPI** shows the server whole, read once a second while it is open:
    - **Figures:** its version, whether its model is loaded, the device it runs on, requests in flight, its memory and its voices.
    - **Server:** where the app reaches it, its backend and models (OpenAI's model names it answers to, for OpenAI's clients, listed apart as aliases), how long it has been idle, when it unloads, its threads. Unload and Reload move its model out of memory and back.
    - **Voices** (its own tab) by accent and gender. Press one to hear a line from the server itself, with or without `ai[voice]`.
    - **Charts:** its memory, its requests in flight, and how long each line took, as a whole file or a stream until its first audio (the page's own and `ai[voice]`'s).
- **The CLI and API** do the same: `my-app inference speech`, `my-app inference speak "a line" -v af_heart -o line.mp3`, `my-app inference speech-model unload|reload`; `GET /api/v1/inference/speech`, `GET /api/v1/inference/speech/say?voice=`, `POST /api/v1/inference/speech/{unload,reload}`.
- **The health check** carries it under the inference check (`my-app health status`, `/health/detailed`).
- **`ai[voice]`** offers it as the Kokoro-FastAPI provider, with every voice it lists ([Voice](../services/ai/voice.md#a-speech-server)).

A server with OpenAI's speech API alone shows its voices, its models and the app's own timings. Kokoro-FastAPI reports its version always, and the rest only with its flags on. A server you run yourself needs them set, or the page names the ones missing. `make kokoro` (`my-app inference kokoro`) sets them and runs the start script of a checkout at `SPEECH_SERVER_DIR` (default `~/Kokoro-FastAPI`): on its GPU where it has one (a Mac, or an NVIDIA card with `nvidia-smi` on the PATH), the CPU one elsewhere, and on Windows the `.ps1` one through PowerShell (which serves on 8880 whatever `SPEECH_BASE_URL` says). It runs in the foreground: Ctrl-C stops it.

```bash
git clone https://github.com/remsky/Kokoro-FastAPI ~/Kokoro-FastAPI
make kokoro
```

| Flag | Opens |
|---|---|
| `ALLOW_DEV_UNLOAD` | Its model's state (loaded, device, requests, idle), and Unload and Reload |
| `ENABLE_DEBUG_ENDPOINTS` | Its process: memory and threads |

## Changing placement

The placement is an answer in `.copier-answers.yml` (`inference_placement`), and the speech server another (`inference_speech`). A speech server is added in place (above); to change the placement, remove and re-add the component:

```bash
aegis remove inference
aegis add inference[docker]
```
