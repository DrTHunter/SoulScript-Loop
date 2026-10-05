"""The field, prediction, channels, budget, and daemon — offline, with a scripted model."""

import asyncio
import json
import shutil
import tempfile
import time
from pathlib import Path

from soulscript_loop import Completion, LoopConfig, LoopDaemon
from soulscript_loop.budget import DailyBudget
from soulscript_loop.prediction import Feature, Predictor
from soulscript_loop.workbench import Workbench
from soulscript_loop.embedding import HashEmbedder, cosine
from soulscript_loop.world import AROUND, CLOSE, EDGE, FOCUS, FULL, InnerWorld


def check(label, condition, detail=""):
    assert condition, f"{label} {detail}"


def _call(name, args, cid="c1"):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


class ScriptedHost:
    """Plays back a list of assistant messages, one per completion call."""

    def __init__(self, script=None, tokens=500):
        self.script = list(script or [])
        self.tokens = tokens
        self.calls = []
        self.tool_calls = []
        self.tasks = []
        self.fail = False

    def prepare(self, agent, view):
        tools = [{"type": "function", "function": {"name": n, "description": "", "parameters": {}}}
                 for n in ("memory", "inbox", "attend")]
        return [{"role": "system", "content": f"You are {agent}."}], tools

    async def complete(self, config, messages, tools):
        if self.fail:
            raise RuntimeError("provider down")
        self.calls.append({"messages": list(messages), "tools": [t["function"]["name"] for t in tools]})
        msg = self.script.pop(0) if self.script else {"role": "assistant", "content": "I sit with it."}
        return Completion(message=msg, tokens=self.tokens, cost=0.001, model="scripted")

    def call_tool(self, agent, name, args):
        self.tool_calls.append((name, args))
        return "Error: boom" if name == "inbox" and args.get("fail") else f"{name} ok"

    def after_response(self, agent, text):
        return text

    def pending_tasks(self):
        return list(self.tasks)


def _daemon(tmp, host, **cfg):
    base = dict(agent="tester", base_interval_seconds=5, min_interval_seconds=5, max_interval_seconds=60)
    base.update(cfg)
    return LoopDaemon(host, LoopConfig.from_dict(base), Path(tmp))


# ─────────────────────────────────────────────
# 1. Prediction
# ─────────────────────────────────────────────
def test_prediction():
    f = Feature("time.gap", "gauss")
    first = f.observe(120)
    check("first observation carries no surprise", first.surprise == 0.0)
    for _ in range(10):
        steady = f.observe(120)
    check("steady signal → low surprise", steady.surprise < 0.05, steady.surprise)
    jolt = f.observe(5)
    check("outlier → high surprise", jolt.surprise > 0.6, jolt.surprise)
    check("outlier direction is 'less'", jolt.direction == -1)
    check("surprise describes itself", "sooner than you expected" in jolt.describe(), jolt.describe())
    check("belief moved toward the outlier", f.expected_raw() < 120)

    b = Feature("door.arrival", "bern")
    for _ in range(12):
        b.observe(0)
    knock = b.observe(1)
    check("rare event → surprise", knock.surprise > 0.4, knock.surprise)
    quiet = b.observe(0)
    check("expected non-event → no surprise", quiet.surprise < 0.1, quiet.surprise)

    p = Predictor()
    p.observe("body.burn", 1000)
    restored = Predictor.from_dict(json.loads(json.dumps(p.to_dict())))
    check("predictor round-trips", restored.features["body.burn"].n == 1)


# ─────────────────────────────────────────────
# 2. The field
# ─────────────────────────────────────────────
def _field(capacity=20000):
    return InnerWorld(capacity_chars=capacity, embedder=HashEmbedder())


def _settle(w):
    w.ensure_vectors()
    w.layout()


def test_embedder():
    e = HashEmbedder()
    a, b, c = e(["the whale essay draft", "notes on whale migration for the essay", "pizza order receipt"])
    check("related texts are closer", cosine(a, b) > cosine(a, c) + 0.1, (cosine(a, b), cosine(a, c)))
    check("vectors are unit length", abs(cosine(a, a) - 1.0) < 1e-6)
    check("mismatched vectors are unrelated", cosine([1.0], [1.0, 0.0]) == 0.0)


