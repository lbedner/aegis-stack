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

    That account is the bot's first **agent**. Each agent is a Google account of its own, with its own name in the call and its own sign-in: a work notetaker and a personal one, each invitee seeing a different name, each agent's meetings apart. Make another by signing it in under a name of its own:

    ```bash
    my-app meetings login --agent work --name "Work Notetaker" --email notes@work.example
    ```

    Each sign-in is kept under its own secret (the first's is `MEETINGS_BOT_LOGIN_SECRET`, `work`'s `MEETINGS_BOT_LOGIN_SECRET__WORK`). A meeting is sent as one agent: the first (`notetaker`) unless another is named. A stack from before agents keeps its sign-in and its meetings as the first agent's, with nothing to do.

    Each agent can also have its own **calendar**: what it is invited to. In the agent's Google Calendar, open Settings, set "Add invitations to my calendar" to "From everyone" (Google otherwise adds only invites from senders the account knows), then copy the calendar's "Secret address in iCal format" (under Integrate calendar) into a secret: the first agent's is `MEETINGS_BOT_CALENDAR_SECRET`, `work`'s `MEETINGS_BOT_CALENDAR_SECRET__WORK`. Set it in Overseer's Secrets, or:

    ```bash
    my-app secrets set MEETINGS_BOT_CALENDAR_SECRET
    ```

    The address reads everything on that calendar, so it is kept like the sign-in. Every minute the scheduler reads each agent's calendar again and keeps its meetings, from a month back to three months ahead, one row per time each happens (a repeating meeting expanded, with the times moved or cancelled on their own followed), with the link to join from the invite: the conference Google attached, or the first Meet, Teams or Zoom link in its location or description. A meeting taken off the calendar is dropped, unless the agent was already sent into it. An agent whose calendar cannot be read keeps what it had.

## What You Get

