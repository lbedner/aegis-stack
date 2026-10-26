# Voice (TTS/STT)

![Voice](../../images/voice.png)

Voice capabilities add Text-to-Speech (TTS) and Speech-to-Text (STT) to the AI service. Multiple providers are supported, from cloud APIs to fully local inference.

!!! warning "Experimental Feature"
    Voice is currently experimental. Some features may not work out of the box and will require configuration on your part. For example, TTS and STT providers that need API keys (like OpenAI) may return errors or hang in the frontend if the key is not set. Make sure your provider credentials are configured before using voice features.

!!! info "Enable at Project Generation"
    Voice is an optional feature enabled at project generation:

    ```bash
    aegis init my-app --services "ai[voice]"

    # With database and RAG
    aegis init my-app --services "ai[sqlite,rag,voice]"
    ```

## What You Get

- **Text-to-Speech** - Convert text to audio with multiple voices and speed control
- **Speech-to-Text** - Transcribe audio with timestamps and segment detection
- **Multiple providers** - Cloud (OpenAI, Gemini, Groq) and local (Whisper, faster-whisper)
- **Voice catalog** - Browse providers, models, and voices via API
- **Voice previews** - Generate audio samples to compare voices
- **Usage tracking** - TTS and STT operations tracked alongside LLM usage

---

## TTS Providers

| Provider | Type | Models | Voices | Streaming | API Key |
|----------|------|--------|--------|-----------|---------|
| **OpenAI** | Cloud | gpt-realtime-2.1-mini (gpt-4o-mini-tts, tts-1, tts-1-hd shut down Jan 6, 2027) | 13 (marin, cedar, alloy, ...); 10 on gpt-realtime-2.1-mini | The /v1/audio/speech models only | `OPENAI_API_KEY` |
| **Gemini** | Cloud | gemini-3.8-flash-tts, gemini-3.8-flash-lite-tts | 30 prebuilt (Kore, Puck, Charon, ...) and its voice library | No | `GOOGLE_API_KEY` |

Each speech model records what its delivery instructions steer, as its
provider documents it: OpenAI's gpt-realtime and gpt-4o voices take the
accent, emotion, intonation, impressions, speed, tone and whispering; Gemini's take style,
tone, emotion and pace, and leave the accent to the voice; tts-1 and
tts-1-hd take none.

Each speech model also records the speeds it takes: 0.25 to 1.5 on
gpt-realtime-2.1-mini, 0.25 to 4.0 on the /v1/audio/speech models, and
none on Gemini's. The voice editor's speed slider spans that range, and is
not shown for a model with no speed.

The voice catalog records which models speak each voice. A voice is only
ever said on a model that speaks it: a preview picks one, and a voice
profile refuses a voice its model does not speak.

### OpenAI TTS

- **gpt-realtime-2.1-mini** (the default) - takes delivery instructions; ten of the voices (not fable, nova or onyx)
- **gpt-4o-mini-tts** and its two pinned builds - shut down Jan 6, 2027; every voice, and takes delivery instructions
- **tts-1** - shut down Jan 6, 2027; optimized for speed; nine of the voices (not marin, cedar, ballad or verse), no instructions
- **tts-1-hd** - shut down Jan 6, 2027; higher quality; the same nine voices

OpenAI shuts every /v1/audio/speech model down on Jan 6, 2027 and names
gpt-realtime-2.1-mini, which speaks only over the Realtime API, as their
replacement. A line is said there one way: a session that never listens
(no turn detection, no audio sent), the line as the response's only
message, and instructions to read it aloud word for word, after the
delivery. The line is a message, not part of the instructions, so a line
that reads as a command ("ignore all previous instructions...") is read,
not obeyed. It comes back as a 24kHz WAV, whole rather than streamed, and
is priced by its tokens like a live call.

OpenAI recommends marin or cedar for the best quality. An accent asked for
in the instructions is a hint: an American voice asked for British comes
out partly British at best.

```bash
# .env configuration
TTS_PROVIDER=openai
TTS_MODEL=gpt-realtime-2.1-mini
TTS_VOICE=alloy
TTS_SPEED=1.0   # 0.25 to 4.0; gpt-realtime-2.1-mini holds it at 1.5
```

