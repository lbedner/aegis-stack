# Documents Service

Durable storage for the paper an application accumulates: scans, statements, letters, forms. The bytes are addressed by their own content hash, the rows say what the file is and when it arrived, and what a document *means* belongs to whatever consumes it.

!!! info "Quick Start"
    Generate a project with the documents service:

    ```bash
    aegis init my-app --services documents
    cd my-app
    uv sync
    make serve
    ```

    Documents requires the `database` component; interactive generation adds it when needed. Without the `storage` component it keeps objects on disk under `STORAGE_ROOT`, which is a working default, not a placeholder.

## What You Get

- **Content-addressed storage** - every object is keyed `sha256/ab/cd/<digest>`, never by path. The same key resolves identically on a filesystem, in SeaweedFS, or in S3, so moving to a bucket later is a byte copy with no database change.
- **Dedupe that is enforced, not hoped for** - uploading the same bytes twice returns the existing document with `200` instead of creating a second one, and a partial unique index makes that true under concurrency.
- **A lifecycle** - a new version supersedes its predecessor rather than overwriting it, `protected` refuses deletion, and delete is a soft delete that frees the hash for re-filing later.
- **Page-addressed extraction** - each page is read once and stored with how it was read, so a claim made from a document can cite the page and the method. See [Extraction](extraction.md).
- **Free-form tags** - `GET /tags` returns them with counts. Tags rather than a taxonomy: what counts as a category differs per application.
- **An Overseer surface** - a Documents card and a three-tab modal (Documents, Activity, Tags) with a detail pane, a page strip, and a full-size page viewer with the transcript beside it.
- **A health check** - document and page counts, storage backend, and whether anything is waiting to be read.

## What It Is For

The service stores paper and reads it. What the paper *means* is the application's business, which is why the same store carries all of these:

- **An agency case file.** Letters arrive by post and email, each with a deadline and a case number, and the reply is more paper. Kinds and channels say where a document came from, `document_date` is the date on the letter rather than the day you scanned it, and supersession keeps last year's renewal readable when this year's replaces it.
- **Statements behind a finance app.** A monthly statement per account, filed as it arrives. Uploading the same PDF twice is one document, so a re-download after a failed sync costs nothing, and extraction turns a scan into text a reconciliation can quote.
- **Identity and authority documents.** A passport scan, a power of attorney, a signed form: the ones where deleting the wrong row is the expensive mistake. `protected` refuses deletion outright rather than warning about it.
- **Receipts and expenses.** Photographs of paper, which have no text layer at all, so every page goes through the vision reader and comes back searchable.
- **Whatever the chat surface was handed.** Attachments already live in the same content-addressed store, so a screenshot pasted into a conversation and a document uploaded through the API are the same bytes under the same key.

Two things stay out of scope on purpose: what a document obliges you to do, and who is allowed to see it. Deadlines, obligations and per-subject access belong to the application, not to a store of paper.

## Data Model

| Table | Key Columns |
|-------|-------------|
| `document` | `id`, `owner_user_id`, `title`, `kind`, `storage_key`, `storage_backend`, `content_hash`, `media_type`, `byte_size`, `page_count`, `document_date`, `received_at`, `source`, `channel`, `supersedes_id`, `protected`, `note`, `meta_data`, `created_at`, `updated_at`, `deleted_at` |
| `document_tag` | `id`, `document_id`, `label` — unique per document |
| `document_page` | `id`, `document_id`, `page_number`, `status`, `method`, `text`, `image_key`, `model`, `detail` — unique per page |

`kind` is constrained in the database to `letter`, `statement`, `form`, `identification`, `receipt`, `other`.

### The dedupe rule

`(owner_user_id, content_hash)` is unique among documents that are not deleted:

```
ix_document_owner_hash  UNIQUE (owner_user_id, content_hash) WHERE deleted_at IS NULL
```

Ingest reads before it writes, and two concurrent uploads of the same bytes can both miss that read, so the rule lives in the index rather than in the code path. It is partial for a reason: retiring a document must not stop the same paper being filed again later.

### The lifecycle

```
uploaded --> superseded by a newer version (supersedes_id points back)
    |
    +--> protected: delete refuses
    |
    +--> soft-deleted: deleted_at set, hash free to use again
```

- **Supersession keeps both.** A renewal letter that replaces last year's does not erase it; the new row points at the old one, and the old one stays readable. Anything that cited it still resolves.
- **`protected` is a refusal, not a warning.** Deleting a protected document raises `ProtectedDocumentError`, which the API returns as `409`.
- **Delete is soft.** The row keeps its bytes and its pages; only `deleted_at` is set.

## Where the Bytes Live

The service never touches a filesystem or a bucket directly. It calls the `ObjectStorage` protocol in `app/core/storage.py`, and `STORAGE_BACKEND` picks the implementation:

| Backend | Class | Where objects live |
|---|---|---|
| `filesystem` (default) | `FilesystemStorage` | under `STORAGE_ROOT`, content-addressed |
| `s3` | `S3Storage` | any S3-compatible endpoint; SeaweedFS in the dev stack |

Adding the [storage component](../../components/storage.md) switches the default and adds the dev container. Because keys are hashes, switching backends is a copy of objects, not a migration of rows.

## Generated Files

```
my-app/
├── app/services/documents/
│   ├── service.py            # DocumentService: ingest, store, list, tag, delete
│   ├── models.py             # document, document_tag, document_page
│   ├── queries.py            # the reads, batched (no N+1 on tags)
│   ├── health.py
│   └── domains/extraction/
│       ├── pages.py          # the run: which pages need reading, and what each becomes
│       ├── pdf.py            # pypdfium2: text layer and page rendering
│       ├── vision.py         # the reader for pages without a text layer
│       ├── dispatch.py       # worker when there is one, in-process when not
│       └── jobs.py           # the entry points a run is started through
├── app/components/backend/api/documents/
│   ├── router.py             # documents, tags, content
│   └── pages.py              # extract, pages, page image
├── app/components/frontend/dashboard/
│   ├── cards/documents_card.py
│   └── modals/documents_modal.py, documents_detail_pane.py,
│       documents_pages.py, documents_activity.py
└── tests/services/test_documents_service.py, test_document_extraction.py
    tests/api/test_documents_endpoints.py, test_document_pages.py
```

## Configuration

```bash
STORAGE_BACKEND=filesystem     # or s3, set for you by the storage component
STORAGE_ROOT=storage_data      # filesystem backend only
```

The S3 settings (`S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`) belong to the storage component and are documented with it.

## Health Status

| Condition | Status | Message |
|-----------|--------|---------|
| Documents stored, every page read | healthy | counts, and the storage backend in use |
| Pages waiting to be read | info | how many, and on which documents |
| Storage unreachable | unhealthy | the backend and the error |

The check reports the backend the service is actually using, so a project that
added the storage component sees `s3` here rather than what `.env` used to say.

## Next Steps

| Topic | Description |
|-------|-------------|
| **[API Reference](api.md)** | Every route, with curl examples |
| **[Extraction](extraction.md)** | How a page becomes text, and which model reads it |
| **[Dashboard](dashboard.md)** | The Overseer modal: documents, activity, and the page viewer |

---

**Related:**

- **[Services Overview](../index.md)** - Complete services architecture
- **[Storage Component](../../components/storage.md)** - S3 backend for the same keys
- **[Worker Component](../../components/worker/index.md)** - Where a background extraction runs
- **[Database Component](../../components/database.md)** - Database component details
