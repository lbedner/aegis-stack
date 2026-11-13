# Inference

Local model serving: the Ollama client, its health check, and a dashboard for the models loaded into memory.

```bash
aegis add inference                  # Ollama on the host (the default)
aegis add inference[docker]          # Ollama as a container in the compose stack
aegis add inference[ollama,docker]   # the engine spelled out; ollama is the only one today
```

The AI service's `ollama` provider pulls the component in, so `aegis init --services "ai[ollama]"` gets it without asking. It also stands alone: a model server with no AI service still gets the client, the health check and the dashboard.

## Where Ollama runs

| Placement | What ships | Reaches Ollama at |
|---|---|---|
| `host` (default) | No container. Ollama runs where it already lives, with the host's GPU. | `http://host.docker.internal:11434` from containers, `localhost:11434` from the host |
| `docker` | An `ollama` service in the compose stack, models in a volume. | `http://ollama:11434` |

Install Ollama from [ollama.com](https://ollama.com/) for host placement, then pull a model:

```bash
ollama pull llama3.1
```

## What you get

- **`app/components/inference/`**: `ollama.py`, an async client for the server's model list, running models, load and unload; `activity.py`, an in-memory record of models moving in and out of memory.
- **Settings:** `OLLAMA_BASE_URL` (defaulted from the placement), `OLLAMA_BASE_URL_LOCAL` for CLI commands run on the host, `OLLAMA_HOST_PORT` for the port `make serve` publishes, `OLLAMA_API_KEY` for a server behind auth.
- **A health check** on the system status: server reachable, installed and running models, VRAM in use.
- **A dashboard card and modal**: installed models with load and unload, and an activity tab of recent loads and evictions.
- **The LLM catalog** lists the installed models when the AI service is present (`my-app llm sync --source ollama`).

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
