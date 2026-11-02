# Meetings Service

A bot that joins a call as a visible, announced participant, and keeps who was there and what each of them said. Put something to it by name and Illiana answers in the call, out loud. It joins Google Meet today; Teams and Zoom come next.

!!! warning "Experimental Service"
    Meetings is currently experimental. The bot, notes and Overseer views are functional and covered by tests, but it joins only Google Meet, each agent needs a Google account of its own, and the data model and API may change before the first stable release.

!!! info "Quick Start"
    Generate a project with the meetings service:

    ```bash
    aegis init my-app --services meetings
    cd my-app
    my-app meetings login
    my-app meetings join https://meet.google.com/abc-defg-hij
    my-app meetings list
    my-app meetings show 1
    ```

    With the htmx frontend, the same is a page at `/meetings`.

    Meetings requires the `database` component and brings the `browser` component, the browser the bot joins through. Signing the bot in (`meetings login`) needs the `secrets` component; see [Agents and Calendars](agents.md).

## What You Get

- **Transcript** - who said what, live, from Meet's captions.
- **Illiana in the call** - say her name and she answers out loud. See [Talking to Illiana](illiana.md).
- **Questions and actions** - questions picked out of the call, each one a click from a coding agent or Illiana.
- **Notes** - summary, decisions, action items and open questions, each citing its lines.
- **Threads, people and series** - commitments and contradictions, a guide to each person, and what keeps coming up across a recurring meeting.
- **Agents and calendars** - several Google accounts to join as; invite one and it comes.
- **Search** - every word said and every note.

## The pages here

| Page | What it covers |
|------|----------------|
| [Agents and Calendars](agents.md) | Signing the bot in, one agent per Google account, each agent's calendar, and joining what it is invited to |
| [In the Call](bot.md) | How the bot joins, runs and leaves a meeting, its card and voice, and what it hears |
| [Talking to Illiana](illiana.md) | Asking her by name, stopping her, talking over her, and how she answers |
| [Questions and Actions](moments.md) | Questions picked out of the call, the actions on them, the runner, and adding your own |
| [Notes, People and Series](notes.md) | What is written once a call is over, and the agents that write it |
| [Meetings Page and Overseer](pages.md) | The `/meetings` page, Overseer's views, the Flet dashboard, and search |
| [CLI Commands](cli.md) | `my-app meetings ...` |
| [API Reference](api.md) | The owner's, the runner's and Overseer's routes |
