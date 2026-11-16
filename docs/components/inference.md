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
| `llamacpp` | `llama-server` serving the one model it was started with: no load or unload, so the dashboards offer none. | Chat that runs long tool loops. Its prompt cache rereads a shared prefix fast: a follow-up on a 12k-token prefix takes 0.6 s, where Ollama takes 4.6 s (measured on an M4 Max, the same GGUF). |

### Running llama-server

On the host, start it with the flags chat needs, and name the model with `--alias`, which is how the catalog shows it:

```bash
llama-server -hf ggml-org/Qwen3-1.7B-GGUF --alias qwen3:1.7b \
  --jinja -c 32768 -np 1 --metrics --port 8080
```

- `--jinja`: the model's chat template, which tool calls need.
- `-c`: the context. The catalog takes it from the server, and chat sizes its history to fit it.
- `-np 1` (or a few): context and prompt cache are per slot, so `-c 32768 -np 2` gives each slot 16k.
  With one slot, a long conversation's fold (its running summary, written on the worker as old turns leave the history) is a request of its own and replaces the chat's cached prompt, so the chat's next turn reads its prompt afresh: once per cut, not per turn. Give the `summarizer` agent row another model, or run a second slot, to keep the chat's cache.
- `--metrics`: Prometheus counters at `/metrics`.

In docker, the `llamacpp` service downloads `LLAMACPP_MODEL` (a Hugging Face `repo[:quant]`, default `ggml-org/Qwen3-1.7B-GGUF`) into a volume on its first start and serves it at `LLAMACPP_CONTEXT` (default 32768).

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
- **A health check** on the system status: server reachable, installed and running models, VRAM in use.
- **A dashboard card and modal**: installed models with load and unload, and an activity tab of recent loads and evictions.
- **The LLM catalog** lists the installed models when the AI service is present (`my-app llm sync --source local`).

## A speech server

A speech server runs beside Ollama, where Ollama runs, and `ai[voice]` speaks through it. Kokoro-FastAPI is the one so far: Kokoro-82M, text to speech only.

```bash
aegis add inference[kokoro_fastapi]          # Kokoro-FastAPI on the host
aegis add inference[docker,kokoro_fastapi]   # a kokoro-fastapi service in the compose stack
```

| Placement | What ships | Reaches it at |
|---|---|---|
| `host` | No container. Run it yourself ([how](../services/ai/voice.md#a-speech-server)). | `http://host.docker.internal:8880/v1` from containers, `localhost:8880` from the host |
| `docker` | A `kokoro-fastapi` service (the CPU image, 2G memory limit), started with `ALLOW_DEV_UNLOAD` and `ENABLE_DEBUG_ENDPOINTS` on. | `http://kokoro-fastapi:8880/v1` |

The answer sets `SPEECH_BASE_URL`'s default; `.env` can point it anywhere. With an address set:

- **Overseer > Inference > Speech** shows the server whole, read once a second while it is open:
    - **Figures:** its version, whether its model is loaded, the device it runs on, requests in flight, its memory and its voices.
    - **Server:** where the app reaches it, its backend and models (OpenAI's model names it answers to, for OpenAI's clients, listed apart as aliases), how long it has been idle, when it unloads, its threads. Unload and Reload move its model out of memory and back.
    - **Voices** by accent and gender. Press one to hear a line from the server itself, with or without `ai[voice]`.
    - **Charts:** its memory, its requests in flight, and how long each line took, as a whole file or a stream until its first audio (the page's own and `ai[voice]`'s).
- **The CLI and API** do the same: `my-app inference speech`, `my-app inference speak "a line" -v af_heart -o line.mp3`, `my-app inference speech-model unload|reload`; `GET /api/v1/inference/speech`, `GET /api/v1/inference/speech/say?voice=`, `POST /api/v1/inference/speech/{unload,reload}`.
- **The health check** carries it under the inference check (`my-app health status`, `/health/detailed`).
- **`ai[voice]`** offers it as the Kokoro-FastAPI provider, with every voice it lists ([Voice](../services/ai/voice.md#a-speech-server)).

A server with OpenAI's speech API alone shows its voices, its models and the app's own timings. Kokoro-FastAPI reports its version always, and the rest only with its flags on. A server you run yourself needs them set, or the page names the ones missing:

```bash
ALLOW_DEV_UNLOAD=true ENABLE_DEBUG_ENDPOINTS=true ./start-gpu_mac.sh
```

| Flag | Opens |
|---|---|
| `ALLOW_DEV_UNLOAD` | Its model's state (loaded, device, requests, idle), and Unload and Reload |
| `ENABLE_DEBUG_ENDPOINTS` | Its process: memory and threads |

## Changing placement

The placement is an answer in `.copier-answers.yml` (`inference_placement`), and the speech server another (`inference_speech`). Remove and re-add the component to switch:

```bash
aegis remove inference
aegis add inference[docker]
```
