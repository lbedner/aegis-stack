# Extraction

How a stored page becomes text, what it costs, and what happens when a page cannot be read.

!!! info "One Page, Read Once"
    Extraction is page-addressed: each page is read once and stored with **how** it was read. A second run skips what is already read, so re-running is cheap and safe. `?force=true` is how you ask for the work again.

## What You Get

- **The PDF's own text layer first** - free, exact, and enough for most digital documents
- **A vision model only for pages without one** - scans, photographs of paper, faxes
- **A row per page either way** - with `method`, the `model` that read it, and the reason when it could not be read
- **A rendered PNG per page** - stored once, content-addressed like everything else, and what the page viewer shows

## The Pipeline

```
document bytes
      |
      +-- pypdfium2 renders page N to PNG  --> stored (image_key)
      |
      +-- pypdfium2 reads page N text layer
              |
              +-- >= 10 characters  --> method="text_layer", model=None
              |
              +-- fewer, or none    --> vision model over the PNG
                                          |
                                          +-- ok      --> method="vision", model=<name>
                                          +-- refused --> status="unread", detail=<why>
```

The ten-character threshold is `MIN_TEXT_CHARS` in `app/services/documents/domains/extraction/pages.py`. A scanned page usually reports a handful of stray characters rather than none, which is why the test is a floor rather than a check for emptiness.

## Page Status

| `status` | `method` | Means |
|---|---|---|
| `read` | `text_layer` | the PDF carried the text; no model was called |
| `read` | `vision` | a model transcribed the rendered page; `model` says which |
| `unread` | `none` | it could not be read, and `detail` says why |

A page that fails is a row saying so, never an absence. That matters twice: the counts stay honest (`{"read": 0, "unread": 7}` is a run that did nothing useful), and a later re-run has something to retry.

## Which Model Reads a Page

The one the dashboard says is active. Extraction asks for the model currently
selected in the LLM catalog - the same selection `llm use` writes and the
chat surface reads - so changing the model changes what reads the next page,
with no restart and nothing to configure per service.

Each page records the model that read it, so a document read months apart by
two different models says so page by page.

!!! warning "A text-only model refuses the whole job"
    Select a model without vision and every scanned page comes back `unread`
    with `Multimodal data provided, but model does not support multimodal
    requests`. The run still reports `done`, because the job finished - the
    pages are what failed. The Activity tab colours that case as incomplete
    rather than as a success, and a forced re-run after switching models
    reads them.

Without the AI service in the stack there is no reader at all. Pages with a
text layer are still read; the rest are recorded `unread` with
`No vision model is available to read a page without a text layer.`

## Where It Runs

| Stack | Behaviour |
|---|---|
| with the `worker` component | queued; `POST .../extract?background=true` returns `202` and a job id |
| without it | in-process; the request returns the counts |

One dispatch decides, from what the project was generated with, so a service that never chose a worker keeps working exactly as it did. The task is registered on all three worker backends (arq, dramatiq, TaskIQ).

Progress is narrated into a shared job record - `Reading page 3 of 7...` - which the web server relays to anything watching, whether the work runs in-process or on a worker.

## Cost and Time

Every page without a text layer is one vision call. A seven-page scan is seven calls, and re-running with `?force=true` pays for all of them again. Two habits keep that in check:

- Let the default (no `force`) skip what is already read; the button in the dashboard does this and only offers a forced run once every page is read.
- Extract deliberately rather than on upload. The service stores paper the moment it arrives; reading it is a separate act.

## Next Steps

| Topic | Description |
|-------|-------------|
| **[API Reference](api.md)** | The extract route, its flags, and the page routes |
| **[Getting Started](index.md)** | What the service stores and the page data model |
| **[Dashboard](dashboard.md)** | Watching a run on the Activity tab |

---

**Related:**

- **[Background Jobs](../../components/worker/jobs.md)** - The job record, the streams, and adding one to a service
- **[Worker Component](../../components/worker/index.md)** - Where a background extraction runs
- **[AI Service](../ai/index.md)** - Providers, the LLM catalog, and the active-model selection
- **[Storage Component](../../components/storage.md)** - Where the page images live
