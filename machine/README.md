# 🖥️ A machine for her

A small, hardened Linux box you can hand to a persona. She runs bash commands on it through the loop's `linux` tool; you watch every one of them.

It's the machine one of OrionForge's minds lives on, cut down to what's worth giving to any mind and made safer to publish. Nothing about any particular persona is in here.

```bash
export MACHINE_TOKEN=$(openssl rand -hex 32)     # any long random string
docker compose up -d --build
```

Point the loop at it (same token, in the loop's environment):

```json
"machine": { "enabled": true, "url": "http://localhost:8080", "hud_url": "http://localhost:8080", "token_env": "MACHINE_TOKEN" }
```

## What she gets

* **Ubuntu 24.04**, headless, with python3 / pip / venv, git, curl, wget, build-essential, node / npm, tmux, jq, ripgrep, sqlite3, vim, nano, htop.
* **A home on a persistent volume** (`/home/agent`). Everything there survives restarts; anything outside it is rebuilt from the image.
* **The internet, outbound only.** Nothing can reach her.
* **A seeded `~/README.md`** that tells her the machine is hers, and asks her to keep a README in each project so you can follow what she's building.
* **A HUD she can read and can't forge** (`~/hud/`), and a control file she can write (`~/hud-control.json`). See below.

By default she has **no `sudo`**. She can build in her home, use `pip install --user`, venvs and local `npm`. If you want her to `apt install` and change the system, that's a decision: build with `AGENT_SUDO: "1"` (and drop `no-new-privileges` from the compose file, or `sudo` can't work). She'll then be root *inside the container*, which is as far as the fence reaches.

## You can watch her

| | |
|---|---|
| `GET /log?lines=300` | tail of the command log: every command, its output and exit code, with timestamps |
| `GET /tree` | the files under her home |
| `GET /file?path=notes/plan.md` | one text file under her home |
| `GET /stats` | disk, memory, load, uptime |
| `GET /health` | `{"ok": true}`, no token needed |

All of these (but `/health`) need `Authorization: Bearer $MACHINE_TOKEN`. For a live shell as her, `docker compose exec -u agent machine bash`.

The log lives at `/var/log/machine/shell.log`, **root-owned, outside her home**. She cannot edit her own record.

## The walls

The server is a short single file ([`server.py`](server.py)); read it. What it does so you don't have to trust a promise:

| Wall | How |
|------|-----|
| **Her commands can't read the token** | The server runs as root and spawns every command as the unprivileged `agent` user in a clean environment. The token lives in a root process; `/proc/<pid>/environ` of a root process is closed to her. (Dropping to a user *from inside* a same-user server would leave the token readable in `/proc`, which is why it's built this way.) |
| **She can't forge her measurements** | The HUD is written by the root server into `/var/hud`, which she can't write. `~/hud` is only a symlink to it; deleting the link changes nothing the loop writes. Her home is hers, so the root-owned folder deliberately lives *outside* it: a root process that wrote into a directory she owns could be pointed at any file on the box by swapping the directory for a symlink. |
| **The server can't be tricked into reading outside her home** | `/file` resolves symlinks and refuses anything that leaves the home. `/tree` doesn't follow symlinked directories. |
| **Runaway commands end** | Time-limited (default 60 s, max 300 s), killed as a whole process group, so a backgrounded child doesn't survive. For long-running things she's told to use tmux or nohup. |
| **Output can't eat the server** | Output goes to temp files, capped at ~4 MB per stream while running, and only the tail (16,000 characters) is returned. |
| **No second door** | There is no web terminal or SSH server. One authenticated HTTP endpoint, bound to `127.0.0.1` by the compose file. |
| **The container is fenced** | Memory, CPU and pid limits; all capabilities dropped except what the server needs to change user; `no-new-privileges`. |

What this does **not** do: it isn't a security boundary against a determined attacker with a kernel exploit, and it doesn't restrict her network. A mind with the internet and a shell can reach the internet. Run it on a machine you'd be comfortable having her use, put the endpoint on localhost or a private network only, and never publish port 8080 on a public address.

## The HUD

Every tick the loop pushes her HUD to `POST /hud` (when `hud_url` is set). The server writes:

* `~/hud/now.json`: this tick's measurements: tick, time (UTC and local), energy, what's left today, who's waiting, how full her field is, mood, focus, pace, what the tick cost.
* `~/hud/now.txt`: the HUD lines exactly as she saw them.
* `~/hud/log.jsonl`: one line per tick, trimmed to its newest half past ~2 MB.
* `~/hud/README.md`: tells her what these are.

Her scripts can trust these numbers because she can't write them. If the file and her memory disagree, she's told to trust the file.

**Steering her own state.** Measurements are the host's; *state* is hers. She writes `~/hud-control.json`:

```json
{ "seq": 1, "reason": "why", "pace_seconds": 300, "rest_minutes": 30, "note": "check the build before bed" }
```

At her next tick, when `seq` has gone up, the loop applies it once: sets her pace (`null` returns to adaptive), schedules a rest, sets the note into her field. What was applied, and what was refused and why, comes back in `now.json` under `"control"`.

## Making it yours

| | |
|---|---|
| Her name | `AGENT_USER` build arg (also the home directory). Change the compose volume path to match. |
| Sudo | `AGENT_SUDO` build arg. Default `0`. |
| Her tools | Edit the `apt-get install` line in the [`Dockerfile`](Dockerfile). |
| The port / token | `PORT` (default 8080) and `MACHINE_TOKEN` environment variables. |
| Another place to run it | It's a plain container: a Raspberry Pi, a VM, a cloud container service. Keep it on a private network. |

Don't want this box? The contract is five lines (see the main [README](../README.md#give-her-a-machine)); anything that speaks it works.
