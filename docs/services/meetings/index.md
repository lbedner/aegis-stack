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
- **Owners** - a meeting belongs to whoever asked for the bot. Without an owner (no auth, the CLI) every meeting is in reach.

## How the bot runs a meeting

```
requested -> joining -> waiting -> in_call -> left
                           |          |
                           +----------+--> failed (with the reason)
```

1. It opens the meeting in the browser container, gives its name and asks to join.
2. It waits up to five minutes for the host to let it in. Refused or never admitted, the meeting ends as `failed` with the reason.
3. Once in, it posts in the meeting chat that it is taking notes. Some places require everyone's consent to record, so this is not optional.
4. It turns on Meet's captions, in its own view only (nobody else sees them), and keeps them as the transcript: one line per turn, under the speaker's name, timed from when it joined. A line Meet is still writing (it corrects words as it goes) is updated in place.
5. It leaves when the call ends, when it is removed, when it has been alone for two minutes, or when asked (`meetings leave`, `POST /api/v1/meetings/{id}/leave`), within ten seconds. Asked before it joins, it never does.

The browser closes whatever happens, so no Chrome outlives its meeting.

The bot runs inside the process that starts it: `meetings join` waits for it, and the API runs it in the background of the webserver, which takes it out of the call (`left`) when the webserver shuts down. While it runs it writes a heartbeat on the meeting every ten seconds, and reads back whether it has been asked to leave. A process that dies mid-call stops the heartbeat, and the webserver checks for that every minute: a meeting whose heartbeat is over a minute old is marked `failed` ("The app stopped during the meeting"). A call another process is still in keeps beating, so the check never touches it.

Every status change moves only from the status the bot expects, so a leave request (or a failure recorded elsewhere) is never overwritten by the bot's next step: it stops instead.

Everything the bot knows about Meet's page (its buttons, its chat, its captions, how it says you were turned away) lives in `app/services/meetings/meet.py`. When Meet changes its page, that module is the fix.

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