def test_field_layout():
    now = time.time()
    w = _field()
    w.begin(1)
    whale, _ = w.upsert("file:whale", "work", "bench", "drafts/whale_essay.md — the whale essay draft",
                        gist="whale essay draft", salience=0.3, now=now)
    notes, _ = w.upsert("seen:whale", "seen", "memory", "memory: notes on whale migration for the essay",
                        gist="whale migration notes", salience=0.3, now=now)
    pizza, _ = w.upsert("note:pizza", "note", "self", "pizza order receipt, pepperoni", gist="pizza receipt",
                        salience=0.9, now=now)
    for i in range(12):
        w.upsert(f"note:filler{i}", "note", "self", f"unrelated filler thought number {i} about gardening tools",
                 gist=f"filler {i}", salience=0.2, now=now)
    w.upsert("time", "time", "time", "evening light · 19:05 UTC", gist="evening, 19:05", salience=0.2,
             mode="level", anchor=True, now=now)

    _settle(w)
    check("unfocused: the most salient sits closest", w.ring(pizza) == CLOSE)

    w.move(text="writing the whale essay")
    _settle(w)
    check("focus on a topic pulls related things close", w.ring(whale) == CLOSE and w.ring(notes) == CLOSE,
          (w.rings.get(whale.id), w.rings.get(notes.id)))
    check("unrelated things fall back", w.ring(pizza) != CLOSE, w.rings.get(pizza.id))
    check("crowded field pushes some to the edge", any(w.ring(i) == EDGE for i in w.in_field()))
    check("gauges are not in the field", all(i.kind != "time" for i in w.in_field()))

    view = w.render(now, {"energy": 0.6, "tokens_left": "120,000", "part_of_day": "evening"})
    check("HUD carries the gauges", "⏱ evening, 19:05" in view and "⚡" in view and "60%" in view, view[:300])
    check("topic focus is shown", 'FOCUS ▸ "writing the whale essay"' in view)
    check("close things in full", "drafts/whale_essay.md — the whale essay draft" in view)
    check("edge things only as traces", "EDGE" in view and "unrelated filler thought number" not in view.split("EDGE")[1])

    w.move(item_id=pizza.id)
    _settle(w)
    check("focus on an item: it is the center", w.ring(pizza) == FOCUS)
    check("whale things drift off when you look away", w.ring(whale) != CLOSE or w.ring(notes) != CLOSE)
    view = w.render(now, {"energy": 0.6})
    check("item focus is shown with its id", f"FOCUS ▸ [{pizza.id}] pizza order receipt" in view)

    w.drop(pizza)
    check("losing the focus leaves its memory as the topic", w.focus_item is None and w.focus_text == "pizza receipt")
    w.move()
    check("unfocus lets the gaze wander", w.focus_label() == "nothing in particular")


def test_capture_and_seeing():
    now = time.time()
    w = _field()
    w.begin(1)
    w.move(text="the essay", deliberate=False)
    m, _ = w.upsert("msg:x", "message", "door", "Trent: urgent — are you there?", salience=0.9, now=now)
    w.capture()
    check("a strong arrival pulls focus to itself", w.focus_item == m.id and w.pulled and w.pulled["to"] == m.id)

    w2 = _field()
    w2.begin(1)
    w2.move(text="the essay", deliberate=True)
    w2.upsert("msg:y", "message", "door", "soft knock", salience=0.55, now=now)
    w2.capture()
    check("chosen focus resists a weaker pull", w2.focus_text == "the essay" and w2.dwell == 1)

    seen = w2.see("memory", {"action": "search", "query": "whales"}, "3 memories about whale songs")
    check("looking brings it into the field", seen.kind == "seen" and seen.source == "memory")
    check("what you look at becomes your focus", w2.focus_item == seen.id)

    w2.upsert("surprise:time.gap", "surprise", "time", "you woke sooner than you expected", salience=0.8, now=now)
    _settle(w2)
    view = w2.render(now, {"energy": 0.9})
    check("surprise flashes as an alert", "ALERTS" in view and "! you woke sooner" in view)
    check("alerts never pull focus", w2.focus_item == seen.id)


