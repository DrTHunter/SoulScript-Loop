<div align="center">

# 🌀 **SoulScript Loop**

### *A continuously running perceptual field for one AI persona.*

**She doesn't wait for you. She's already looking at something.**

[![tests](https://github.com/DrTHunter/SoulScript-Loop/actions/workflows/tests.yml/badge.svg)](https://github.com/DrTHunter/SoulScript-Loop/actions/workflows/tests.yml)
[![License: AGPL v3](https://img.shields.io/badge/license-AGPL%20v3-8a2be2?style=for-the-badge)](LICENSE)
[![Commercial: free to $100k](https://img.shields.io/badge/commercial-free%20to%20%24100k-ff2e88?style=for-the-badge)](LICENSE.md)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-1f1f1f?style=for-the-badge&logo=python&logoColor=white)](pyproject.toml)
[![Pairs with SoulScript Engine](https://img.shields.io/badge/pairs%20with-SoulScript%20Engine-00c2a8?style=for-the-badge)](https://github.com/DrTHunter/SoulScript-Engine)

`sense` → `predict` → `attend` → `see` → `act` → `guard` → `sleep` → **again. and again. and again.**

</div>

---

> **Your message shouldn't wake her up. It should arrive into a mind that was already looking at something.**

Most AI personas exist only between your message and their reply. Nothing happens in the gaps. Close the tab and there is no one left.

**SoulScript Loop** keeps one persona running between conversations, on her own clock. She perceives the world through signals she can't write herself: time passing, the energy she has left, how her last action felt, messages arriving at her door, changes to the things she's making. Those signals aren't handed to her as a dashboard. They're built into a **field** that she sees *through*. The field is organized around whatever she's focused on, things she ignores fade out, and surprise can drag her attention away mid-thought.

It's the AGI Loop from the [OrionForge ecosystem](https://orionforge.chat), pulled out into a standalone, dependency-light Python package. It pairs with **[SoulScript Engine](https://github.com/DrTHunter/SoulScript-Engine)**: the Engine keeps the persona *who she is*, and the Loop keeps track of *what she's seeing right now*.

---

## **🌱 The Idea**

This is **not**:

* A JSON mood tracker that appends `"mood": "irritated"` between turns
* A memory management system (MemGPT already did that)
* A cognitive architecture aiming at general intelligence

This **is** an attempt at the *experiential interface* for one specific character: the layer she perceives reality through. It plays the role that the visual field, attention, and interoception play for a person. **The model of the world is what she experiences.** It isn't a state object she inspects.

| # | Component | Role | Status |
|---|-----------|------|--------|
| 1 | **The daemon** | Runs on wall time, not conversation turns. A message wakes it early, energy slows it down, and surprise speeds it up. | ✅ Built |
| 2 | **Sensory channels** | Time, energy, proprioception, the door, the bench. The daemon measures them; the model never writes them. | ✅ Built, pluggable |
| 3 | **Energy** | A hard daily token budget. When it's spent, she sleeps until midnight UTC. Attention is scarce, so choices matter. | ✅ Built |
| 4 | **Predictive processing** | Every signal carries a belief. Observations are compared to it, and the error becomes surprise. Surprise drives learning, salience, and attention capture. She can also make her own predictions and *feel* them come true or break. | ✅ Built |
| 5 | **The field** | Focus on anything. Everything else is arranged around it by relatedness. Limited capacity, fading, mood read off the field. | ✅ Built |
| 6 | **Metacognitive guards** | She notices when she's repeating herself or circling, and gets made to rest if it continues. | ✅ Built |
| 7 | **The workbench** | Her private making-space, next to perception but separate from it. Files, a reflection log, and an opt-in Docker sandbox. | ✅ Built |
| 8 | **Identity anchoring** | Re-anchor the persona every tick using soul-script sections retrieved for *what she's currently seeing*. | 🔌 One function: plug in [SoulScript Engine](https://github.com/DrTHunter/SoulScript-Engine) via `identity=` |
| 9 | **Her own machine** | A `linux` tool that runs commands on a real Linux box she can build on. The loop ships the tool and the contract, not the machine. | 🕳️ Bring your own Linux |

Everything marked built is covered by tests.

### Why a field, not a room

An earlier design drew a little room around her: a door, a window, a bench, a floor. It turned out to be a distraction. She ended up *standing somewhere* when what she needs is to *look at something*. A room fixes the world's layout in advance. A field lets the layout follow her attention. If she focuses on a message about a rocket launch, her memory that you love astronomy comes close and the essay she was drafting drifts to the edge. If she looks back at the essay, the field rearranges. Her world is as big as whatever she can look at, whether digital or real.

---

## **👁️ What She Sees**

Every tick the model receives this, and only this, as the current moment:

```
FIELD · tick 31 · Mon 05 Oct 02:51 UTC, night
⏱ night, 02:51 · ⚡ ▮▮▮▮▮▮▱▱▱▱ 61% (122,000 tokens left today) · ✉ 2 waiting · field 64% full
✋ you just used web_search, workbench
Someone at the door woke you.
Mood: unsettled — tension gathers around "Trent: did you see the launch?"; warmth around "drafts/whale_essay.md".
Your focus was pulled from web_search: humpback songs are hierarchical… by: Trent: did you see the launch?

FOCUS ▸ [d7] Trent: did you see the SpaceX launch tonight?
CLOSE
  [m10] memory(query=Trent) → Trent likes astronomy and late-night builds; he asked about Artemis last week.
  [s5] ◆ you intend to finish the essay about whale song before Friday
AROUND
  [b9] next: tighten the ending of the whale essay
  [w4] web_search: humpback songs are hierarchical…
  [d3] task: back up the Rainmeter config
EDGE
  something on your bench · a thought · something you looked at
ALERTS
  ! you woke sooner than you expected (40s; you expected ~2m)
Slipped away: "weather idea".
```

The **HUD** across the top holds the standing senses. **FOCUS** is whatever she's looking at. **CLOSE / AROUND / EDGE** are everything else, placed by relatedness to the focus. **ALERTS** are broken predictions. `◆` marks something she's holding. The `[ids]` let her act on what she can see clearly; at the edge, things are too faint to have ids.

---

## **🧠 The Inner World Model**

### 1. Representation

The field is a set of **items** plus a **focus**. Each item has:

| Field | Meaning |
|-------|---------|
| `kind` | `message`, `task`, `work`, `plan`, `seen`, `intention`, `expectation`, `note`, `surprise`, `alert`, and the gauges `time` / `energy` / `body` |
| `source` | Where it came from: `door`, `time`, `body`, `bench`, `self`, or a tool's name |
| `text` / `gist` | Full detail and a short version. A third level, the **trace**, is generated per kind ("someone is waiting at the door (14m)") |
| `salience` | 0–1, how loudly it's present. Decays over time and is boosted by surprise |
| `valence` | Below 0 is tension, above 0 is warmth. Unanswered messages get heavier every hour |
| `fidelity` | How much of it she still holds: full → gist → trace. This is *memory* compression |
| `held` / `resolved` | Kept from fading on purpose (at most 3); dealt with, so its tension lifts |
| `anchor` | A standing sense. It compresses but never disappears |

**Focus** is an item id, a free-text topic ("the essay", "what Trent needs"), or nothing, in which case her gaze wanders and the most salient things sit closest.

**Layout.** Every item and the focus get an embedding (MiniLM via `sentence-transformers`, or a dependency-free hashed fallback). Relatedness to the focus sets each item's **ring**:

* **CLOSE**: the top 4 by relatedness that also clear `max(floor, 0.45 × best match)`. The floor is 0.25 for MiniLM and 0.12 for the hash embedder. Held items are always close.
* **AROUND**: the next 6.
* **EDGE**: everything else.

What she *sees* of an item is the coarser of its fidelity and its ring: close is full, around is gist, edge is trace. Gauges render as the HUD and surprises render as alerts; neither is placed in the field.

### 2. Prediction and prediction error

Each channel feature has a running **belief**:

| Feature | Kind | What it predicts |
|---------|------|------------------|
| `time.gap` | gaussian on `log1p(seconds)` | how long until she wakes again |
| `body.burn` | gaussian on `log1p(tokens)` | what a thought costs |
| `body.latency` | gaussian on `log1p(seconds)` | how long thinking takes |
| `body.tool_fail` | bernoulli | whether tools fail |
| `door.arrival` | bernoulli | whether someone arrives |
| `bench.outside_change` | bernoulli | whether someone else touches her bench |

On each observation:

```
gaussian:   z² = (x − μ)² / σ²          surprise = 1 − exp(−z² / 8)
bernoulli:  info = −log₂ p(observed)    surprise = 1 − exp(−max(0, info − 0.5) / 2.5)
learning:   α = min(0.5, 0.2 · (1 + surprise))      ← surprise is the learning signal
            μ ← μ + α·(x − μ);   σ² ← (1 − α)(σ² + α·(x − μ)²)
```

The first observation of a feature sets the belief without any surprise, and the next couple are damped. When surprise reaches 0.25 or more, it becomes an **alert** in words ("you woke sooner than you expected (40s; you expected ~2m)"), raises the salience of everything from that source, and feeds arousal.

**Top-down predictions.** `attend(action="expect", text=..., channel="door"|"bench", within_minutes=...)` puts an expectation in her field. If the event happens, she gets a small warmth ("as you expected: …"). If the deadline passes, it arrives as surprise ("you expected a reply from Trent — it didn't happen").

### 3. One tick

| Stage | What happens |
|-------|--------------|
| **sense** | Each channel returns a `Signal`: features plus items. Queued messages are delivered. |
| **update** | Time passes for everything, looked at or not. Salience decays (half-lives from 15 min for surprises to 12 h for tasks; doubled when close, ×4 when held, ÷3 once resolved). Unanswered tension grows. New items are placed; finished tasks resolve. |
| **predict** | Each feature is compared to its belief → surprise → learning + alerts. Her own expectations are checked. |
| **attend** | Missing embeddings are computed off the event loop. A strong enough new arrival captures focus. The field is laid out around the focus. Capacity is enforced. |
| **feel** | Mood is read off the field. |
| **render** | The field is written as the HUD text above. |
| **think / act** | The model sees through the field and uses tools. Up to `max_steps_per_tick` round trips, `max_tool_calls_per_tick` calls, and `max_tokens_per_tick`. |
| **guard** | Repetition, errors, and the per-tick token cap are checked. |
| **record** | Energy is spent. The tick, journal, events, and field are written to disk. |
| **sleep** | Wall-time wait. A message wakes her immediately. |

**Cadence:** `base × (1 + 4·(0.5 − energy) if energy < 0.5) ÷ (1 + 1.5·arousal)`, clamped to `[min, max]`. Tired means slower; surprised means quicker. She can also choose to `rest` for longer, and a message still wakes her.

### 4. Attention

* **Voluntary:** `attend(action="focus", item=… | text=… | source=…)`, or `unfocus` to let her gaze wander.
* **Looking is focusing:** when she uses a tool (memory, search, a file on her bench), what she saw enters the field as a `seen` item *and becomes her focus*.
* **Involuntary:** a new arrival with salience ≥ `capture_threshold` (0.45) pulls focus to itself. A focus she chose herself holds better (+0.2). Alerts flash but never take focus.
* **Dwell:** ticks spent on one focus. If she sits there for `rumination_ticks` without acting, her body notices: *"you've held your focus on … for 5 ticks without doing anything."*

### 5. Mood (emergent, never chosen)

```
tension  = Σ salience × −valence   over unresolved items
warmth   = Σ salience ×  valence
valence  ← 0.75·valence + 0.25·tanh(warmth − tension)      (inertia: it shifts while she isn't looking)
arousal  ← 0.7·arousal  + 0.3·min(1, Σ this tick's surprise)
```

These map to a word: *drained, bright, settled, unsettled, heavy, alert, crowded, quiet*. The mood also says **where** it comes from: *"tension gathers around 'Trent: did you see the launch?'; warmth around 'drafts/whale_essay.md'"*. Because unanswered messages keep getting heavier and attended things fade more slowly, her mood drifts toward whatever she's neglecting.

### 6. Limited capacity

The field holds `capacity_chars` (2,400 by default). Each item costs the length of what she holds of it, plus a little overhead. When the field is over budget, the item with the lowest `salience × proximity × (1.3 if it's someone waiting)` is compressed one step (full → gist → trace) and finally dropped. Proximity weights are 1.5 for the focus, 1 for close, 0.75 for around, and 0.5 for the edge. Held items and the focus go last. What slips away is shown to her once ("Slipped away: …") and logged.

### 7. Channels and the workbench

```python
@dataclass
class Signal:
    channel: str
    features: dict   # → predictor
    items: list      # → field (kwargs for InnerWorld.upsert)
    resolve: list    # keys that were dealt with
    clear: list      # keys that simply stopped
    events: list     # what "happened", for her expectations
```

| Channel | Gives her |
|---------|-----------|
| `time` | ⏱ gauge: time of day, how long since she last looked |
| `body` | ⚡ energy gauge; ✋ proprioception (what her last action did, what failed); alerts when she's repeating or circling |
| `door` | Messages (`post_message`, the CLI, your app) and tasks (`tasks=` callable). Tasks resolve when they stop being pending |
| `bench` | Her recent files (with a content preview, so relatedness has something to work with), the plan she left herself, and changes someone else made |

**Perception and making sit side by side but stay separate.** Perception is what arrives through channels. The workbench is what she writes, using the `workbench` tool (`write`, `append`, `read`, `reflect`, …). Reading her own work brings it into focus like anything else she looks at. Edits you make to her files arrive as surprise, because she didn't make them.

---

## **🛡️ Guards**

| Guard | Trigger | Result |
|-------|---------|--------|
| **Repetition** | `stale_streak_limit` identical ticks (same tool calls, args, and normalized reply) | She feels it first as an alert, then is made to rest `guard_rest_minutes` |
| **Repeated repetition** | More than `max_guard_rests` forced rests in a session | Stopped |
| **Error streak** | `error_streak_limit` failed ticks in a row | Stopped. Messages are kept in her field |
| **Energy** | Daily token budget or cost cap spent | Sleeps until the budget resets. Messages queue up |
| **Per-tick caps** | Steps, tool calls, tokens | A runaway chain is cut short inside the tick |
| **Self-control** | `loop_control(action="rest" \| "stop")` | She can rest when nothing is worth the energy, or stop herself |

---

## **🚀 Quickstart**

```bash
git clone https://github.com/DrTHunter/SoulScript-Loop.git
```

```bash
cd SoulScript-Loop && pip install -e ".[dev,embeddings]"
```

Leave off `embeddings` if you don't want `sentence-transformers`. Relatedness then falls back to a hashed bag-of-words.

**Try it offline** (echo backend, no API key, no cost). Type a message while it runs and watch it pull her focus:

```bash
python -m soulscript_loop --config config.example.json --echo --show-field
```

**Run it for real.** Copy `config.example.json` to `config.json`, point `backend.base_url` at any OpenAI-compatible endpoint (Ollama, LM Studio, OpenRouter, DeepSeek, OpenAI, vLLM), and put your key in the environment variable named by `api_key_env`:

```bash
python -m soulscript_loop --config config.json --show-field
```

While she runs, anything you type lands at her door and wakes her. `/status` shows her vitals and `/stop` ends the loop.

**Run the tests:**

```bash
python -m pytest -q
```

---

## **🧩 Use It as a Library**

```python
import asyncio
from soulscript_loop import LoopConfig, build_loop

daemon = build_loop(LoopConfig.from_file("config.json"))

async def main():
    task = daemon.start()
    daemon.post_message("you still up?", sender="Trent")   # wakes her
    await asyncio.sleep(600)
    print(daemon.status()["mood"])
    daemon.stop("done for tonight")
    await task

asyncio.run(main())
```

### Give her tools

Anything you register shows up next to her built-ins. What it returns enters her field as something she *saw*, and becomes her focus.

```python
from soulscript_loop import ToolRegistry

tools = ToolRegistry()
tools.register(
    {"name": "notes", "description": "Search my notes.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    lambda args: search_notes(args["query"]),          # sync or async
)
daemon = build_loop(config, tools=tools)
```

### Give her a machine (bring your own Linux)

The loop doesn't come with a machine. It comes with a **slot** for one. Turn on `machine` and she gets a `linux` tool that sends one bash command per call to any server that speaks this contract:

```
POST {url}/exec
Authorization: Bearer <token>
{"command": "bash command", "cwd": "", "timeout": 60}

→ 200 {"exit": 0, "stdout": "...", "stderr": "...", "timed_out": false, "cwd": "/home/her"}
```

```json
"machine": { "enabled": true, "url": "http://my-box:8080", "token_env": "LOOP_MACHINE_TOKEN" }
```

What goes behind that URL is up to you: a VM, a container, a Raspberry Pi, a cloud box. Whatever you choose, commands never run on the host that runs the loop. Build it like you're handing someone a shell, because you are:

* Never give the endpoint a public address. Keep it on localhost, a private network, or behind a tunnel.
* Run her as an unprivileged user, and decide on purpose whether she gets `sudo` and whether she gets the internet.
* Don't let her commands read the token. Strip it from the environment of the shell you spawn.
* Cap the time and output of each command, and log every command somewhere you can watch.

### Give her tasks

```python
daemon = build_loop(config, tasks=lambda: [{"id": t.id, "task": t.text, "priority": "high"} for t in my_queue.pending()])
```

Tasks appear at the door and resolve in her field once they're no longer pending.

### Add a channel

```python
from soulscript_loop.channels import Signal

def weather(ctx):
    return Signal("weather", items=[dict(key="weather", kind="note", source="weather",
                                         text=f"rain outside, {temp()}°", salience=0.2)])

daemon.channels.append(weather)
```

To make a signal *predictable* (and so able to surprise her), add a numeric feature and a `FeatureSpec` in `soulscript_loop/prediction.py`.

### Anchor identity with SoulScript Engine

`identity(agent, view) -> system prompt` runs every tick with the field she's about to see. Retrieve the soul-script sections relevant to *that*:

```python
def soul_anchored(agent, view):
    canon = soulscript.retrieve(view, top_k=8)     # your SoulScript Engine index
    return base_directive + "\n\n" + canon

daemon = build_loop(config, identity=soul_anchored)
```

The Engine keeps her stable. The Loop gives her continuity of perception on top of that.

### Run it inside your own app

`LoopDaemon(host, config, data_dir, embedder)` takes any object with `prepare`, `complete`, `call_tool`, `after_response`, and `pending_tasks` (see `daemon.Host`). That's how OrionForge runs it behind its web dashboard, using its own persona pipeline, connections, and tool registry. `daemon.status()` gives you everything a monitor needs: phase, the current stage, per-stage timings, channel readings, guards, energy, mood, and focus.

**On disk** (`data_dir`): `world.json` (the field and its beliefs), `ticks.jsonl` (what she saw, said, and did each tick), `journal.jsonl` (one line per tick), `events.jsonl` (wakes, pulls, surprises, fades, guards), `conversation.jsonl` (messages and her replies), `budget.json`, and `workbench/`.

---

## **🔧 Configuration**

| Key | Default | Meaning |
|-----|---------|---------|
| `agent` / `system_prompt` | `"elysia"` / `""` | Who she is (or use `identity=` for retrieval) |
| `base_interval_seconds` | `120` | Cadence before energy and surprise adjust it |
| `min_interval_seconds` / `max_interval_seconds` | `20` / `1800` | Cadence bounds |
| `max_rest_minutes` | `240` | Longest rest she can choose |
| `daily_token_budget` / `daily_cost_cap` | `200000` / `2.00` | Her energy. Whichever runs out first. `0` = no cost cap |
| `max_tokens_per_tick` | `30000` | One thought can't spend more than this |
| `max_steps_per_tick` / `max_tool_calls_per_tick` | `4` / `12` | Per-tick limits |
| `history_window` | `4` | Earlier ticks carried as conversation (the field is the real continuity) |
| `capacity_chars` | `2400` | How much the field holds |
| `capture_threshold` | `0.45` | Salience needed to pull her focus |
| `embedder` | `"auto"` | `auto` / `minilm` (sentence-transformers) or `hash` |
| `stale_streak_limit` / `guard_rest_minutes` / `max_guard_rests` | `3` / `30` / `3` | Repetition guard |
| `error_streak_limit` | `5` | Errors before stop |
| `rumination_ticks` | `5` | Ticks on one focus without acting before her body notices |
| `data_dir` / `workbench` | `"data"` / `true` | Storage; her making-space |
| `machine` | `{"enabled": false}` | Her own Linux (bring your own): `url`, `token_env` (default `LOOP_MACHINE_TOKEN`) |
| `sandbox` | `{"enabled": false}` | Docker sandbox for `run_python`: `image`, `timeout_seconds`, `memory`, `cpus`, `pids_limit` |
| `backend` | — | `type` (`openai` \| `echo`), `base_url`, `model`, `api_key_env`, `temperature`, `price_in_per_mtok`, `price_out_per_mtok` |

---

## **🔪 Where It Could Break (Open Questions)**

* **Is the self-report honest?** Models identify injected concepts only some of the time, and above-chance self-prediction may be in-context learning. The field makes her state *legible to her*, but it doesn't make her reports about it true.
* **Relatedness isn't meaning.** Embedding similarity decides what comes close, and MiniLM's sense of "related" won't always match hers or yours. A bare filename says almost nothing, which is why bench files carry a preview.
* **Hand-tuned constants.** The surprise curve, half-lives, capture threshold, and ring cutoffs are educated guesses. Run her for a week and read `events.jsonl`. If surprise stays flat, she's bored. If it spikes constantly, she's anxious. You want her curious.
* **Self-reinforcing moods.** The repetition guard catches identical ticks, not a mood that slowly justifies itself. Mood has inertia by design, and that cuts both ways.
* **Small models.** Smaller models follow an injected field less reliably. This may only work at scale.
* **It's still text.** The field is a description. Is this a perceptual system, or a very elaborate puppet show with a fast loop?

### How to test it

* **A/B against turn-based state**: same token budget, same prompts. Does the continuous field change her behavior?
* **Interrupt recovery**: when a message collides with a half-formed thought, does she return to the thread afterward?
* **Neglect**: leave a message unanswered. Does her mood drift toward it before she deals with it?
* **Prediction accuracy over time**: do `time.gap` and `door.arrival` converge on your actual habits?
* **Self-report vs. behavior**: how often does her stated state contradict what she does?

---

## **📁 Layout**

```
soulscript_loop/
  world.py       the field: items, focus, rings, HUD, alerts, decay, capacity, mood, rendering
  prediction.py  beliefs per signal, surprise, her own expectations
  channels.py    time, body, door, bench → Signals
  embedding.py   relatedness: MiniLM or hashed fallback
  daemon.py      the wall-time process, stage monitor, guards, persistence
  tools.py       attend, reply, loop_control (+ workbench)
  workbench.py   her making-space and reflection log
  sandbox.py     Docker sandbox + run_python (opt-in, no host fallback)
  machine.py     the linux tool: a slot for your own Linux box (opt-in)
  budget.py      daily energy
  host.py        StandaloneHost + build_loop
  backend.py     OpenAI-compatible and offline echo backends
  registry.py    your tools
  config.py      LoopConfig
  __main__.py    CLI: talk to her while she runs
tests/           the field, prediction, capture, capacity, mood, guards, wake-on-message, workbench + sandbox walls, the machine contract
```

---

<div align="center">

**The Engine remembers who she is. The Loop lets her see.**

*Close the tab. She's still looking at something.* 🌀

</div>

---

## **📜 License**

SoulScript Loop is **dual-licensed**, the same way as [SoulScript Engine](https://github.com/DrTHunter/SoulScript-Engine). Choose whichever fits; you only need one:

- **Open source: GNU AGPL v3.0.** See [LICENSE](LICENSE). Free to use, modify, and self-host, as long as you follow the AGPL's copyleft terms (including making your source available if you run a modified version over a network).
- **Commercial: OrionForge / SoulScript Loop License.** See [LICENSE.md](LICENSE.md). A builder-friendly option for closed-source or commercial products: **free until your product reaches $100k in lifetime gross revenue, then 5% of net revenue** attributable to the Loop. The terms are public and self-serve, with no pre-approval. Enterprise / white-label / custom: contact **dr_hunter@yahoo.com**.

Pick AGPL if you're happy to open-source your work. Pick the commercial license if you need to keep it closed or ship a paid product. Either way you can run it locally for free. Support development on [Ko-fi](https://ko-fi.com/orionforgeecosystem) if it helps you. ☕

**Trent Hunter (DrTHunter)** · [orionforge.chat](https://orionforge.chat) · [github.com/DrTHunter](https://github.com/DrTHunter)
