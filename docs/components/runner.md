# Runner

Work the app sends out to a coding agent. The app keeps a queue of runs; a runner on any machine with your repository and the agent's login claims each one, answers it with a headless command, and posts back what it printed. The agent never runs in the app.

```bash
aegis add runner
```

## What you get

- **A queue of runs.** A service asks a run of an action about something of its own (a kind and an id). Meetings asks its questions this way ("Ask agent").
- **The runner:** `my-app runner run`, a process that holds a token, talks only HTTP, and answers one run at a time, oldest first.
- **Runner tokens:** made, listed and revoked from the CLI and the API. Only a token's digest is kept; its value is shown once.
- **A `runner` service in the dev stack**, configured in `.env.runner`, so `make serve` answers runs without a second terminal.

## How a run goes

```
 a service asks  --->  run: asked
                       POST /runner/runs/claim   <---  runner claims the oldest
                                                       fresh worktree of --repo
                                                       runs --command
                       POST /runner/runs/{id}/finish <-- posts what it printed
                       run: done | failed
```

Only one runner takes a run, and only the runner that took it finishes it. A run whose runner stopped before it answered fails after 30 minutes.

## Running one

```bash
my-app runner token create laptop
export RUNNER_TOKEN=rnr_...
my-app runner run \
  --url https://my-app.example.com \
  --repo ~/code/my-service \
  --command 'claude -p {prompt} --permission-mode plan'
```

Any headless agent works (`codex exec {prompt}`, `aider --message {prompt}`). Start more runners to answer more at once.

```bash
--command CMD    # Required: the command each run runs; {prompt} is its prompt (stdin without it)
--repo PATH      # Answer from a fresh worktree of this repository
--ref REF        # What each worktree checks out (origin/main)
--action NAME    # An action this runner answers (agent); repeat for more
--url URL        # The app (API_BASE_URL by default)
--token TOKEN    # Its runner token (or RUNNER_TOKEN)
--once           # Answer one waiting run and stop
--poll SECONDS   # How often it looks while idle
```

A token made with `--owner` claims that owner's runs only; one without claims every owner's.

## In the dev stack

`make serve` starts a `runner` service beside the app. It answers nothing until `.env.runner` has a token:

```bash
RUNNER_TOKEN=rnr_...
CLAUDE_CODE_OAUTH_TOKEN=...        # the agent's login (claude setup-token)
RUNNER_REPO=/Users/you/code/my-service
RUNNER_COMMAND=claude -p {prompt} --permission-mode plan
```

The service sees your home directory at the same path, so a repository path reads as it does on your machine. `.env` never reaches it, so the agent does not hold the app's secrets.

## Asking a run from your own service

```python
from app.components.runner import runs

run = await runs.ask(
    db,
    owner_user_id=owner,
    kind="ticket",
    subject_id="42",
    action="agent",
    prompt="Why does the export time out?",
)
later = await runs.about(db, "ticket", ["42"])  # its runs, oldest first
```

A runner answers the actions it was started with (`--action`, `agent` by default).

## API

A runner's routes take its token (`Authorization: Bearer rnr_...`), not a user.

| Route | What it does |
|-------|--------------|
| `POST /api/v1/runner/runs/claim` | `{"actions": [...]}`: the oldest waiting run of those actions among the token's owner's, now the runner's, with its prompt; `204` when there is none |
| `POST /api/v1/runner/runs/{id}/finish` | `{"ok": ..., "result": ...}`: what the run came back with; `404` for a run this runner did not claim |
| `GET /api/v1/runner/tokens` | The caller's live runner tokens |
| `POST /api/v1/runner/tokens` | `{"name": ...}`: a runner token; `201` with its `value`, shown this once |
| `DELETE /api/v1/runner/tokens/{id}` | Revoke one; `404` for one that is not the caller's |

## Coming from meetings

The queue, the runner and its tokens were part of the meetings service. A stack updated across that change keeps its runs and tokens (the migration carries them over), and its dev stack keeps answering from `.env.meetings-runner` and the `MEETINGS_RUNNER_*` names until you move them to `.env.runner`. The commands moved: `meetings runner` is `runner run`, and `meetings runner-token` is `runner token`.
