"""A llama.cpp ``llama-server`` for tests (``app.components.inference``),
by path, as a real one answers (trimmed to what is read): one model, which
is both installed and loaded, as a single-model server serves it. Its
``/v1/models`` also carries the Ollama-shaped ``models`` list a real one
does, every field empty, which the engine must not read.
"""

from typing import Any

MODEL = "qwen2.5:7b"  # what ``--alias`` names it; the GGUF's path otherwise

ROUTES: dict[str, Any] = {
    "/health": {"status": "ok"},
    "/props": {
        "modalities": {"vision": False, "audio": False},
        "chat_template_caps": {"supports_tool_calls": True, "supports_tools": True},
        "build_info": "b6700-cd959bae9",
    },
    "/v1/models": {
        "models": [
            {
                "name": MODEL,
                "model": MODEL,
                "modified_at": "",
                "size": "",
                "digest": "",
                "capabilities": ["completion"],
                "details": {"format": "gguf", "family": "", "parameter_size": ""},
            }
        ],
        "object": "list",
        "data": [
            {
                "id": MODEL,
                "aliases": [MODEL],
                "object": "model",
                "created": 1759233600,
                "owned_by": "llamacpp",
                "meta": {
                    "n_vocab": 152064,
                    "n_ctx": 32768,
                    "n_ctx_train": 131072,
                    "n_embd": 3584,
                    "n_params": 7615616512,
                    "size": 4683073952,
                    "ftype": "Q4_K - Medium",
                },
            }
        ],
    },
}

# A router (``llama-server --models-dir``), as b12110 answers: ``/props``
# says so, and ``/v1/models`` lists every model it can serve, each with its
# status and where it found it; ``/models/load`` and ``/models/unload`` move
# one. It knows a model's trained context, not its size or what it can do.
OTHER = "llama3.1:8b"
ROUTER: dict[str, Any] = {
    "/props": {
        "role": "router",
        "model_path": "none",
        "build_info": "b12110-cd959bae9",
    },
    "/v1/models": {
        "object": "list",
        "data": [
            {
                "id": name,
                "aliases": [],
                "object": "model",
                "owned_by": "llamacpp",
                "status": {"value": state, "args": []},
                "source": source,
                "can_remove": source == "cache",
                "context_length": 131072,
            }
            for name, state, source in (
                (MODEL, "loaded", "models_dir"),
                (OTHER, "unloaded", "cache"),
            )
        ],
    },
    "/models/load": {"success": True},
    "/models/unload": {"success": True},
}
