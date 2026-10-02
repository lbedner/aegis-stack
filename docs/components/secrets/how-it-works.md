# How It Works

## How a value is resolved

```
await secrets.get("RESEND_API_KEY")
        |
        v
  set in .env or the environment? --yes--> that value (read-only everywhere else)
        |
        no
        v
  shared cache (ciphertext, 30 s) --miss--> secret table
        |
        v
  decrypted at the moment of use
```

`.env` always wins: a key set there shows as read-only, with "Change it in .env" where the edit field would be.

The shared cache (`app.core.cache`, Redis when the stack has it) holds the encrypted row, never a decrypted value. A write clears that row's entry, so with Redis the next read in any process sees the change. Without Redis, each process keeps its own copy and catches up within 30 seconds.

## What is stored

One row per key in the `secret` table (in a `secrets` schema on Postgres), with its own migration:

| Column | Holds |
|---|---|
| `name` | The setting's own name, `RESEND_API_KEY` |
| `ciphertext` | The value, AES-GCM encrypted and bound to the name: copied to another name, it will not decrypt |
| `hint` | The last four characters (none for a value under 12 characters); provider configuration like a from address is kept whole |
| `set_by`, `set_at` | Who saved it (an admin's email, or `cli:<user>`) and when |

Every write emits an audit event, `secrets.set` or `secrets.deleted`, with the actor and the name, never the value.

## Listed but read-only

Some credentials are read once, when a client is built at startup, rather than on each call. The storage component's `S3_ACCESS_KEY` and `S3_SECRET_KEY` are the bundled example. They are listed with their source and last four characters, read-only with "Set it in .env", because a stored value would not reach a client that already exists. A setting of your own typed `Credential` is listed the same way.

## Backends

`database` is the only backend today. The `secrets[...]` axis exists so external managers (HashiCorp Vault, a cloud secret manager) can plug in behind the same calls. A backend is a small protocol in `app/core/secrets.py` (`SecretStore`): a `name`, whether it is `writable`, and `get`, `put`, `delete` and `stored`.

A backend may be read-only by policy. Then the app reads from it but never writes to it: both Overseers drop their edit controls and say "Values are managed in Vault: change them there", and writes refuse with the same reason.

## Health

The component adds a `secrets` entry to the system health check:

- **Healthy**: "4 of 18 set, 1 stored here", with declared, set, stored and needed counts in the metadata.
- **Warning**: a needed key is missing (named), or `ENCRYPTION_KEY` is not set.
