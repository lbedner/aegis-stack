# API Reference

Complete reference for all documents API endpoints. All routes are mounted under:

```
http://localhost:8000/api/v1/documents
```

Extraction jobs are watched through the generic jobs surface at `/api/v1/jobs`, documented in [Background Jobs](../../components/worker/jobs.md).

---

## Upload

```bash
curl -X POST http://localhost:8000/api/v1/documents \
  -F "file=@renewal-letter.pdf" \
  -F "title=Medicaid renewal RFI" \
  -F "kind=letter"
```

| Status | Meaning |
|:---:|---|
| `201` | stored; a new document |
| `200` | these exact bytes are already stored, and this is that document |

The `200` is the dedupe rule answering, not an error. Fields: `file` (required), `title`, `kind`, `document_date`, `source`, `channel`, `note`.

---

## List and read

```bash
GET /api/v1/documents?page=1&page_size=50&kind=letter&tag=medicaid&search=renewal
GET /api/v1/documents/{id}
GET /api/v1/documents/{id}/content      # the bytes, with their media type
GET /api/v1/documents/tags              # every tag with its count
```

`include_superseded=true` adds documents a newer version replaced; they are hidden by default.

---

## Update, tag, delete

```bash
PATCH  /api/v1/documents/{id}           # title, kind, document_date, note,
                                        # channel, supersedes_id, protected
POST   /api/v1/documents/{id}/tags      # {"label": "medicaid"}
DELETE /api/v1/documents/{id}/tags/{label}
DELETE /api/v1/documents/{id}           # soft delete
```

| Status | When |
|:---:|---|
| `204` | deleted |
| `409` | the document is `protected` |
| `404` | no such document for this owner |

Setting `supersedes_id` is how a new version retires an old one; the service refuses a document that supersedes itself, or one that is already superseded by something else.

---

## Extraction

```bash
POST /api/v1/documents/{id}/extract                        # in-process, returns counts
POST /api/v1/documents/{id}/extract?background=true        # queued, returns a job id
POST /api/v1/documents/{id}/extract?force=true             # re-read pages already read
```

| Status | Body |
|:---:|---|
| `200` | `{"read": 7, "unread": 0, "skipped": 0}` |
| `202` | `{"job_id": "cc35bde2..."}` — with `background=true` |
| `502` | the row outlived its object: storage no longer has those bytes |

Without `force`, pages already read are skipped, so a second run on a fully-read document returns all zeros with `skipped` set. See [Extraction](extraction.md) for what happens to each page.

---

## Pages

```bash
GET /api/v1/documents/{id}/pages                  # one row per page
GET /api/v1/documents/{id}/pages/{number}         # that page with its text
GET /api/v1/documents/{id}/pages/{number}/image   # the rendered PNG
```

A page row carries `status` (`read` or `unread`), `method` (`text_layer`, `vision`, or `none`), `model` when a model read it, and `detail` — the reason, when a page could not be read. A page that failed is a row saying so, never an absence.

---

## Watching a background extraction

```bash
JOB=$(curl -s -X POST "http://localhost:8000/api/v1/documents/2/extract?background=true" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")

curl -N http://localhost:8000/api/v1/jobs/$JOB/events
```

```
event: status
data: {"job_id": "...", "status": "running", "label": "Reading page 2 of 7..."}

event: status
data: {"job_id": "...", "status": "done", "result": {"read": 7, "unread": 0}}
```

The stream sends label updates and then exactly one terminal frame. `GET /api/v1/jobs` lists every job, running first; `GET /api/v1/jobs/events` is the same feed for all of them at once, which is what the modal's Activity tab reads.

---

**See also:**

- **[Getting Started](index.md)** - Service overview and data model
- **[Dashboard](dashboard.md)** - The Overseer modal
- **[Extraction](extraction.md)** - What each page status means
- **[Background Jobs](../../components/worker/jobs.md)** - The surface behind `background=true`
