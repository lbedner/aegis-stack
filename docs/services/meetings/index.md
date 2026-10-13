# Meetings Service

A bot that joins a call as a visible, announced participant, and keeps who was there and what each of them said. It joins Google Meet today; Teams and Zoom come next.

!!! info "Quick Start"
    Generate a project with the meetings service:

    ```bash
    aegis init my-app --services meetings
    cd my-app
    my-app meetings join https://meet.google.com/abc-defg-hij
    my-app meetings list
    my-app meetings show 1
    ```

    With the htmx frontend, the same is a page at `/meetings`.

    Meetings requires the `database` component and brings the `browser` component, the browser the bot joins through.

!!! warning "The bot needs its own Google account"
    Meet turns away a browser that is not signed in to Google. Make the bot a Google account of its own (never yours: the bot acts as whoever it is signed in as), then sign it in once:

    ```bash
    my-app meetings login
    ```

    This opens Chrome on this machine at Google's sign-in. Sign in as the bot, then quit Chrome (Cmd+Q / Ctrl+Q), and the sign-in is kept, encrypted, in the secrets store, where the bot finds it from the CLI and the webserver alike. It needs the `secrets` component (`aegis add secrets`) and an `ENCRYPTION_KEY` in `.env`. Until it is signed in, the bot joins as a guest, which only meetings that admit guests let in.

## What You Get

