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

Only one runner takes a run, and only the runner that took it finishes it. A run whose runner went quiet fails once twice the runner's own time limit has passed (30 minutes by default).

## A run that is work

A question is answered once, from a worktree that is thrown away. Work is different: you want the changes kept, the agent to remember what it did, and to be able to take over yourself. A run asked on a branch and in a session does that.

- **The worktree stays.** The runner makes it under `<repo>-worktrees/<branch>` (or `--worktrees`) and leaves it there: on the branch as the repository or its remote has it, or on a new one cut from `--ref`. The run says where it is from the moment a runner takes it.
- **The app names the agent's session** when the run is asked (a run asked in none is given one when it is claimed). With the worktree, that is how you pick the work up: `cd <worktree> && claude --resume <session>`.
- **A later run of the same session continues it**, in the same worktree, with the resume form of the command.
- **The run says what it cost.** An agent reports what its whole session has cost so far; each run keeps what it added, so a session's cost is the sum of its runs'. That holds while the session stays on one machine: started afresh on another, the agent counts from zero again, and those runs keep no cost until it passes what was already counted. How long it took is the time between claimed and finished.

```python
from app.components.runner import runs

session = runs.new_session()
run = await runs.ask(
    db,
    owner_user_id=owner,
    kind="issue",
    subject_id="acme/app#12",
    action="agent",
    title="The export times out",  # what a list of runs calls it
    source="acme/app",  # and where it was asked
    prompt="Fix the export timing out.",
    branch="issue-12-export",
    session_id=session,
)
# Later, in the same session and worktree:
await runs.ask(db, ..., prompt="Now add a test.", branch="issue-12-export", session_id=session)
```

