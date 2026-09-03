# Examples

## Storing and Reading Bytes

Any service reaches storage the same way, whichever backend the project runs:

```python
from app.core.storage import get_storage


async def store_and_read(pdf_bytes: bytes) -> None:
    storage = get_storage()

    key = await storage.put(pdf_bytes, content_type="application/pdf")
    # 'sha256/9f/2c/9f2c...'

    data = await storage.get(key)          # bytes, or None
    exists = await storage.exists(key)
    removed = await storage.delete(key)    # False when there was nothing there
```

Keep the key. It is what a database row should store, alongside the backend name if the row might outlive a migration, which is exactly what the documents service records.

## A Link Instead of a Proxy

Serving a 40 MB scan through the app costs a worker for the length of the download. A presigned URL hands the browser a time-limited link to the object itself:

```python
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import RedirectResponse

from app.core.storage import get_storage

router = APIRouter()


@router.get("/documents/{key:path}")
async def download(key: str) -> Response:
    storage = get_storage()
    url = await storage.presigned_url(key, expires_seconds=600)
    if url is not None:
        return RedirectResponse(url)

    data = await storage.get(key)          # no link to hand out: proxy it
    if data is None:
        raise HTTPException(status_code=404)
    return Response(data, media_type="application/pdf")
```

`None` is not a failure. The filesystem backend has nothing to link to, so the fallback reads the bytes through the same protocol rather than reaching for a path. A caller that handles both cases works on every stack, and the same code gets faster when the project adopts a bucket.

## Testing Against Storage

Swap the backend for the duration of a test; nothing else changes:

```python
import pytest

from app.core.storage import FilesystemStorage, set_storage


@pytest.fixture(autouse=True)
def _storage(tmp_path):
    set_storage(FilesystemStorage(tmp_path))
    yield
    set_storage(None)
```

The S3 backend's own tests use [moto](https://github.com/getmoto/moto), so they need no server and no credentials.

## Moving a Running Project to a Bucket

Keys are derived from the bytes, so nothing in the database has to change. The move is a copy of objects and a setting:

```bash
# 1. add the component: the backend, the compose service, the card
aegis add storage
```

Adding it makes `s3` the default, so hold the app on disk while the copy runs:

```ini title=".env"
STORAGE_BACKEND=filesystem
```

```bash
# 2. copy what is already stored, preserving the key layout
aws s3 sync storage_data/sha256 s3://my-app/sha256
```

```ini title=".env"
# 3. point the app at the bucket
STORAGE_BACKEND=s3
S3_ENDPOINT_URL=https://s3.example.com
S3_BUCKET=my-app
```

Every stored reference resolves afterwards, because every reference is a key rather than a path.

!!! tip "Verify before switching, not after"
    Adding the storage component makes `s3` the default, so pin `STORAGE_BACKEND=filesystem` in `.env` before the copy and only change it to `s3` once the objects are across. The dashboard's storage card reports reachability and object counts, so a bucket that is missing objects is visible before anything reads from it.

Going the other way works identically: copy the bucket down and set `STORAGE_BACKEND=filesystem`. That is worth knowing for a local reproduction of a production bug.

## Next Steps

| Topic | Description |
|-------|-------------|
| **[Configuration](configuration.md)** | Settings, targets, and the dev container |
| **[Getting Started](index.md)** | The protocol and content-addressed keys |

---

**Related:**

- **[Documents Service](../../services/documents/extraction.md)** - Page images stored the same way
