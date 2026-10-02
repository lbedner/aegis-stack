# Secrets

Every credential the app reads goes through one interface, `app.core.secrets`. It ships in every project.

```python
from app.core import secrets

api_key = await secrets.get("RESEND_API_KEY")
```

## Where values come from

`.env` (with the process environment) is the default backend: read-only, and a value changes when the server restarts. A writable backend, the optional [secrets component](../secrets/index.md), plugs in behind the same calls and makes keys settable while the app runs. A value set in `.env` always wins over a stored one and cannot be changed anywhere else.

The bundled services read their keys through it: comms (Resend, Twilio), payment (Stripe), the AI providers, voice, RAG embeddings and OAuth sign-in. Each reads at the moment of use, so a key saved in the store applies on the next call. Reading `settings` stays fine for your own code: a value there comes from `.env` alone.

For several keys at once (a provider's key and its settings), `await secrets.get_many(*names)` reads them with one store lookup. A service built with its own settings object passes it as `source=`, and `.env` values are read from that.

Names are the settings' own (`RESEND_API_KEY`, `TWILIO_AUTH_TOKEN`), so one name works in `.env`, in `Settings` and in a store.

## Listing a setting without code

Type a `Settings` field `Credential` and the Secrets page lists it, with no `SECRETS` tuple and no `OWNERS` entry:

```python
from app.core.credential import Credential

SENDGRID_API_KEY: Credential = None  # still a plain str when read
```

Code that reads it through `settings` only sees `.env`, so it is listed read-only. Declare it in `SECRETS` and read it with `secrets.get` to make it settable while the app runs.

## Declaring what you read

The code that reads a credential declares it beside itself, in a module listed in `OWNERS` (`app/core/secrets.py`):

```python
from app.core.secrets import Secret

SECRETS = (
    Secret("RESEND_API_KEY", owner="Email (Resend)"),
    Secret("RESEND_FROM_EMAIL", owner="Email (Resend)", label="From address", secret=False),
)
```

`secret=False` marks provider configuration that is safe to show in full, like a from address or a phone number. The AI service derives its declarations from its provider registry, so a new provider is declared with it. Comms (Resend, Twilio), payment (Stripe) and sign-in (GitHub and Google OAuth) declare theirs.

### Needed or optional

`needed` says whether something enabled reads the key. It is a bool, or a callable when config decides:

```python
Secret("RESEND_API_KEY", owner="Email (Resend)", needed=True)
Secret("GROQ_API_KEY", owner="AI", needed=lambda: settings.AI_PROVIDER == "groq")
```

An unset needed key reads **Missing**; an unset optional one, a provider you could add, reads **Not used**. Leave it `False` for a choice.

### Choices

`choices` lists values the provider itself has, as `(value, label)` pairs, so the Overseer can offer them instead of a blank field (the Twilio account's numbers, the Resend account's verified domains). It raises like `verify` when the provider cannot answer, and the field then just takes typing. `await secrets.choices(name)` returns the list, or an empty one.

### A provider check

`verify` is one cheap call that tells a working key from a typo. `probe` covers the usual shape, an authenticated GET:

```python
from app.core.secrets import Secret, probe


async def _verify_resend(key: str) -> None:
    await probe(
        "https://api.resend.com/domains",
        headers={"Authorization": f"Bearer {key}"},
        # A send-only key is refused here by name, which still proves it is real.
        passes=lambda r: r.is_success or "restricted_api_key" in r.text,
    )


SECRETS = (Secret("RESEND_API_KEY", owner="Email (Resend)", verify=_verify_resend),)
```

`probe` returns when `passes` holds (by default, any 2xx). It raises `SecretRejectedError` for a status in `rejected` (default `401`; Google answers a bad key with `400`), and `SecretUncheckedError` for anything else, a network failure included. It never repeats the provider's body, because some echo part of a rejected key. A hand-written `verify` raises the same two errors.

## Values are write-only

`get` hands a value to the code that uses it. Everything else sees only `await secrets.status()`: for every declared secret, whether it is set, where (`env` or `database`), its last four characters (none for a value under 12 characters), and, from a store, when and by whom it was set. Provider configuration (`secret=False`) shows in full.

`status()` also carries `needed` and `verifiable` (whether the key has a check).

Writes go through `await secrets.put(name, value, actor)`. With only `.env` they refuse with the reason ("No writable backend: set RESEND_API_KEY in .env, or add the secrets component"); a name set in `.env`, or one nothing declares, is refused too. With a check, `put` runs it first: a key the provider refuses raises `SecretRejectedError` and is not stored, and one it could not be asked about is stored. `put` returns the check's `Verdict` (`result` is `VERIFIED`, `UNVERIFIED` or `REJECTED`, plus a `message` that never carries the value), or `None` for a key without a check.

`await secrets.test(name)` runs the check against the value in effect, wherever it is set, and returns a `Verdict`.

## In the Overseer

**Overseer > Secrets** (a top-level page; with the secrets component it moves to the component's own page under Components) lists every declared secret grouped by the code that reads it: its source, its last four characters, whether it is needed, and, for one that is missing, the `.env` line to add. A key with a check has a **Test** button. It never shows a value. Like every Overseer page it is admin-only (see [Who can open the Overseer](../web-frontend/index.md#who-can-open-the-overseer)).

With the [secrets component](../secrets/index.md), the page (and the Flet dashboard's Secrets modal) also sets, replaces and removes keys not set in `.env`.