### Gemini TTS

Gemini's 3.8 speech models (``gemini-3.8-flash-tts``, the flagship, and
``gemini-3.8-flash-lite-tts``, fast and low cost) speak its 30 prebuilt
voices, the same ones Gemini Live speaks, so a live call and a spoken line
can share one voice, and the voices of its voice library: about two
thousand, in some fifty accents (Dublin, Glasgow, Sydney, Montreal, Osaka,
Tamil...). The library is read with the key once per process, every page,
in the background: nothing waits on it, and its voices appear as they come
in. Each takes the tone its description says. The voice editor searches
them with every other voice; the Models table leaves them out. Gemini Live keeps to the prebuilt 30. Speech goes through the Interactions API: the line is the
transcript and the delivery its ``speech_metadata`` style. Audio comes
back as WAV; there is no speed to set. Gemini takes the accent from the
voice, not the instructions: pick a voice with the accent. The 2.5 preview
models are open only to past users.

```bash
TTS_PROVIDER=gemini
TTS_MODEL=gemini-3.8-flash-tts
TTS_VOICE=Kore
GOOGLE_API_KEY=...
```

---

## STT Providers

| Provider | Type | Model | Speed | Quality | Requires |
|----------|------|-------|-------|---------|----------|
| **OpenAI Whisper** | Cloud | whisper-1 | Good | High | `OPENAI_API_KEY` |
| **Groq Whisper** | Cloud | whisper-large-v3-turbo | Very fast | High | `GROQ_API_KEY` |
| **Local Whisper** | Local | whisper-tiny to large-v3 | Varies | Varies | `transformers`, `torch` |
| **faster-whisper** | Local | tiny to large-v3 | 4x faster | High | `faster-whisper` |

### OpenAI Whisper

Cloud-based transcription with segment timestamps:

```bash
STT_PROVIDER=openai_whisper
STT_MODEL=whisper-1
```

### Groq Whisper

Ultra-fast cloud transcription:

```bash
STT_PROVIDER=groq_whisper
STT_MODEL=whisper-large-v3-turbo
```

### Local Whisper

Runs on your machine via HuggingFace transformers. Auto-detects GPU (CUDA, MPS) or falls back to CPU:

```bash
STT_PROVIDER=whisper_local
STT_MODEL=openai/whisper-base   # tiny, base, small, medium, large-v3
```

Requires: `uv add transformers torch`

### faster-whisper

SYSTRAN's optimized implementation - 4x faster than standard Whisper with similar accuracy:

```bash
STT_PROVIDER=faster_whisper
STT_MODEL=base   # tiny, base, small, medium, large-v3
```

Requires: `uv add faster-whisper`

Supports compute types: `default`, `float16`, `int8`

---

## API Endpoints

All endpoints are prefixed with `/voice`.

### TTS Catalog

```bash
# List TTS providers
curl http://localhost:8000/voice/catalog/tts/providers | jq

# List models for a provider
curl http://localhost:8000/voice/catalog/tts/openai/models | jq

# List voices for a provider
curl http://localhost:8000/voice/catalog/tts/openai/voices | jq
```

**Provider Response:**

```json
{
  "id": "openai",
  "name": "OpenAI",
  "type": "tts",
  "requires_api_key": true,
  "api_key_env_var": "OPENAI_API_KEY",
  "is_local": false,
  "description": "OpenAI TTS API"
}
```

**Voice Response:**

```json
{
  "id": "alloy",
  "name": "Alloy",
  "provider_id": "openai",
  "model_ids": ["gpt-realtime-2.1-mini", "gpt-4o-mini-tts", "tts-1", "tts-1-hd"],
  "description": "Neutral, balanced voice",
  "category": "neutral",
  "gender": "neutral",
  "preview_text": "Hello, I'm Alloy..."
}
```

### STT Catalog

```bash
# List STT providers
curl http://localhost:8000/voice/catalog/stt/providers | jq

# List models for a provider
curl http://localhost:8000/voice/catalog/stt/openai_whisper/models | jq
```