**The dev runner only reads.** Its default command runs the agent in plan mode, so a work run under `make serve` thinks and answers but changes nothing. To let runs change code, give the runner a command that may, and its resume form with it (see [In the dev stack](#in-the-dev-stack)): a command set without its resume form cannot continue a session, and the second run of one fails.

Things to know:

- **One driver at a time.** Do not drive a session from the runner and from your terminal at once: wait for the run to finish, or the two lose each other's turns.
- **A session lives where it began:** on the machine whose runner started it, in its worktree. With more than one runner, give work runs an action only one of them answers (`--action`).
- **Start or continue is the agent's to say.** The runner tries what the app expects and, if the agent refuses at once, the other form. So a run that timed out or was stopped does not leave its session stuck, and a command that worked for a while before failing is not run twice. Where both forms are refused, the run fails with what each said.
- **A branch is only a branch name** (`git check-ref-format`), and its worktree only a place under the worktrees folder; anything else fails the run before git is asked. A kept worktree that has been moved off its branch is not worked in.
- **Time.** A command is given 15 minutes (`--timeout`), then stopped with everything it started. Stopping the runner (Ctrl-C) stops its command the same way. Work usually wants longer.
- **Pushing is a press, never the agent's.** A run back on a branch says how many of its commits are not on the remote ("1 commit not on GitHub" in its drawer, `unpushed` on the run). **Push and open PR** in the drawer asks a `push` run, which the runner answers itself: it pushes the branch over HTTPS and opens its pull request on the repository's default branch, titled and described by the commits not yet pushed and closing the run's issue (`acme/app#12`), or links the one already open for the branch. It needs a fine-grained GitHub token for the repository (Contents and Pull requests, read and write) as `RUNNER_GITHUB_TOKEN` where it runs; without one, the push says so. Merging stays yours.
- **Cleaning up is yours.** A kept worktree stays until you remove it (`git worktree remove`).
- **On Linux**, the dev runner's container runs as root, so the worktrees and session files it makes are root-owned on the host.

## What a run is doing

While a run is going, the app knows the agent's last step: `Edit app/core/tokens.py`, `Bash Run the tests`, or that it is waiting on you. It is on the run (`activity`, and when, `activity_at`).

- **It is for now.** Once the agent ends its turn the run is doing nothing, and `activity` is empty. A run that was stopped or ran out of time keeps the step it was on.
- **A command is shown in the agent's words** for it where it gives any (`Bash Run the tests`), not as the command line, which can hold a secret. A file is shown by its place in the worktree, an address without its query.

The agent says so itself. Claude Code's hooks post each step to the app, signed with the runner's token, and the app finds the run by the agent's session. The runner fills the hooks in where its command says `{hooks}`:

```bash
--command 'claude -p {prompt} --session-id {session} --settings {hooks} ...'
```

The dev runner's default commands have it. A command of your own without `{hooks}` runs as before and reports nothing.

A session you pick up in your terminal reports only if you give it the same hooks and the runner's token. From the project folder on that machine:

```bash
my-app runner hooks > ~/runner-hooks.json
cd <worktree>
RUNNER_TOKEN=rnr_... claude --resume <session> --settings ~/runner-hooks.json
```

`runner hooks` prints them for the app as that machine reaches it (`--url` for another address). Its steps show on the latest run a runner took in the session. A step the app cannot be told about never holds the agent for more than a couple of seconds, and never fails it.

### Its session, as it goes

A run's drawer shows its agent's session as a terminal would: what it said, each tool it called with what it was given, and what the tool gave back, in order, followed as it goes and kept at the newest line unless you scroll up to read. The runner reads it from Claude Code's `--output-format stream-json --verbose` (the dev runner's default commands), one event per line, its last the result the run already reads, and posts what came about once a second, signed with its token, to the run it holds (`/lines`).

- **Kept with the run**, up to 500 lines of its own besides its hooks' 500 steps, each cut to 2,000 characters, and gone with the run.
- **What a tool gave back can hold a secret** (a file read, an environment printed). Each line, the run's step and what it came back with are redacted by the same rules as the errors Overseer keeps: a value set for a name like a credential's (`OPENAI_API_KEY=...`), an `Authorization` header, a URL's password, and a token by its prefix (`sk-`, `ghp_`, `github_pat_`, `xoxb-`, `AKIA`). Anything else a tool printed is kept as it printed it, and Overseer shows every owner's runs.
- **Another agent's command** that prints no such session sends none, and the drawer shows the steps its hooks posted.

## In Overseer

**Overseer > Runner** lists the newest 200 runs of every owner, newest first, and says so when older ones are left out. Each is marked with the icon of the agent that ran it, by the program its runner's command starts: `claude`, `gemini`, `opencode` and `cline` have one of their own. Any other program, and a run answered in the app, get a plain one, as does a command that starts through a launcher (`npx`, `python`). Runs a runner took before agents were recorded are taken to be `claude`'s, the default command's. The drawer names the agent beside its runner. and reads as what was asked, in its asker's words (`title`, and `source` for where it was asked; a run given neither reads as its subject), with how long it took, what it cost and how it went: Waiting, Running (with what its agent is doing), Answered, No answer (its command succeeded and said nothing, or its agent said it has none: the runner asks every question that is not work on a branch to end with a line `[no answer]` when it finds none, and reads that line off what it keeps), Done (work on a branch) or Failed. Runs asked in one place of one action fold into a row that holds them (a meeting's questions): how many, how long and how much together, and how they went. It unfolds to the runs, and opens by itself while one is going or failed in the last 7 days. A place is the run's `source`, so give runs that belong together the same one. Over the list: how many runs wait, how many a runner has, and what failed and what was spent in the last 7 days. The cost counts the runs still kept: a run replaced by asking the same thing again takes its cost with it, and a run that was stopped or timed out never said what it cost, so what was spent is at least that figure. Where runs of more than one action are listed, a chip keeps the list and the figures to one. Click a run to open it: what came back, who ran it, the worktree and session to pick it up with, and the prompt it was sent, folded. Reload the page for the next step.

The update that brings `title` and `source` names the runs meetings had already asked, in the same revision: each gets its question and its meeting.

The runner's health check counts the runs waiting and the runs a runner has, and says whether a runner is listening: it used its token in the last two minutes (asking for runs, or posting a step), or it is working on a run that is not yet overdue (a runner on a long step posts nothing until it is back). A run waiting while no runner that takes its owner's runs is listening is a warning: nothing will answer it. The dashboard's Runner card shows the same counts, and Overseer's home shows them on the Runner card there.

The dev stack's `runner` service shows on that page too, under **Container** and **Logs**.

## Running one

```bash
my-app runner token create laptop
export RUNNER_TOKEN=rnr_...
my-app runner run \
  --url https://my-app.example.com \
  --repo ~/code/my-service \
  --command 'claude -p {prompt} --session-id {session} --output-format stream-json --verbose --permission-mode plan --settings {hooks}' \
  --resume-command 'claude -p {prompt} --resume {session} --output-format stream-json --verbose --permission-mode plan --settings {hooks}'
```

Any headless agent works (`codex exec {prompt}`, `aider --message {prompt}`); one that answers with Claude Code's JSON result says what the run cost. The command above only reads (`--permission-mode plan`): a runner whose runs change code is given a command that may, and answers the actions that ask for it. Start more runners to answer more at once.

```bash
--command CMD         # Required: the command each run runs; {prompt} is its prompt
                      # (stdin without it), {session} the agent's session id,
                      # {hooks} the settings that make it say what it is doing
--resume-command CMD  # The command that continues a session; --command without it
--repo PATH           # Answer from a worktree of this repository
--ref REF             # What a new worktree checks out (origin/main)
--worktrees DIR       # Where a branch's worktree is kept (<repo>-worktrees)
--timeout SECONDS     # What a command is given before it is stopped (900)
--action NAME         # An action this runner answers (agent); repeat for more
--url URL             # The app (API_BASE_URL by default)
--token TOKEN         # Its runner token (or RUNNER_TOKEN)
--once                # Answer one waiting run and stop
--poll SECONDS        # How often it looks while idle
```

A token made with `--owner` claims that owner's runs only; one without claims every owner's.

## In the dev stack

`make serve` starts a `runner` service beside the app. It answers nothing until `.env.runner` has a token:

```bash
RUNNER_TOKEN=rnr_...
CLAUDE_CODE_OAUTH_TOKEN=...        # the agent's login (claude setup-token)
RUNNER_REPO=/Users/you/code/my-service
```

That is all it needs. Its command is Claude Code's, in a session, saying what it cost, and read-only:

```bash
# The defaults, as if set:
# RUNNER_COMMAND=claude -p {prompt} --session-id {session} --output-format stream-json --verbose --permission-mode plan --settings {hooks}
# RUNNER_RESUME_COMMAND=claude -p {prompt} --resume {session} --output-format stream-json --verbose --permission-mode plan --settings {hooks}
```

For runs that change code, set both forms to a command that may (here Claude Code accepting its own edits), and give work the room it needs:

```bash
RUNNER_COMMAND=claude -p {prompt} --session-id {session} --output-format stream-json --verbose --permission-mode acceptEdits --settings {hooks}
RUNNER_RESUME_COMMAND=claude -p {prompt} --resume {session} --output-format stream-json --verbose --permission-mode acceptEdits --settings {hooks}
RUNNER_TIMEOUT=3600
RUNNER_WORKTREES=/Users/you/code/worktrees/my-service
RUNNER_GITHUB_TOKEN=github_pat_...  # to push a run's branch and open its PR
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
    title="Why does the export time out?",  # what a list of runs calls it
    source="Support",  # and where it was asked
    prompt="Why does the export time out?",
)
later = await runs.about(db, "ticket", ["42"])  # its runs, oldest first
```

A runner answers the actions it was started with (`--action`, `agent` by default).

## API

A runner's routes take its token (`Authorization: Bearer rnr_...`), not a user.

| Route | What it does |
|-------|--------------|
| `POST /api/v1/runner/runs/claim` | `{"actions": [...]}`: the oldest waiting run of those actions among the token's owner's, now the runner's, with its prompt, its `session_id`, its `branch` where it has one, and whether to `resume` the session; `204` when there is none. The runner may say where it keeps worktrees (`worktrees`), how long it gives a command (`timeout`) and which agent it runs (`agent`) |
| `POST /api/v1/runner/runs/{id}/finish` | `{"ok": ..., "result": ..., "cost": ..., "worktree": ...}`: what the run came back with, what the agent says its session has cost so far and where its work is kept; `404` for a run this runner did not claim |
| `POST /api/v1/runner/runs/activity` | An agent's hook event, as the agent sends it: what the latest run a runner took in its session is doing, or nothing once it ends its turn. `204`, also for an event that says neither |
| `GET /api/v1/runner/tokens` | The caller's live runner tokens |
| `POST /api/v1/runner/tokens` | `{"name": ...}`: a runner token; `201` with its `value`, shown this once |
| `DELETE /api/v1/runner/tokens/{id}` | Revoke one; `404` for one that is not the caller's |

With auth, a token is its maker's. Without, every token is the operator's and claims every run, so making and revoking one over the API is an operator's change: let through on the local dev build only (`403` elsewhere), as MCP's tokens are. The CLI makes one anywhere it can run.

## Coming from meetings

The queue, the runner and its tokens were part of the meetings service. A stack updated across that change keeps its runs and tokens (the migration carries them over), and its dev stack keeps answering from `.env.meetings-runner` and the `MEETINGS_RUNNER_*` names until you move them to `.env.runner`. The commands moved: `meetings runner` is `runner run`, and `meetings runner-token` is `runner token`.
