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

## Changing placement

The placement is an answer in `.copier-answers.yml` (`inference_placement`). Remove and re-add the component to switch:

```bash
aegis remove inference
aegis add inference[docker]
```