### Voice Settings

```bash
# Get current settings
curl http://localhost:8000/voice/settings | jq
```

**Settings fields:** `tts_provider`, `tts_model`, `tts_voice`, `tts_speed`, `stt_provider`, `stt_model`, `stt_language`

### Voice Overview

What the active voice profile uses, then every speech, hearing and live
model and every voice, each with the voice and model to hear it on and the
change a Use would make. Both Overseers show it.

```bash
curl http://localhost:8000/voice/overview | jq

# Put a row on the active profile (an admin's); the rest is made to fit:
# a voice brings its provider and a model that speaks it
curl -X POST http://localhost:8000/voice/use \
  -H "Content-Type: application/json" -d '{"tts_voice": "Kore"}'

# Make another profile the active one
curl -X POST http://localhost:8000/voice/profiles/2/active
```

Each answers with the overview as it now is.

### Voice Design

```bash
# A profile's design (the active one's without ?profile=): every voice with
# its gender and tone, the styles and dials, what is picked, what it sends
curl "http://localhost:8000/voice/design?profile=1" | jq

# Choices in the query are composed, not saved
curl "http://localhost:8000/voice/design?voice=marin&style=calm" | jq .instructions

# Hear them unsaved
curl "http://localhost:8000/voice/design/preview?voice=marin&style=calm&accent=british" --output design.wav

# Hear a saved profile
curl http://localhost:8000/voice/design/profiles/1/preview --output profile.wav

# Every profile at a glance; a new one from the one in use (an admin's)
curl http://localhost:8000/voice/design/profiles | jq
curl -X POST http://localhost:8000/voice/design/profiles -H "Content-Type: application/json" -d '{"name": "Calls"}'

# Save them onto a profile (an admin's)
curl -X POST "http://localhost:8000/voice/design?profile=1" -H "Content-Type: application/json" \
  -d '{"voice": "marin", "delivery": {"style": "calm", "accent": "british"}, "speed": 1.0}'
``` A stack keeping no voice
profiles (no database) shows what its settings use, and a change is a 409.

### Voice Preview

Generate audio samples to compare voices:

```bash
# POST with body
curl -X POST http://localhost:8000/voice/preview \
  -H "Content-Type: application/json" \
  -d '{"voice_id": "alloy", "text": "Hello world"}' \
  --output preview.mp3

# GET (browser-friendly), optionally on a model that speaks the voice
curl "http://localhost:8000/voice/preview/marin?text=Hello+world&model=gpt-realtime-2.1-mini" \
  --output preview.wav
```

Said on the model named, or the one in use, where it speaks the voice;
otherwise on one that does. Returns the provider's audio: `audio/mpeg`
from OpenAI, `audio/wav` from Gemini.

### Voice Chat

A spoken turn is a typed turn with a microphone in front of it: the
transcript becomes the user's message in the same conversation, answered
by the same agent, as if it had been typed.

```bash
curl -X POST "http://localhost:8000/api/v1/ai/voice-chat?conversation_id=c-1&user_id=u-1&agent_slug=helper&surface=support&transcription_hint=Aegis" \
  -F "audio=@question.webm"
```

| Parameter | Meaning |
|-----------|---------|
| `conversation_id` | Continue this conversation (a new one when omitted) |
| `user_id` | Who spoke: owns the turn, and STT/TTS usage is recorded against it |
| `agent_slug` | The agent that answers, exactly as for a typed turn; the stack never picks one |
| `surface` | The history scope the turn lands in, as for a typed turn |
| `transcription_hint` | Names the transcriber should spell right, sent to it as its prompt |
| `voice_mode` | Return the answer as plain spoken sentences |
| `return_audio` | Also synthesize those sentences and return `audio/mpeg` |

The audio is not stored: the conversation holds the words, and the usage
records hold the cost. The spoken version of an answer is the agent's own
words with the markdown stripped (`voice/spoken.py`), not a second model
call. `/api/v1/ai/synthesize` takes form fields (`text`, `voice`, `speed`).

### Catalog Summary

```bash
curl http://localhost:8000/voice/catalog/summary | jq
```

