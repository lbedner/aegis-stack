# Storage Component

Object storage for the files an application keeps: chat attachments, documents, anything addressed by its own content hash. An S3 backend that speaks to any S3-compatible endpoint, with [SeaweedFS](https://github.com/seaweedfs/seaweedfs) as the container the dev stack ships.

Use `aegis init my-project --components storage` or add it to an existing project with `aegis add storage`.

## What Storage Adds

- **An S3 backend** for the `ObjectStorage` protocol in `app/core/storage.py`. Same keys, same calls as the filesystem backend every stack already has; switching is a byte copy, not a migration.
- **A SeaweedFS service** in the compose stack with a named volume, S3 port only, for exercising the bucket path locally. Its own web UI and native APIs are an operator tool; nothing in the app calls them.
- **Presigned URLs** on the protocol: a time-limited link straight to an object. The filesystem backend returns `None` and serves through the app instead.
- **A health check, card and modal** in the dashboard: backend, endpoint, bucket, reachability, and object counts when the documents service is present.

Nothing names a vendor. Production points `S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_ACCESS_KEY` and `S3_SECRET_KEY` at AWS, a Garage box, or any other S3-compatible store, and the code is unchanged.

## Generated Files

```
my-project/
├── app/components/storage/
│   ├── s3.py                 # S3Storage: the protocol on a bucket
│   └── health.py             # Reachability and counts for the dashboard
├── app/components/frontend/dashboard/
│   ├── cards/storage_card.py
│   └── modals/storage_modal.py
└── tests/components/test_storage_s3.py   # moto-backed, no server needed
```

## Configuration

| Setting | Default | Meaning |
|---|---|---|
| `STORAGE_BACKEND` | `s3` when the component is selected, else `filesystem` | Which backend `get_storage()` builds |
| `S3_ENDPOINT_URL` | `http://seaweedfs:8333` in compose | Empty for AWS |
| `S3_BUCKET` | the project slug | Created on first use if missing |
| `S3_ACCESS_KEY`, `S3_SECRET_KEY` | placeholder values for SeaweedFS | Real credentials in production |
| `S3_REGION` | `us-east-1` | |
| `S3_PATH_STYLE` | `true` | Path-style addressing; most self-hosted stores need it |

## Moving an Existing Stack

Keys are `sha256/ab/cd/<digest>`, derived from the bytes. Copy the filesystem tree into the bucket under the same keys, set `STORAGE_BACKEND=s3`, and every stored reference resolves. Nothing in the database changes.

## Why SeaweedFS

MinIO stopped publishing community images in 2025 and archived its repository in 2026. SeaweedFS is Apache 2.0, one binary, and has run in production since 2012. It is only the dev container; the backend works against any S3-compatible endpoint.