- **Meetings** - one row per call the bot is asked to join: the link, its platform, the name the bot joins as, and its status, with when it joined and left.
- **Platforms** - the platform comes from the link: Google Meet (`meet.google.com`), Microsoft Teams (`teams.microsoft.com`, `teams.live.com`) and Zoom's web links (`zoom.us/j/...`). Any other link is refused before anything is stored.
- **Participants** - whoever the call names, by display name and the platform's own id when it gives one. A participant can be linked to a user, to say "this speaker is me".
- **Transcript** - one line per thing a participant said, timed in seconds from when the bot joined.
- **Audio** - what the bot hears, a second at a time, each second given to whoever was talking. See [What the bot hears](#what-the-bot-hears).
- **Notes** - once the bot has left, the meeting's summary, decisions, action items (who, what, and by when if it was said) and open questions, each citing the transcript lines it came from. See [Notes](#notes).
- **Me** - which speaker you are in a meeting, by name. It decides which action items are yours, and your next meeting starts from the same name when that person spoke in it too.
- **Owners** - a meeting belongs to whoever asked for the bot. Without an owner (no auth, the CLI) every meeting is in reach.

## How the bot runs a meeting

```
requested -> joining -> waiting -> in_call -> left
                           |          |
                           +----------+--> failed (with the reason)
```

1. It opens the meeting in the browser container, gives its name and asks to join.
2. It waits up to five minutes for the host to let it in. Refused or never admitted, the meeting ends as `failed` with the reason.
3. Once in, it answers whatever Meet puts over the call: a meeting with Gemini (or another notetaker) taking notes asks every newcomer to confirm with "Join now", and camera tips ask for "Got it". Unanswered, they cover the chat, the captions and Leave. Then it posts in the meeting chat that it is taking notes. Some places require everyone's consent to record, so this is not optional.
4. It turns on Meet's captions, in its own view only (nobody else sees them), and keeps them as the transcript: one line per turn, under the speaker's name, timed from when it joined. A line Meet is still writing (it corrects words as it goes) is updated in place, and keeps the time it was first captioned. Meet keeps a long turn short on screen by trimming its start as it grows; the line keeps the whole turn.
5. It leaves when the call ends, when it is removed, when it has been alone for two minutes, or when asked (`meetings leave`, `POST /api/v1/meetings/{id}/leave`), within ten seconds. Asked before it joins, it never does.

The browser closes whatever happens, so no Chrome outlives its meeting. Once it is out, the notes are written (below). A bot stopped from outside (Ctrl-C, the webserver shutting down) writes none; the page can.

The bot runs inside the process that starts it: `meetings join` waits for it, and the API runs it in the background of the webserver, which takes it out of the call (`left`) when the webserver shuts down. While it runs it writes a heartbeat on the meeting every ten seconds, and reads back whether it has been asked to leave. A process that dies mid-call stops the heartbeat, and the webserver checks for that every minute: a meeting whose heartbeat is over a minute old is marked `failed` ("The app stopped during the meeting"). A call another process is still in keeps beating, so the check never touches it.

Every status change moves only from the status the bot expects, so a leave request (or a failure recorded elsewhere) is never overwritten by the bot's next step: it stops instead.

Everything the bot knows about Meet's page (its buttons, its chat, its captions, how it says you were turned away) lives in `app/services/meetings/meet.py`. When Meet changes its page, that module is the fix.

## What the bot hears

The bot's browser reads every audio stream the call sends it, as 16 kHz mono, and hands it to the bot a second at a time over the connection the bot already drives the browser with. No socket is opened for it, so nothing outside the bot's process can send audio in. A silent second is dropped in the browser.

Meet does not send one stream per person: it mixes the call into a few streams that follow the loudest speakers, so a stream never says who is talking. The captions do. Each second goes to the speaker whose caption changed nearest to when it was heard, allowing for captions showing up a moment after the words, once they have had time to catch up. A second no caption explains is `Unknown`.

When the call ends, how many seconds of each speaker the bot heard is kept with the meeting (Overseer shows it as "Heard: Ada 4m 10s · Leonard 2m 30s"). The audio itself is not kept by default: set `MEETINGS_KEEP_AUDIO_DIR` to a folder to keep each speaker's audio there as a WAV, under the meeting's id (`<folder>/<id>/Ada.wav`), for checking what the bot heard.

## Notes

One pass of the active model (the one Overseer's AI page selects) over the finished transcript, with the transcript's line ids in front of each line. What comes back is checked against the transcript: an item citing a line that does not exist loses that citation. The call is metered like every other, as `meetings:notes` in AI spend.

The notes are written again on request (the page's "Write them again"), over the old ones: after switching to a better model, say. A model that fails leaves its reason, which the page shows. A meeting where nothing was said gets no notes.

Notes need the AI service on pydantic-ai with a database (`ai_backend` other than `memory`). Without it the meeting keeps its transcript and the page shows that alone.

## The Meetings page

With the htmx frontend, `/meetings` (linked from the navbar) sends the bot and reads what came of it, no CLI needed (signing the bot in is still `meetings login`):

- **Meetings** - every meeting the bot was sent to, newest first, with its status, how long the bot was in it, and how many action items are yours. Paste a link, name the bot, and send it.
- **One meeting** - its status while the bot joins, waits and listens (the page keeps itself current, and stops once nothing is happening), a button to ask it to leave, then the notes: the summary, your action items, everyone's, the decisions and open questions. Each item links to the line it came from, in the transcript below.
- **Which speaker is you** - picked from the people who spoke. Your action items follow at once, with nothing written again.

Each meeting is its owner's: with the auth service a user sees only the meetings they sent the bot to.

## In Overseer

Overseer > Services > Meetings runs meetings as fully as the Meetings page does, across every owner: send the bot to a call from there (the meeting is the admin's own), and every owner's meetings are listed, newest first, with how many there are and how many the bot is in now. A row opens the meeting in the drawer: its status, owner and how long each speaker was heard, then the same notes and transcript as the page, with "I am" (which speaker the owner is, their action items first) and "Write them again". The drawer re-reads itself every few seconds while the bot is in or the notes are being written. From there the admin also asks the bot to leave a meeting it is still in, or deletes a meeting it is out of, with its transcript, notes and speakers.

The Flet dashboard (`/dashboard`) has the same: a Meetings card with the counts, opening a modal that sends the bot and lists every owner's meetings beside the selected one, read in full and followed while something is happening, with the same actions.

## CLI

| Command | What it does |
|---------|--------------|
| `meetings login [--chrome PATH]` | Sign the bot's Google account in, once, in Chrome on this machine |
| `meetings join <link> [--bot-name NAME]` | Send the bot into a meeting and wait until it leaves (Ctrl-C takes it out) |
| `meetings leave <id>` | Ask the bot to leave |
| `meetings list [-n LIMIT]` | The meetings, newest first |
| `meetings show <id>` | One meeting: its status and its transcript |

## API

| Route | What it does |
|-------|--------------|
| `POST /api/v1/meetings` | `{"url": ..., "bot_name": ...}`: record the meeting and start the bot; answers `202` before it joins |
| `GET /api/v1/meetings/{id}` | The meeting and its status |
| `POST /api/v1/meetings/{id}/leave` | Ask the bot to leave |

Overseer's routes, across every owner. Reading them takes an admin where the stack has auth; a change is an operator's (an admin, or without auth only the local dev build):

| Route | What it does |
|-------|--------------|
| `GET /api/v1/meetings/admin` | Every owner's meetings, newest first |
| `GET /api/v1/meetings/admin/{id}` | One meeting with its notes (or why there are none), transcript, and how long each speaker was heard |
| `POST /api/v1/meetings/admin/{id}/leave` | Ask the bot to leave |
| `POST /api/v1/meetings/admin/{id}/me` | `{"name": ...}`: which speaker the owner is (`null`: nobody); returns the meeting read in full |
| `POST /api/v1/meetings/admin/{id}/notes` | Write the notes again, in the background; `409` while the bot is in, when nothing was said, or while a writer is at it |
| `DELETE /api/v1/meetings/admin/{id}` | Delete the meeting with its transcript, notes and speakers; `409` while the bot is in it |