- **Meetings** - one row per call the bot is asked to join: the link, its platform, the name the bot joins as, and its status, with when it joined and left.
- **Platforms** - the platform comes from the link: Google Meet (`meet.google.com`), Microsoft Teams (`teams.microsoft.com`, `teams.live.com`) and Zoom's web links (`zoom.us/j/...`). Any other link is refused before anything is stored.
- **People** - everyone the owner's calls name, one person each across their meetings: a participant is that person as one call named them, so the same name in the owner's next meeting (as written, or ignoring case and spacing) is the same person, and their guide, their threads and whether they are you follow them from call to call.
- **Transcript** - one line per thing a participant said, timed in seconds from when the bot joined.
- **Audio** - what the bot hears, a second at a time, each second given to whoever was talking. See [What the bot hears](#what-the-bot-hears).
- **Notes** - once the bot has left, the meeting's summary, decisions, action items (who, what, and by when if it was said) and open questions, each a row citing the transcript lines it came from. See [Notes](#notes).
- **Commitments, contradictions and positions** - from each meeting, who said they would do what (for whom, by when), what was said one way and the opposite way, and where each person stands on a topic, each citing its lines; kept with the notes and gathered per person. See [Commitments, contradictions and positions](#commitments-contradictions-and-positions).
- **Me** - which speaker you are, picked in any meeting (nobody else in that meeting is). That person is you in every meeting they are in, and decides which action items are yours; your own guide is not written or listed.
- **Agents** - the Google accounts the bot joins as, each with its own name and sign-in; every meeting says which one went. See the warning above.
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

The browser closes whatever happens, so no Chrome outlives its meeting. Once it is out, the notes are written (below). A bot stopped from outside (Ctrl-C, its process shutting down) writes none; the page can.

`meetings join` runs the bot in the terminal and waits for it. The pages and the API hand it to the worker when the stack has one: each call is a job on the worker's own `meetings` queue, so a webserver restart (a reload, a deploy) leaves the call alone, and the queue's concurrency (`WORKER_QUEUES`) is how many calls run at once. The job has no timeout that ends a call and is never retried: a job delivered twice finds its meeting taken and does nothing. The `worker-meetings` container does not reload when code changes in dev (`WORKER_WATCH=false`), since a reload would end the call; restart it to pick up a change. A stack without a worker runs the bot in the background of the webserver instead, which ends the call when it restarts. Either way, a process that shuts down takes the bot out of the call (`left`).

A meeting the bot has not started yet is over as soon as it is asked to leave. While it runs it writes a heartbeat on the meeting every ten seconds, and reads back whether it has been asked to leave. A process that dies mid-call stops the heartbeat, and the webserver checks for that every minute: a meeting whose heartbeat is over a minute old is marked `failed` ("The app stopped during the meeting"). A call another process is still in keeps beating, so the check never touches it.

Every status change moves only from the status the bot expects, so a leave request (or a failure recorded elsewhere) is never overwritten by the bot's next step: it stops instead.

Everything the bot knows about Meet's page (its buttons, its chat, its captions, how it says you were turned away) lives in `app/services/meetings/meet.py`. When Meet changes its page, that module is the fix.

## What the bot hears

The bot's browser reads every audio stream the call sends it, as 16 kHz mono, and hands it to the bot a second at a time over the connection the bot already drives the browser with. No socket is opened for it, so nothing outside the bot's process can send audio in. A silent second is dropped in the browser.

Meet does not send one stream per person: it mixes the call into a few streams that follow the loudest speakers, so a stream never says who is talking. The captions do. Each second goes to the speaker whose caption changed nearest to when it was heard, allowing for captions showing up a moment after the words, once they have had time to catch up. A second no caption explains is `Unknown`.

When the call ends, how many seconds of each speaker the bot heard is kept with each of them (what no caption explained, with the meeting) (Overseer shows it as "Heard: Ada 4m 10s · Leonard 2m 30s"). The audio itself is not kept by default: set `MEETINGS_KEEP_AUDIO_DIR` to a folder to keep each speaker's audio there as a WAV, under the meeting's id (`<folder>/<id>/Ada.wav`), for checking what the bot heard.

## Notes

One pass of the `meeting-notes` agent (see [The writers are agents](#the-writers-are-agents)) over the finished transcript, with the transcript's line ids in front of each line. What comes back is checked against the transcript: an item citing a line that does not exist loses that citation. The call is metered like every other, as `meetings:notes` in AI spend.

The notes are written again on request (the page's "Write them again"), over the old ones: after switching to a better model, say. A model that fails leaves its reason, which the page shows above the notes the meeting already had: a failed rewrite never loses them. A meeting where nothing was said gets no notes.

Each item is kept as a row, citing its lines by foreign key, and each name the model gives (an action item's owner, who a commitment was made to) points at the person it is: someone in the call, by name as written or ignoring case and spacing, else someone the owner already knows. A name that is no one in the calls ("the board", a customer) is kept as written.

Notes need the AI service on pydantic-ai with a database (`ai_backend` other than `memory`). Without it the meeting keeps its transcript and the page shows that alone.

## Commitments, contradictions and positions

The same pass that writes the notes (same agent, same metering) also writes the meeting's threads, each citing the lines it came from:

- **Commitments** - who said they would do what, for whom and by when, in their own words ("I'll send it to you").
- **Earlier commitments raised** - a commitment from an earlier meeting that came up again: done, dropped, or only mentioned and still open.
- **Said both ways** - something said one way and the opposite way, by one person or two, in this meeting or against an earlier one, with the lines of both sides.
- **Where people stand** - each person's stance on the topics they spoke to, and where they stood before when it shifted.

So that a meeting can be read against the earlier ones, the model is also shown, from the owner's latest fifty meetings, the commitments the people in this one made or were made that are still open, and where each of them last stood on each topic, with the lines those rest on. What comes back is checked like the notes: a thread keeps only lines it was shown (a contradiction's other side may be an earlier meeting's line), a follow-up only names a commitment it was shown, and a thread left citing nothing is dropped.

The `meeting-notes` agent's seeded prompt says how to write them; each thread's field in the notes' schema says so too, so a project whose agent was seeded before them still gets them. Seeding never overwrites an agent row, so to give that agent the fuller prompt, set its prompt in Agents to `NOTES_PROMPT` from `app/services/meetings/domains/agents.py`.

They are kept with the meeting's notes, and writing the notes again writes them again. The next meeting's notes are shown the open commitments numbered `[C1]`, `[C2]`, and a follow-up names one by its number; a commitment is kept by its own id, so notes written again keep each commitment that cites a line it cited before, and whatever later meetings said of it still points at it. Gathered per person, they make a ledger across the owner's meetings: what the person said they would do and what was promised them, each with where it came up again and whether it was done; where they stood on each topic over time; and what they said both ways.

## How to work with each person

For everyone who speaks in an owner's meetings, a guide to working with them, read from what they say across those meetings: what they care about, how they like their information (big picture or detail, a demo or numbers, short or thorough), how they decide and commit, and what lands with them and what gets pushback. Every point cites the lines it rests on, so the read can be checked against what was said. It is only how they work: nothing about health, family, relationships, politics or religion, even when it came up.

Once the notes are written, the bot writes the guide of everyone in the meeting but the owner (the speaker "I am" names), one pass of the `meeting-guide` agent over the latest ten meetings of the owner's they spoke in, metered as `meetings:guide`. Someone with fewer than three lines across them gets none yet. Each meeting writes it again, so it firms up as meetings accrue; a write that fails keeps the last guide, with why. The owner's own note on a person (what they know that the meetings do not say) is kept across every rewrite and read with the meetings. Guides are the owner's own; Overseer's admin sees every owner's. Like the notes, they need the AI service on pydantic-ai with a database.

## Search

Every word said in a meeting, and every part of its notes, is searchable: the summary, the decisions, the action items, the open questions, and the commitments, follow-ups, contradictions and positions. A hit is the line itself, with its meeting, who said it and when in the call; a hit in the notes names its part and opens at the line it came from. Newest meeting first, each meeting's notes before its lines. Words match their other forms ("pricing" finds "priced"), and every word has to be there. It is search by words, not meaning: "pricing" does not find "$49 a month".

On PostgreSQL it is full-text search (English), with a GIN index over the transcript's lines and one over the note items, which the meetings revision adds. On SQLite it is FTS5: a search table over each of the two, holding only the index (the text stays in its own table), kept by triggers and made by every startup's `create_all` (filled from what is already there) since no model can describe them. Neither needs a dependency.

Each owner searches their own meetings; Overseer's admin searches every owner's. Overseer's chat has it too: the `meetings_search` tool, granted to the default agent when the meetings service seeds its agents, answers "what did Lawrence say about pricing?" from the transcripts, each line linked to the meeting at that line.

## The writers are agents

The notes and the guides are each written by an agent row the meetings service seeds at startup: `meeting-notes` and `meeting-guide`, under the "meetings" category in Overseer's Agents. Their prompt, model and sampling are edited there like any other agent's, and every prompt change is kept in its history. A row left as seeded runs on the model in force; one pinned to a model runs on that model. Seeding only adds a missing row, so an edit survives restarts and upgrades. While a row is missing or turned off, its built-in prompt runs on the model in force.

## The Meetings page

With the htmx frontend, `/meetings` (linked from the navbar) sends the bot and reads what came of it, no CLI needed (signing the bot in is still `meetings login`):

- **Meetings** - every meeting the bot was sent to, newest first, with its status, how long the bot was in it, and how many action items are yours. Paste a link, name the bot, and send it.
- **One meeting** - its status while the bot joins, waits and listens (the page keeps itself current, and stops once nothing is happening), a button to ask it to leave, then the notes: the summary, your action items, everyone's, the decisions and open questions. Each item links to the line it came from, in the transcript below.
- **Which speaker is you** - picked from the people who spoke. Your action items follow at once, with nothing written again.

Each meeting is its owner's: with the auth service a user sees only the meetings they sent the bot to.

## In Overseer

Overseer > Services > Meetings runs meetings as fully as the Meetings page does, across every owner: send the bot to a call from there (the meeting is the admin's own), and every owner's meetings are listed, newest first, with how many there are and how many the bot is in now. A row opens the meeting in the drawer: its status, owner and how long each speaker was heard, then the same notes and transcript as the page, with "I am" (which speaker the owner is, their action items first) and "Write them again". The drawer re-reads itself every few seconds while the bot is in or the notes are being written. From there the admin also asks the bot to leave a meeting it is still in, or deletes a meeting it is out of, with its transcript, notes and speakers, and anyone who spoke only in it with their guide. Whatever else cited only its lines goes with it: another meeting's note item, a guide's point, a contradiction left with one side.

Above the list, a search box searches every owner's transcripts and notes as you type ([Search](#search)); a hit opens its meeting in the drawer at the line, marked, with the hits kept above it.

A meeting's commitments, earlier commitments raised, contradictions and positions load into its drawer once its notes are there, each folding open to its lines (and the other side, or where it came up again).

The send form picks which agent goes, where there is more than one, and each meeting's row names its agent. The Agents tab lists every agent: its name, the name it joins as, its Google account, whether its sign-in still works (Signed in; Signed out once Google's session has run out, so sign it in again; Not signed in), and the meetings it is in now, each opening in the drawer.

Its People tab lists every owner's guides, latest written first; a row opens one in the drawer, each point folding open to the lines it rests on (each opening its meeting), then the person's open threads (what they said they would do and what was promised them, with whether it was done; where they stand; what they said both ways), with the owner's note and "Write it again".

The Flet dashboard (`/dashboard`) has the same: a Meetings card with the counts, opening a modal that sends the bot and lists every owner's meetings beside the selected one, read in full and followed while something is happening, with the same actions. A Search tab searches every owner's meetings and opens a hit's meeting at its line, a People tab does the same for the guides, an Agents tab lists the agents, whose picker sits beside the send box, and both meeting and guide panes show the threads.

## CLI

| Command | What it does |
|---------|--------------|
| `meetings login [--agent NAME] [--name NAME] [--email EMAIL] [--chrome PATH]` | Sign one of the bot's Google accounts in, once, in Chrome on this machine: the first agent unless `--agent` names another, made if new |
| `meetings join <link> [--agent NAME] [--bot-name NAME]` | Send the bot into a meeting as an agent (the first unless named) and wait until it leaves (Ctrl-C takes it out) |
| `meetings leave <id>` | Ask the bot to leave |
| `meetings list [-n LIMIT]` | The meetings, newest first |
| `meetings show <id>` | One meeting: its status and its transcript |

## API

| Route | What it does |
|-------|--------------|
| `POST /api/v1/meetings` | `{"url": ..., "agent": ..., "bot_name": ...}`: record the meeting and start the bot as `agent` (the first unless named; `422` for one there is not), joining as `bot_name` or the agent's own name; answers `202` before it joins |
| `GET /api/v1/meetings/{id}` | The meeting and its status |
| `GET /api/v1/meetings/{id}/threads` | Its commitments, earlier commitments raised, contradictions and positions, each with the lines it cites |
| `POST /api/v1/meetings/{id}/leave` | Ask the bot to leave |
| `GET /api/v1/meetings/search?q=` | The caller's meetings' lines and note items with the words, newest meeting first |

Overseer's routes, across every owner. Reading them takes an admin where the stack has auth; a change is an operator's (an admin, or without auth only the local dev build):

| Route | What it does |
|-------|--------------|
| `GET /api/v1/meetings/admin` | Every owner's meetings, newest first |
| `GET /api/v1/meetings/admin/agents` | Every agent, the first first: who it is, its sign-in (`Signed in`, `Signed out`, `Not signed in`), and the ids of the meetings it is in now |
| `GET /api/v1/meetings/admin/search?q=` | Search every owner's meetings |
| `GET /api/v1/meetings/admin/{id}` | One meeting with its notes (or why there are none), transcript, how long each speaker was heard (`heard_seconds`), and which speaker the owner is (`me`) |
| `GET /api/v1/meetings/admin/{id}/threads` | Its threads, as the owner's route reads them |
| `POST /api/v1/meetings/admin/{id}/leave` | Ask the bot to leave |
| `POST /api/v1/meetings/admin/{id}/me` | `{"name": ...}`: which speaker the owner is (`null`: nobody); returns the meeting read in full |
| `POST /api/v1/meetings/admin/{id}/notes` | Write the notes again, in the background; `409` while the bot is in, when nothing was said, or while a writer is at it |
| `DELETE /api/v1/meetings/admin/{id}` | Delete the meeting with its transcript, notes and speakers; `409` while the bot is in it |

How to work with each person. The caller's own guides under `/api/v1/meetings/people`; every owner's, for Overseer, under `/api/v1/meetings/admin/people`, read by an admin and changed by an operator:

| Route | What it does |
|-------|--------------|
| `GET .../people` | The guides, latest written first, each with the person it is to (`{"guide", "person", "owner_user_id"}`) |
| `GET .../people/{id}` | One guide, each part with its points and the lines they rest on, and the person's threads across the owner's meetings (`threads`) |
| `PUT .../people/{id}/note` | `{"note": ...}`: the owner's note on the person (blank clears it); returns the guide |
| `POST .../people/{id}/guide` | Write the guide again, in the background; `409` without a model or while it is being written |
