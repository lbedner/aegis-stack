# Meetings Service

A bot that joins a call as a visible, announced participant, and keeps who was there and what each of them said. This release ships the records: the meetings the bot is asked to join, their participants and the transcript. Joining a call comes next.

!!! info "Quick Start"
    Generate a project with the meetings service:

    ```bash
    aegis init my-app --services meetings
    cd my-app
    my-app meetings add https://meet.google.com/abc-defg-hij
    my-app meetings list
    my-app meetings show 1
    ```

    Meetings requires the `database` component and brings the `browser` component, the browser the bot joins through.

## What You Get

- **Meetings** - one row per call the bot is asked to join: the link, its platform, the name the bot joins as, and its status (`requested`, `joining`, `waiting` to be admitted, `in_call`, `left`, or `failed` with a reason), with when it joined and left.
- **Platforms** - the platform comes from the link: Google Meet (`meet.google.com`), Microsoft Teams (`teams.microsoft.com`, `teams.live.com`) and Zoom's web links (`zoom.us/j/...`). Any other link is refused before anything is stored.
- **Participants** - whoever the call names, by display name and the platform's own id when it gives one. A participant can be linked to a user, to say "this speaker is me".
- **Transcript** - one line per thing a participant said, timed in seconds from when the bot joined.
- **Owners** - a meeting belongs to whoever asked for the bot. Without an owner (no auth, the CLI) every meeting is in reach.

## CLI

| Command | What it does |
|---------|--------------|
| `meetings add <link> [--bot-name NAME]` | Record a meeting for the bot to join |
| `meetings list [-n LIMIT]` | The meetings, newest first |
| `meetings show <id>` | One meeting: its status and its transcript |
