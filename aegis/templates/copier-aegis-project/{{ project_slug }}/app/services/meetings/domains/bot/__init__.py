"""The meeting bot.

- ``run`` - the bot's run: join, stay, leave, and write each step on the row
- ``meet`` - Google Meet's page: when Meet changes its UI, the fix
- ``audio`` - the call's audio, each second to whoever was talking
- ``login`` - the bot's Google sign-in, kept as a secret
- ``dispatch`` - where a run goes: the worker's meetings queue, or this process
"""