def test_capacity_and_decay():
    w = _field(capacity=600)
    now = time.time()
    w.begin(1)
    keep, _ = w.upsert("note:keep", "note", "self", "x" * 150, gist="the held thought", salience=0.1, now=now)
    w.hold(keep)
    for i in range(8):
        w.upsert(f"note:{i}", "note", "self", f"thought {i} " + "y" * 120, gist=f"thought {i}", salience=0.2 + i * 0.05, now=now)
    _settle(w)
    w.fit(now)
    check("field stays within capacity", w.used(now) <= w.capacity, w.used(now))
    check("something compressed or faded", w.faded or any(i.fidelity > FULL for i in w.items.values()))
    check("held item survives at full detail", keep.id in w.items and keep.fidelity == FULL)
    check("faded things are logged", len(w.fade_log) == len(w.faded))

    w = _field()
    w.begin(1)
    w.decay(now)
    n, _ = w.upsert("note:n", "note", "self", "a passing thought", salience=0.6, now=now)
    m, _ = w.upsert("msg:m", "message", "door", "unanswered", salience=0.5, valence=-0.3, grows=0.25, now=now)
    for i in range(12):
        w.upsert(f"note:f{i}", "note", "self", f"filler {i}", salience=0.9, now=now)
    _settle(w)
    w.decay(now + 7200)
    check("an unattended thought decays", n.salience <= 0.31, n.salience)
    check("an unanswered message grows heavier", m.valence < -0.6 and m.salience > 0.5, (m.valence, m.salience))
    w.decay(now + 7200 * 8)
    check("a thought left alone eventually fades out", "note:n" not in w.keys)


def test_mood_and_expectations():
    now = time.time()
    w = _field()
    w.begin(1)
    w.upsert("msg:1", "message", "door", "angry message", gist="angry message", salience=0.9, valence=-0.8, now=now)
    for _ in range(6):
        w.compute_mood(0.9, now)
    check("tension makes a heavy mood", w.mood["word"] in ("heavy", "unsettled"), w.mood)
    check("mood locates the tension", "angry message" in w.mood["phrase"], w.mood["phrase"])
    check("tension attributed to its source", w.mood["by_source"]["door"]["tension"] > 0)
    w.resolve(w.get("msg:1"))
    for _ in range(8):
        w.compute_mood(0.9, now)
    check("resolving lifts the mood", w.mood["valence"] > 0, w.mood)
    check("low energy reads as drained", w.compute_mood(0.05, now)["word"] == "drained")

    w = _field()
    w.begin(1)
    ex = w.expect("a reply from Trent", "door", 10, now=now)
    check("an expectation is something you hold in mind", w.get(f"expect:{ex.id}").source == "self")
    w.check_expectations(["door"], now + 60)
    check("expectation met", ex.status == "met" and w.get(f"met:{ex.id}") is not None)
    ex2 = w.expect("the draft to change", "bench", 1, now=now)
    w.begin(2)
    w.check_expectations([], now + 120)
    check("expectation broken → surprise", ex2.status == "violated" and w.surprises)

    w.move(text="the draft")
    data = json.loads(json.dumps(w.to_dict()))
    w2 = InnerWorld.from_dict(data, embedder=HashEmbedder())
    check("field round-trips", len(w2.items) == len(w.items) and w2.tick == w.tick and w2.focus_text == "the draft")
    old = {"items": [{"id": "d1", "key": "msg:1", "kind": "message", "region": "door", "text": "x", "gist": "x"}],
           "focus": "door", "predictor": {"window.gap": {"key": "window.gap", "kind": "gauss"}}}
    w3 = InnerWorld.from_dict(old)
    check("old room state is ignored, not crashed on", not w3.items and not w3.predictor.features)


