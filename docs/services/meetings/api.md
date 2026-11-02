# API Reference

## The owner's routes

| Route | What it does |
|-------|--------------|
| `POST /api/v1/meetings` | `{"url": ..., "agent": ..., "bot_name": ...}`: record the meeting and start the bot as `agent` (the first unless named; `422` for one there is not), joining as `bot_name` or the agent's own name; answers `202` before it joins |
| `GET /api/v1/meetings/{id}` | The meeting and its status |
| `GET /api/v1/meetings/{id}/threads` | Its commitments, earlier commitments raised, contradictions and positions, each with the lines it cites |
| `POST /api/v1/meetings/{id}/leave` | Ask the bot to leave |
| `GET /api/v1/meetings/search?q=` | The caller's meetings' lines and note items with the words, newest meeting first |
| `GET /api/v1/meetings/{id}/moments` | What the call threw up (its questions), each with who said it, the actions it offers and the runs asked of it |
| `POST /api/v1/meetings/{id}/moments/find` | Read the call over again for moments: what it holds after |
| `POST /api/v1/meetings/{id}/moments/{moment_id}/runs` | `{"action": ...}`: ask an action of a moment; `202` with the run, `404` for an action that cannot be asked (a browser one) |
| `POST /api/v1/meetings/{id}/lines/{line_id}/about` | What a line is about (or, with `?part=component:scheduler`, the part it names), as Illiana says it to the meeting's owner: `{"summary": ..., "card_id": ...}` (the card she drew of the part it names, or `null`); `404` for a line the meeting does not hold, or a stack without her |
| `GET /api/v1/meetings/runner-tokens` | The caller's live runner tokens |
| `POST /api/v1/meetings/runner-tokens` | `{"name": ...}`: a runner token; `201` with its `value`, shown this once |
| `DELETE /api/v1/meetings/runner-tokens/{id}` | Revoke one; `404` for one that is not the caller's |

## The runner's routes

A runner's routes take its token (`Authorization: Bearer mrt_...`), not a user. See [The runner](moments.md#the-runner).

| Route | What it does |
|-------|--------------|
| `POST /api/v1/meetings/runs/claim` | `{"actions": [...]}`: the oldest waiting run of those actions among the token's owner's meetings, now the runner's, with its prompt; `204` when there is none |
| `POST /api/v1/meetings/runs/{id}/finish` | `{"ok": ..., "result": ...}`: what the run came back with |

## Overseer's routes

Across every owner. Reading them takes an admin where the stack has auth; a change is an operator's (an admin, or without auth only the local dev build):

| Route | What it does |
|-------|--------------|
| `GET /api/v1/meetings/admin` | Every owner's meetings, newest first |
| `GET /api/v1/meetings/admin/agents` | Every agent, the first first: who it is, its sign-in (`Signed in`, `Signed out`, `Not signed in`), and the ids of the meetings it is in now |
| `PUT /api/v1/meetings/admin/agents/{name}/owner` | Who owns a meeting the agent joins from its calendar when nobody on the invite has an account here (`{"user_id": 3}`, or `null` for nobody); 422 for an id nobody here has |
| `PUT /api/v1/meetings/admin/agents/{name}/{switch}` | One of the agent's switches, `{"on": false}` to turn it off: `camera`, whether its camera shows its card in a call; `answers_anyone`, whether anyone in a call may ask it something by name (off: only the meeting's owner) |
| `POST /api/v1/meetings/admin/agents/{name}/image` | The picture on the agent's card (multipart `file`: PNG, JPEG, WebP, GIF or SVG, up to 5 MB); 422 for anything else |
| `GET /api/v1/meetings/admin/agents/{name}/image` | The agent's picture as uploaded; 404 when it has none |
| `DELETE /api/v1/meetings/admin/agents/{name}/image` | The agent back to its initials |
| `GET /api/v1/meetings/admin/owners` | Everyone a meeting can be given to, by email (`id`, `email`); empty without auth |
| `GET /api/v1/meetings/admin/calendar?first=&last=&tz=&agent=` | Every agent's meetings (`agent`'s only, when named) from `first` to `last`, whole days in time zone `tz` (default UTC), up to six weeks: each with its agent and color, title, start and end, link, organizer, everyone invited (`emails`), where it stands (`state`: the call's status once the agent was sent in, else `upcoming`, `missed`, `cancelled`, `no_link`, `cannot_join` or `sent`) and the meeting it became |
| `GET /api/v1/meetings/admin/calendar/{event_id}?tz=` | One meeting on a calendar: all of the above, what its organizer wrote (`description`, Google's join and dial-in lines left out), and who is invited (`invited`: each email, with the name and color of whoever spoke on its link and plainly is them) |
| `POST /api/v1/meetings/admin/{id}/owner` | Give a meeting nobody owns to someone (`{"user_id": 3}`), its people and action items with it; 409 if someone owns it, 422 for an id nobody here has |
| `GET /api/v1/meetings/admin/search?q=` | Search every owner's meetings |
| `GET /api/v1/meetings/admin/{id}` | One meeting with its notes (or why there are none), transcript, how long each speaker was heard (`heard_seconds`), each speaker's and action item owner's color in the chart ramp (`voices`), and which speaker the owner is (`me`) |
| `GET /api/v1/meetings/admin/{id}/threads` | Its threads, as the owner's route reads them |
| `GET /api/v1/meetings/admin/{id}/moments` | Its moments, as the owner's route reads them |
| `POST /api/v1/meetings/admin/{id}/moments/find` | Its call read over again |
| `POST /api/v1/meetings/admin/{id}/moments/{moment_id}/runs` | Ask an action of one |
| `POST /api/v1/meetings/admin/{id}/lines/{line_id}/about` | Ask Illiana what one of its lines is about, as its owner (she reads every part, as an admin) |
| `POST /api/v1/meetings/admin/{id}/leave` | Ask the bot to leave |
| `POST /api/v1/meetings/admin/{id}/me` | `{"name": ...}`: which speaker the owner is (`null`: nobody); returns the meeting read in full |
| `POST /api/v1/meetings/admin/{id}/notes` | Write the notes again, in the background; `409` while the bot is in, when nothing was said, or while a writer is at it |
| `DELETE /api/v1/meetings/admin/{id}` | Delete the meeting with its transcript, notes and speakers; `409` while the bot is in it |

## People

How to work with each person. The caller's own guides under `/api/v1/meetings/people`; every owner's, for Overseer, under `/api/v1/meetings/admin/people`, read by an admin and changed by an operator:

| Route | What it does |
|-------|--------------|
| `GET .../people` | The guides, latest written first, each with the person it is to (`{"guide", "person", "owner_user_id"}`) |
| `GET .../people/{id}` | One guide, each part with its points and the lines they rest on, and the person's threads across the owner's meetings (`threads`) |
| `PUT .../people/{id}/note` | `{"note": ...}`: the owner's note on the person (blank clears it); returns the guide |
| `POST .../people/{id}/guide` | Write the guide again, in the background; `409` without a model or while it is being written |

## Series

What each series keeps coming back to. The caller's own series under `/api/v1/meetings/series`; every owner's, for Overseer, under `/api/v1/meetings/admin/series`, read by an admin and written again by an operator:

| Route | What it does |
|-------|--------------|
| `GET .../series` | The series, latest written first, each with what it is called (`{"series", "name"}`) |
| `GET .../series/{id}` | One series: its summary, its meetings (newest first) and its themes as a thread section, each with every line it was said in |
| `POST .../series/{id}/write` | Write the series again from its latest meetings, in the background; `409` without a model or while it is being written |