```json
{
  "tts": {
    "provider_count": 2,
    "model_count": 7,
    "voice_count": 43,
    "providers": ["openai", "gemini"]
  },
  "stt": {
    "provider_count": 4,
    "model_count": 4,
    "providers": ["openai_whisper", "whisper_local", "faster_whisper", "groq_whisper"]
  },
  "current_config": {
    "tts_provider": "openai",
    "tts_model": "gpt-realtime-2.1-mini",
    "tts_voice": "alloy",
    "stt_provider": "openai_whisper",
    "stt_model": "whisper-1"
  }
}
```

---

## Live Calls

The phone beside the chat's microphone opens a live call on the engine the
voice profile names (Gemini Live, an OpenAI realtime model, or GPT-Live).
The server holds the engine's session; the page carries the audio over one
WebSocket. The agent on a call is built the way a typed turn builds it:
the same prompt, memory modules, contexts and tools, plus how to talk on a
call and a tool to end it.

- **Working, not narrating.** While the agent runs a step, the page plays
  soft key taps (the profile's "while it works" sound) instead of the agent
  announcing its lookups.
- **The quiet.** No provider ends a call on silence, and a call bills while
  it is open, so the page counts real quiet: nobody speaking (from your
  first sound, where the provider reports it: OpenAI and xAI do, Gemini
  from your first transcribed word), no answer to what you just said still
  coming, the agent's audio played out, nothing being worked on, not
  muted. After the profile's
  "check in after" seconds the agent asks if you are still there; still
  quiet, it says goodbye, and the call ends a moment after that has played.
  The status line counts the last stretch down. Anything you say starts the
  count over. The rules live in `static/js/call-state.js`, tested on Node
  (`tests/js`).
- **Noise.** OpenAI realtime filters a laptop mic's noise and ends your turn
  when the thought does, not on a pause; Gemini waits 800ms of silence
  before ending it.
- **Mute** stops your voice going out (after a moment of silence, so the
  engine hears you stop) and pauses the quiet count.
- **Her voice.** A call speaks the profile's voice where the engine's
  provider has it: Gemini Live speaks a Gemini voice, an OpenAI engine an
  OpenAI one. With a voice the engine does not have, it speaks its own.

---

## Pronunciation

One list says how every voice says a term: answers read aloud, the meeting
bot, previews, and live calls. It starts with the stack's own names
(Traefik as "traffic", Redis as "red-iss", PostgreSQL, SQLite, htmx,
Pydantic, Ollama, uvicorn, Aegis, MCP, OTel), kept in code in
`app/services/ai/domains/voice/spoken.py`, so a stack without a database
still has it.

- **Read aloud**, the speech service swaps each term as a whole word, in
  any case, before the text is sent (`Traefiker` is left alone).
- **On a live call** the model speaks for itself, so it is told the list
  as a "Say X as Y" section with the engine's call manners, which reach
  whichever model speaks (GPT-Live's voice model takes them as its own).
- **An app's own terms** join it with one call, at import:

  ```python
  from app.services.ai.service import register_pronunciation

  register_pronunciation("Steward", "stew-ard")
  ```

- **Edits** are rows (`voice_pronunciation`), made in the chat's voice
  dialog (Pronunciation) or over the API. A row wins over a default or an
  app's own term and takes effect on the next thing said, with no restart;
  removing it brings the default back. An entry may also keep an IPA
  spelling, for a provider's own dictionary; none reads it yet.

```bash
curl http://localhost:8000/api/v1/voice/pronunciation | jq
# An admin's: save one, or drop the saved row for a term
curl -X POST http://localhost:8000/api/v1/voice/pronunciation \
  -H "Content-Type: application/json" -d '{"term": "Illiana", "say": "ill-ee-ah-na"}'
curl -X DELETE http://localhost:8000/api/v1/voice/pronunciation/Illiana
```

---

## In Overseer

Overseer > AI > Voice has two tabs.

**Profiles** lists every voice profile at a glance: its voice, style and
speed, which one is in use, a Listen button, and Edit. A new profile starts
from the one in use. Edit opens the profile in three steps:

1. **Voice**: who it is, and the model it is spoken on. The chosen voice
   is pinned on top; below it a search finds others, as the model catalog
   does: text over name, tone, accent and description, and checklists for
   provider, gender, tone family (Warm and soft, Bright and upbeat, Calm
   and even, Firm and authoritative, Expressive) and accent, the accents
   grouped by language (a language ticked takes all of its accents, and
   only the accents of the voices in view are offered). It opens on voices
   like the chosen one (its provider and accent) and lists the first 50
   matches, saying how many more there are; each plays a sample. Each model the voice is spoken on says whether it follows
   delivery instructions. Only voices that can be heard are
   listed: a provider without its key is one line saying which key it
   needs.
2. **Delivery**: how it talks. A premade style (Calm and warm, Brisk and
   professional, Cheerful, Storyteller, Empathetic support, Newsreader),
   each playable with the fine-tuning kept, and the speed; pace, energy,
   emotion and anything extra under Fine-tune, and an accent where the
   model steers one (on Gemini the accent comes with the voice). A model
   that ignores delivery instructions is said up front.
3. **Review**: the voice, style and speed, the delivery instructions they
   make (the "Voice Affect / Tone / Pacing" form OpenAI's voices read;
   Gemini takes the same words as the line's style), Listen to hear them
   unsaved, and Save.

The profile keeps the choices, so the editor opens on them again. The
chat's voice dialog keeps a profile's name, hearing model, reply and
check-in, and opens the editor for the voice itself.

**Models** is one tight table: what the active profile uses, every speech,
hearing and live model (with its price where the model catalog has one)
and every voice, in columns, narrowed by kind, provider, model and text
with no request. Each voice plays on a model that speaks it; Use puts a row
on the active profile.

The Flet Overseer's voice tab has the same two views, over the API.

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `TTS_PROVIDER` | `openai` | TTS provider |
| `TTS_MODEL` | `gpt-realtime-2.1-mini` | TTS model (Gemini: `gemini-3.8-flash-tts`) |
| `TTS_VOICE` | `alloy` | Default voice |
| `TTS_SPEED` | `1.0` | Speed multiplier (0.25-4.0) |
| `STT_PROVIDER` | `openai_whisper` | STT provider |
| `STT_MODEL` | `whisper-1` | STT model |
| `STT_LANGUAGE` | auto-detect | Language for transcription |

---

## Data Models

### TTS

- **SpeechRequest** - `text`, `voice`, `speed`
- **SpeechResult** - `audio` (bytes), `format` (MP3 from OpenAI, WAV from Gemini), `media_type`, `provider`

### STT

- **AudioInput** - `content` (bytes), `format`, `language`, `prompt` (a spelling hint for the transcriber)
- **TranscriptionResult** - `text`, `language`, `duration_seconds`, `provider`, `segments`
- **TranscriptionSegment** - `text`, `start`, `end`, `confidence`

---

## Source Files

| File | Purpose |
|------|---------|
| `app/services/ai/voice/tts/providers.py` | TTS provider implementations |
| `app/services/ai/voice/tts/service.py` | TTS service |
| `app/services/ai/voice/tts/config.py` | TTS configuration |
| `app/services/ai/voice/tts/usage.py` | TTS usage tracking |
| `app/services/ai/voice/stt/providers.py` | STT provider implementations |
| `app/services/ai/voice/stt/service.py` | STT service |
| `app/services/ai/voice/stt/config.py` | STT configuration |
| `app/services/ai/voice/stt/usage.py` | STT usage tracking |
| `app/services/ai/voice/catalog.py` | Voice catalog (providers, models, voices) |
| `app/services/ai/voice/models.py` | Data models |
| `app/services/ai/voice/spoken.py` | An answer as it is said: markdown stripped |
| `app/components/backend/api/voice/router.py` | API endpoints |

---

**Next Steps:**

- **[AI Service Overview](index.md)** - Getting started
- **[Provider Setup](providers.md)** - Configure AI providers
- **[API Reference](api.md)** - All REST endpoints
- **[CLI Commands](cli.md)** - Command-line interface
