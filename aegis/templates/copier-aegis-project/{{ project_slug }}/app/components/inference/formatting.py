"""How a model's facts read on a page: quantization in bits, and the
digest as ``ollama list`` prints it. Shared by every UI that lists Ollama
models; a context window reads through ``app.core.model_picker``."""

# Digest characters shown, matching `ollama list`.
MODEL_ID_LENGTH = 12


def format_quantization(quant: str) -> str:
    """Convert quantization level to human-readable format.

    Q4_K_M → 4-bit
    Q8_0 → 8-bit
    Q5_K_S → 5-bit
    """
    if not quant or quant == "—":
        return "—"
    # Extract the bit number from formats like Q4_K_M, Q8_0, Q5_K_S
    if quant.startswith("Q") and len(quant) > 1:
        bit_num = quant[1]
        if bit_num.isdigit():
            return f"{bit_num}-bit"
    return quant


def format_model_id(digest: str) -> str:
    """Short digest, the same 12 characters ``ollama list`` prints.

    The full sha256 is 64 characters and would dominate the row; the
    leading 12 are what Ollama itself considers enough to identify a
    build, and they are what the user sees in the terminal.
    """
    if not digest:
        return "—"
    return digest[:MODEL_ID_LENGTH]
