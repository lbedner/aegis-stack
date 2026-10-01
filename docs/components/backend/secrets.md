# Secrets

Every credential the app reads goes through one interface, `app.core.secrets`. It ships in every project.

```python
from app.core import secrets

api_key = await secrets.get("RESEND_API_KEY")
```

## Where values come from

`.env` (with the process environment) is the default backend: read-only, and a value changes when the server restarts. A writable backend, the optional secrets component, plugs in behind the same calls. A value set in `.env` always wins over a stored one and cannot be changed anywhere else.

Today the services still read their keys from `Settings` directly. They move onto `secrets.get` together with the writable backend, which is what makes a stored value take effect; until then `.env` is the only source that matters.

Names are the settings' own (`RESEND_API_KEY`, `TWILIO_AUTH_TOKEN`), so one name works in `.env`, in `Settings` and in a store.

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

## Values are write-only

`get` hands a value to the code that uses it. Everything else sees only `await secrets.status()`: for every declared secret, whether it is set, where (`env` or `database`), its last four characters (none for a value under 12 characters), and, from a store, when and by whom it was set. Provider configuration (`secret=False`) shows in full.

Writes go through `await secrets.put(name, value, actor)`. With only `.env` they refuse with the reason ("No writable backend: set RESEND_API_KEY in .env, or add the secrets component"); a name set in `.env`, or one nothing declares, is refused too.

## In the Overseer

**Overseer > Secrets** lists every declared secret grouped by the code that reads it: its source, its last four characters, and, for one that is missing, the `.env` line to add. It never shows a value. Like every Overseer page it is admin-only (see [Who can open the Overseer](../web-frontend/index.md#who-can-open-the-overseer)).