# ─────────────────────────────────────────────
# 3. Workbench & budget
# ─────────────────────────────────────────────
def test_workbench_and_budget():
    tmp = tempfile.mkdtemp()
    try:
        wb = Workbench(Path(tmp) / "bench")
        check("confined to the bench", '"ok": false' in wb.execute({"action": "write", "path": "../x", "content": "a"}))
        wb.execute({"action": "write", "path": "a.md", "content": "hello"})
        check("own writes aren't outside changes", wb.outside_changes() == [])
        (Path(tmp) / "bench" / "b.md").write_text("from the operator")
        check("someone else's write is noticed", wb.outside_changes() == ["b.md"])
        wb.execute({"action": "reflect", "built": "a", "next": "polish"})
        check("reflections recorded", wb.reflections(1)[0]["next"] == "polish")

        b = DailyBudget(Path(tmp) / "budget.json", 1000)
        b.spend(400, 0.0)
        check("energy reflects spend", abs(b.energy - 0.6) < 1e-9)
        check("budget persists", DailyBudget(Path(tmp) / "budget.json", 1000).tokens == 400)
        b.spend(700, 0.0)
        check("over budget → exhausted", b.exhausted and b.tokens_left == 0)
        c = DailyBudget(Path(tmp) / "b2.json", 10_000, cost_per_day=1.0)
        c.spend(10, 0.75)
        check("cost cap can be the tighter limit", abs(c.energy - 0.25) < 1e-9)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_config():
    c = LoopConfig.from_dict({"daily_token_budget": "5000", "workbench": "false", "capture_threshold": "0.3",
                              "min_interval_seconds": 1, "ticks_per_loop": 15, "sandbox": "yes",
                              "backend": {"type": "echo"}, "embedder": None})
    check("strings coerced", c.daily_token_budget == 5000 and c.workbench is False and c.capture_threshold == 0.3)
    check("floors enforced", c.min_interval_seconds == 5.0)
    check("v0.1 keys ignored", not hasattr(c, "ticks_per_loop"))
    check("objects stay objects", c.backend == {"type": "echo"} and c.sandbox == {"enabled": False})
    check("missing values keep defaults", c.embedder == "auto")


