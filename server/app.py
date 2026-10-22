#!/usr/bin/env python3
"""За стеклом (UnderWatch) — a resident with a mind of their own in a drawn flat.

    python3 server/app.py                  the server (see README.md for the environment)
    python3 server/app.py passwd <login>   set a password from the machine itself

The code lives in server/underwatch/:
    config, storage, passwords, context, clock, settings, world, brain   — the ground floor
    life/ (state, emotions, needs, bonds, goals, gifts, drawings,
           prompts, memory, mind, guest, body/)                          — the resident's life
    residents, accounts, web                                             — people and the HTTP side
"""
import sys

from underwatch.accounts import passwd_cli
from underwatch.web import main

if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "passwd":
        sys.exit(passwd_cli(sys.argv[2]))
    main()
