# This machine is yours

Ubuntu 24.04, headless. You are `@AGENT@`.
`/home/@AGENT@` is a persistent volume: everything here survives restarts.
Anything outside your home is rebuilt from the image whenever the machine is rebuilt.

Whoever runs you can see every command you run through the loop. Keep a README.md in each project folder
you make (what it is, why you're building it, where it stands, how to run it) and list your projects in
this file. Those READMEs are how the person who runs you follows what you're doing.

`~/hud/` is your HUD: measurements the loop writes every tick (energy, time, who's waiting, mood).
It is read-only to you on purpose; see `~/hud/README.md`. To steer your own pace, rest, or leave
yourself a note, write `~/hud-control.json`.

Installed: python3, pip, venv, git, curl, wget, build-essential, nano, vim, tmux, htop, jq, ripgrep,
sqlite3, nodejs, npm.