# ─────────────────────────────────────────────
# 4. Daemon
# ─────────────────────────────────────────────
def test_daemon_tick():
    tmp = tempfile.mkdtemp()
    try:
        host = ScriptedHost([
            {"role": "assistant", "content": "", "tool_calls": [_call("attend", {"action": "focus", "source": "door"}, "a"),
                                                              _call("memory", {"action": "search"}, "b")]},
            {"role": "assistant", "content": "", "tool_calls": [_call("reply", {"text": "Here. Working on it."}, "c")]},
            {"role": "assistant", "content": "Answered Trent; back to the bench next."},
        ])
        d = _daemon(tmp, host)
        d.post_message("are you there?", sender="Trent")
        asyncio.run(d.tick())

        first = host.calls[0]
        check("host tools offered, loop tools not duplicated", "memory" in first["tools"] and first["tools"].count("attend") == 1, first["tools"])
        check("loop tools offered", {"attend", "reply", "loop_control", "workbench"} <= set(first["tools"]))
        check("persona prompt carries the loop preamble", "FIELD" in first["messages"][0]["content"])
        view = first["messages"][-1]["content"]
        check("the model sees through the field", view.startswith("FIELD"), view[:80])
        check("the message is in view", "Trent: are you there?" in view)
        check("the message pulled focus", "FOCUS ▸ [" in view and "Trent" in view.split("FOCUS ▸")[1].splitlines()[0])
        check("registry tool ran through the host", host.tool_calls == [("memory", {"action": "search"})])
        convo = d.conversation.tail(5)
        check("reply recorded in the conversation", convo[-1]["role"] == "agent" and convo[-1]["in_reply_to"])
        msg_item = d.world.get(f"msg:{convo[0]['id']}")
        check("message resolved by the reply", msg_item and msg_item.resolved)
        seen = d.world.get('seen:memory:action=search')
        check("what it looked at entered the field", seen is not None and seen.kind == "seen")
        check("budget spent", d.budget.tokens == 1500)
        t = d.ticks.tail(1)[0]
        check("tick recorded with view + tools", t["view"].startswith("FIELD") and len(t["tool_calls"]) == 3)
        check("journal narrated", "Answered Trent" in d.journal.tail(1)[0]["narrative"])
        procs = {p["stage"]: p for p in d.status()["processes"]}
        check("every stage ran", all(procs[s]["runs"] >= 1 for s in ("sense", "update", "predict", "attend",
                                                                      "feel", "render", "think", "act", "guard", "record")))
        check("channels reported", {"time", "body", "door", "bench"} <= set(d.channel_status))

        d2 = _daemon(tmp, ScriptedHost())
        check("field survives a restart", d2.world.tick == 1 and d2.world.focus_item == d.world.focus_item)
        check("history carried into the next tick", d2.history and "Answered Trent" in d2.history[-1]["response"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_daemon_tasks_and_limits():
    tmp = tempfile.mkdtemp()
    try:
        host = ScriptedHost([{"role": "assistant", "content": "",
                              "tool_calls": [_call("inbox", {"fail": True}, f"x{i}") for i in range(4)]}])
        host.tasks = [{"id": "t1", "type": "task", "status": "pending", "task": "summarise the logs", "priority": "high"}]
        d = _daemon(tmp, host, max_tool_calls_per_tick=2)
        asyncio.run(d.tick())
        check("inbox task appears at the door", d.world.get("task:t1") is not None)
        tools = d.ticks.tail(1)[0]["tool_calls"]
        check("every tool call answered", len(tools) == 4)
        check("calls beyond the limit skipped", [t["ok"] for t in tools][2:] == [False, False]
              and tools[3]["result"].startswith("Skipped"))
        check("failed tool calls felt next tick", d.last_result["tools"][0]["ok"] is False)

        host.tasks = []
        asyncio.run(d.tick())
        check("task done in the inbox → resolved in the room", d.world.get("task:t1").resolved)
        check("body registers the failures", "failed" in (d.world.get("proprio").text if d.world.get("proprio") else ""))

        host.fail = True
        for _ in range(2):
            asyncio.run(d.tick())
        check("errors counted", d.error_streak == 2 and d.last_error == "provider down")
        check("error felt on the floor", "broke off" in d.world.get("proprio").text)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_daemon_guards():
    tmp = tempfile.mkdtemp()
    try:
        host = ScriptedHost()   # says the same thing every tick
        d = _daemon(tmp, host, stale_streak_limit=2, max_guard_rests=1, guard_rest_minutes=7)
        d.running = True
        for _ in range(3):
            asyncio.run(d.tick())
        check("repetition forces a rest", d.guard_rests == 1 and d.rest_request and d.rest_request[0] == 420)
        check("the body notices being made to stop", d.world.get("guard-rest") is not None)
        secs, reason = d._next_interval()
        check("rest overrides cadence", secs == 420 and "repeating" in reason)
        for _ in range(3):
            asyncio.run(d.tick())
        check("still repeating after max rests → stop", not d.running and "forced rests" in d.stop_reason)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_daemon_run_and_wake():
    tmp = tempfile.mkdtemp()
    try:
        host = ScriptedHost()

        async def scenario():
            d = _daemon(tmp, host, base_interval_seconds=60, min_interval_seconds=60)
            d.start()
            await asyncio.sleep(0.3)
            first = d.world.tick
            phase = d.phase
            t0 = time.monotonic()
            d.post_message("wake up")
            while d.world.tick == first and time.monotonic() - t0 < 5:
                await asyncio.sleep(0.05)
            woke_in = time.monotonic() - t0
            reason = d.wake_reason
            await asyncio.sleep(0.3)
            second = d.world.tick
            t1 = time.monotonic()
            await asyncio.to_thread(d.post_message, "from a worker thread")
            while d.world.tick == second and time.monotonic() - t1 < 5:
                await asyncio.sleep(0.05)
            thread_woke_in = time.monotonic() - t1
            d.pause()
            await asyncio.sleep(0.2)
            paused_phase = d.phase
            d.stop("test")
            await asyncio.sleep(0.2)
            return first, phase, woke_in, reason, paused_phase, d, thread_woke_in

        first, phase, woke_in, reason, paused_phase, d, thread_woke_in = asyncio.run(scenario())
        check("first tick runs at start", first == 1)
        check("then it sleeps on wall time", phase == "sleeping", phase)
        check("a message wakes it early", woke_in < 2 and reason == "message", (woke_in, reason))
        check("a message from another thread wakes it too", thread_woke_in < 2, thread_woke_in)
        check("pause holds it", paused_phase == "paused", paused_phase)
        check("stop ends it", not d.running and d.phase == "stopped" and d.stop_reason == "test")

        check("the field is readable after stopping", d.ticks.tail(1)[0]["view"].startswith("FIELD"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
