# Storage Component

Object storage for the files an application keeps: chat attachments, documents, anything worth more than the request that uploaded it. An S3 backend that speaks to any S3-compatible endpoint, with [SeaweedFS](https://github.com/seaweedfs/seaweedfs) as the container the dev stack ships.

!!! info "Quick Start"
    ```bash
    aegis init my-project --components storage
    cd my-project
    make serve
    ```

    Or add it to a project that has been running on the filesystem: `aegis add storage`. That switches the default backend to `s3`, so files already written to disk are no longer where the app looks. Pin `STORAGE_BACKEND=filesystem` until the objects are copied across; see [Examples](examples.md#moving-a-running-project-to-a-bucket).

## What You Get

- **An S3 backend** for the `ObjectStorage` protocol every stack already has. Same keys, same calls as the filesystem backend; switching is a byte copy, not a migration.
- **A SeaweedFS service** in the compose stack, S3 port only, with a named volume, enough to exercise the bucket path locally. Its web UI and native APIs are an operator tool; nothing in the app calls them.
- **Presigned URLs**: a time-limited link straight to an object, for handing a browser a file without proxying it. The filesystem backend returns `None` and serves through the app instead.
- **A health check, card and modal**: backend, endpoint, bucket, reachability, and object counts when the documents service is present.

Nothing names a vendor. Production points `S3_ENDPOINT_URL` and the credentials at AWS, a Garage box, or any other S3-compatible store, and the code is unchanged.

## The One Decision Everything Rests On

A key is derived from the bytes, never from a filename or a path:

```
sha256/ab/cd/<64-hex-digest>
```

That is why the backend can change later without a migration. The same key resolves identically on a disk and in a bucket, so adopting object storage is a copy of objects rather than a rewrite of rows. Two consequences worth knowing:

- **Identical bytes are one object.** Uploading the same file twice stores it once; whether that is one *row* is the caller's business (the documents service enforces it with a unique index).
- **Keys are validated, not trusted.** They arrive from database columns and API payloads, so a backend checks the shape before touching anything: a traversal in a key must not reach a file it was never given.

## The Protocol

`app/core/storage.py` defines what every backend can do, and nothing more:

| Method | Answers |
|--------|---------|
| `put(data, *, content_type=None)` | stores the bytes, returns the key they now live under |
| `get(key)` | the bytes, or `None` when nothing is stored there |
| `exists(key)` | whether an object is there |
| `delete(key)` | `True` when this call removed something; absence is an answer, not an error |
| `presigned_url(key, *, expires_seconds=600)` | a direct link, or `None` when this backend can only serve through the app |

A service calls `get_storage()` and gets whichever backend the project configured. Nothing outside a backend builds a path.

## Generated Files

```
my-project/
├── app/core/storage.py           # the protocol + FilesystemStorage (always present)
├── app/components/storage/
│   ├── s3.py                     # S3Storage: the protocol on a bucket
│   └── health.py                 # reachability and counts for the dashboard
├── app/components/frontend/dashboard/
│   ├── cards/storage_card.py
│   └── modals/storage_modal.py
└── tests/components/test_storage_s3.py   # moto-backed, no server needed
```

## Why SeaweedFS

MinIO stopped publishing community images in 2025 and archived its repository in 2026. SeaweedFS is Apache 2.0, one binary, and has run in production since 2012. It is only the dev container: the backend works against any S3-compatible endpoint, and production is expected to point elsewhere.

## Next Steps

| Topic | Description |
|-------|-------------|
| **[Configuration](configuration.md)** | Every setting, and what each S3-compatible target needs |
| **[Examples](examples.md)** | Storing and reading bytes, presigned URLs, moving a running project |

---

**Related:**

- **[Components Overview](../index.md)** - Infrastructure layer
- **[Documents Service](../../services/documents/index.md)** - The largest consumer: paper, deduped and page-addressed
