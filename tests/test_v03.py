"""v0.3: the quiet gate, cache breakpoints, pace, the handoff letter, the llm tool, time zones,
soul scripts, and the HUD half of her machine, all offline with a scripted model."""

import asyncio
import json
import time
from pathlib import Path

import pytest

from soulscript_loop import Completion, LoopConfig, LoopDaemon
from soulscript_loop.backend import wire_messages
from soulscript_loop.budget import DailyBudget
from soulscript_loop.host import StandaloneHost
from soulscript_loop.world import local_dt


def _call(name, args, cid="c1"):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


class Host:
    """Plays back assistant messages; records what it was sent."""

    def __init__(self, script=None, side=None):
        self.script = list(script or [])
        self.side = list(side or [])
        self.calls = []
        self.side_calls = []

    def prepare(self, agent, view):
        return [{"role": "system", "content": f"You are {agent}."}], []

    async def complete(self, config, messages, tools):
        self.calls.append([dict(m) for m in messages])
        msg = self.script.pop(0) if self.script else {"role": "assistant", "content": f"thought {len(self.calls)}"}
        return Completion(message=msg, tokens=100, cost=0.001, model="scripted", prompt_tokens=80, cached_tokens=60)

    async def side_complete(self, name, messages, max_tokens):
        self.side_calls.append((name, messages, max_tokens))
        text = self.side.pop(0) if self.side else "side answer"
        return Completion(message={"role": "assistant", "content": text}, tokens=40, cost=0.0004, model=f"m-{name}")

    def call_tool(self, agent, name, args):
        return f"{name} ok"

    def after_response(self, agent, text):
        return text

    def pending_tasks(self):
        return []


def daemon(tmp_path, host=None, **cfg):
    base = dict(agent="tester", base_interval_seconds=5, min_interval_seconds=5, max_interval_seconds=60)
    base.update(cfg)
    return LoopDaemon(host or Host(), LoopConfig.from_dict(base), tmp_path)


def tick(d):
    asyncio.run(d.tick())


# ── cache breakpoints ──────────────────────────────────────────

def test_wire_messages_strips_the_marker_and_optionally_translates():
    msgs = [{"role": "system", "content": "sys", "cache": True}, {"role": "user", "content": "now", "cache": True},
            {"role": "assistant", "content": None, "tool_calls": []}]
    plain = wire_messages(msgs, prompt_cache=False)
    assert all("cache" not in m for m in plain) and plain[0]["content"] == "sys"
    cached = wire_messages(msgs, prompt_cache=True)
    assert cached[0]["content"] == [{"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}]
    assert cached[2]["content"] is None            # nothing to mark on a tool-call message
    assert msgs[0]["cache"] is True                # the caller's list is untouched


def test_the_loop_marks_breakpoints_and_history_is_append_only(tmp_path):
    host = Host()
    d = daemon(tmp_path, host, history_window=2, quiet_gate=False)
    for _ in range(3):
        tick(d)
    last = host.calls[-1]
    assert last[0]["cache"] is True                       # end of the stable system prompt
    assert last[-1]["cache"] is True and last[-1]["role"] == "user"   # this moment
    assert last[-2].get("cache") is True                  # end of the carried history
    # window 2 → history grows to 4 before trimming, so earlier ticks keep their place in the prefix
    assert len(d.history) == 3
    for _ in range(2):
        tick(d)
    assert len(d.history) == 2
    assert d.session_cached_tokens > 0 and d.status()["session_cache"]["hit_rate"] == 0.75


# ── the quiet gate ─────────────────────────────────────────────

def test_the_quiet_gate_sleeps_through_idle_timer_wakes(tmp_path):
    host = Host()
    d = daemon(tmp_path, host, gate_max_skips=1)
    tick(d)                                   # a first wake is always a thought
    assert len(host.calls) == 1
    d.wake_reason = "timer"
    tick(d)
    assert len(host.calls) == 1 and d.gated_streak == 1       # slept through: no model call
    assert d.ticks.tail(1)[0]["gated"] is True
    spent = d.budget.tokens
    d.wake_reason = "timer"
    tick(d)                                   # gate_max_skips reached: this one comes through
    assert len(host.calls) == 2 and d.gated_streak == 0
    assert "slept through 1 quiet wake" in host.calls[-1][-1]["content"]
    assert d.budget.tokens > spent


def test_the_gate_never_swallows_a_message_or_an_acting_tick(tmp_path):
    host = Host([{"role": "assistant", "content": "", "tool_calls": [_call("attend", {"action": "unfocus"})]}])
    d = daemon(tmp_path, host)
    tick(d)
    assert d.last_result["tools"]                           # it acted
    d.wake_reason = "timer"
    assert d._gate_check([]) == "your last tick acted"
    d.last_result = {"tools": []}
    assert d._gate_check([{"text": "hi"}]) == "something new arrived"
    d.wake_reason = "message"
    assert d._gate_check([]) == "you were woken"


def test_the_mind_can_turn_the_gate_off(tmp_path):
    d = daemon(tmp_path)
    out = d.tools.execute("loop_control", {"action": "gate", "on": False, "reason": "want every wake"})
    assert "Gate off" in out and d.gate_on is False
    d.wake_reason = "timer"
    d.last_result = {"tools": []}
    assert d._gate_check([]) == ""                          # off: every wake is a thought
    d.save()
    assert daemon(tmp_path).gate_on is False                # and it persists
    off = daemon(tmp_path / "other", quiet_gate=False)
    assert "switched off by the operator" in off.tools.execute("loop_control", {"action": "gate", "on": True})


# ── pace ───────────────────────────────────────────────────────

def test_pace_is_hers_within_limits_and_survives_a_restart(tmp_path):
    d = daemon(tmp_path, min_interval_seconds=20, max_interval_seconds=600)
    assert d.set_pace(1, "something is live") == 20
    assert d.set_pace(99999) == 600
    d.set_pace(45, "steady")
    secs, _ = d._next_interval()
    assert secs == 45 and "you chose" in d.pace_note
    d.save()
    assert daemon(tmp_path, min_interval_seconds=20, max_interval_seconds=600).pace == (45, "steady")
    d.tools.execute("loop_control", {"action": "pace"})
    assert d.pace is None


# ── the handoff letter ─────────────────────────────────────────

def test_a_letter_is_the_first_thing_after_a_restart_and_only_once(tmp_path):
    d = daemon(tmp_path)
    tick(d)
    d.save()
    letter = Path(d.workbench.root) / "handoff" / "letter.md"
    letter.parent.mkdir(parents=True, exist_ok=True)
    letter.write_text("Dear me: the essay's ending is the thing. Start there.", encoding="utf-8")

    d2 = daemon(tmp_path)
    d2._admit_handoff()
    it = d2.world.get("handoff-letter")
    assert it and it.held and "the essay's ending" in it.text
    assert d2.world.focus_item == it.id
    d2.save()

    d3 = daemon(tmp_path)
    d3._admit_handoff()
    again = d3.world.get("handoff-letter")
    assert "didn't leave a new letter" in again.text and not again.held

    letter.write_text("A new one.", encoding="utf-8")
    d4 = daemon(tmp_path)
    d4._admit_handoff()
    assert "A new one." in d4.world.get("handoff-letter").text


def test_no_letter_on_a_first_life(tmp_path):
    d = daemon(tmp_path)
    letter = Path(d.workbench.root) / "handoff" / "letter.md"
    letter.parent.mkdir(parents=True, exist_ok=True)
    letter.write_text("not for this gap", encoding="utf-8")
    d._admit_handoff()
    assert d.world.get("handoff-letter") is None


# ── the llm tool ───────────────────────────────────────────────

LLM = {"models": {"fast": {"model": "small"}, "deep": {"model": "big"}}, "default": "fast", "max_tokens": 500}


def test_llm_is_off_until_models_are_listed(tmp_path):
    assert "llm" not in daemon(tmp_path).tools.names()
    d = daemon(tmp_path / "x", llm=LLM)
    assert "llm" in d.tools.names()
    spec = next(t for t in d.tools.definitions() if t["function"]["name"] == "llm")["function"]
    assert spec["parameters"]["properties"]["model"]["enum"] == ["fast", "deep"]


def test_llm_side_call_is_charged_to_the_tick_and_sees_only_the_prompt(tmp_path):
    host = Host([{"role": "assistant", "content": "", "tool_calls": [
        _call("llm", {"prompt": "summarise: a b c", "model": "deep", "system": "be terse", "max_tokens": 9999})]}],
        side=["a,b,c"])
    d = daemon(tmp_path, host, llm=LLM)
    tick(d)
    name, messages, cap = host.side_calls[0]
    assert name == "deep" and cap == 500                    # the operator's ceiling holds
    assert messages == [{"role": "system", "content": "be terse"}, {"role": "user", "content": "summarise: a b c"}]
    result = d.ticks.tail(1)[0]["tool_calls"][0]["result"]
    assert "a,b,c" in result and "m-deep" in result
    entry = d.ticks.tail(1)[0]
    assert entry["tokens"] == 100 + 100 + 40 and entry["cost"] == pytest.approx(0.001 * 2 + 0.0004)  # two model steps + side


def test_llm_default_is_hers_to_change_and_persists(tmp_path):
    host = Host()
    d = daemon(tmp_path, host, llm=LLM)
    assert d.llm_default() == "fast"
    out = asyncio.run(d.side_llm({"set_default": "deep"}))
    assert "now deep" in out and d.llm_default() == "deep" and not host.side_calls
    d.save()
    assert daemon(tmp_path, host, llm=LLM).llm_default() == "deep"
    assert asyncio.run(d.side_llm({"prompt": "x", "model": "nope"})).startswith("Error: no model 'nope'")
    assert asyncio.run(d.side_llm({})).startswith("Error: llm needs a prompt")


def test_standalone_host_builds_side_backends_from_the_main_connection(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEP_KEY", "k2")
    cfg = LoopConfig.from_dict({"backend": {"type": "openai", "base_url": "http://x/v1", "model": "main",
                                            "api_key_env": "MAIN_KEY", "prompt_cache": True},
                                "llm": {"models": {"a": {"model": "ma"},
                                                   "b": {"model": "mb", "base_url": "http://y/v1", "api_key_env": "DEEP_KEY"}}}})
    seen = {}

    class Fake:
        def __init__(self, **kw):
            seen.update({kw["model"]: kw})

        async def complete(self, messages, tools, max_tokens=0):
            return Completion(message={"content": "ok"})

    monkeypatch.setattr("soulscript_loop.host.OpenAICompatibleBackend", Fake)
    host = StandaloneHost(cfg, backend=None)
    asyncio.run(host.side_complete("a", [], 10))
    asyncio.run(host.side_complete("b", [], 10))
    assert seen["ma"]["base_url"] == "http://x/v1" and seen["ma"]["prompt_cache"] is True
    assert seen["mb"]["base_url"] == "http://y/v1" and seen["mb"]["api_key"] == "k2"


# ── time zones ─────────────────────────────────────────────────

def test_her_clock_is_yours(tmp_path):
    pytest.importorskip("zoneinfo")
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo("Asia/Tokyo")
    except Exception:
        pytest.skip("no tz database")
    now = 1_760_000_000.0
    assert local_dt(now, "Asia/Tokyo").strftime("%Z") == "JST"
    assert local_dt(now, "Not/AZone").utcoffset().total_seconds() == 0   # unknown → UTC

    d = daemon(tmp_path, timezone="Asia/Tokyo", quiet_gate=False)
    tick(d)
    view = d.ticks.tail(1)[0]["view"]
    assert "JST" in view.splitlines()[0] and "⏲ now" in view and "UTC" in view
    b = DailyBudget(tmp_path / "b.json", 1000, tz="Asia/Tokyo")
    assert 0 < b.seconds_until_reset() <= 86400 + 5


# ── soul scripts ───────────────────────────────────────────────

def test_the_soul_script_file_is_read_fresh_every_tick(tmp_path):
    soul = tmp_path / "soul.md"
    soul.write_text("I am the first draft.", encoding="utf-8")
    cfg = LoopConfig.from_dict({"soul_script": str(soul), "system_prompt": "ignored"})
    host = StandaloneHost(cfg, backend=None)
    assert host.prepare("a", "")[0][0]["content"] == "I am the first draft."
    soul.write_text("I am the second.", encoding="utf-8")
    assert host.prepare("a", "")[0][0]["content"] == "I am the second."
    soul.unlink()
    assert host.prepare("a", "")[0][0]["content"] == "ignored"      # missing file → inline prompt
    assert StandaloneHost(LoopConfig(), backend=None).prepare("a", "")[0][0]["content"] == ""   # empty is valid


# ── the HUD half of her machine ────────────────────────────────

class FakeMachine:
    hud_url = "http://box"

    def __init__(self, control=None):
        self.control = control
        self.pushed = []

    def read_file(self, path):
        return {"ok": True, "content": json.dumps(self.control)} if self.control is not None else {"ok": False}

    def push_hud(self, payload):
        self.pushed.append(payload)


def test_hud_payload_is_measurements_and_control_is_applied_once(tmp_path):
    d = daemon(tmp_path, quiet_gate=False)
    d.machine = FakeMachine({"seq": 1, "reason": "focus", "pace_seconds": 30, "rest_minutes": 10, "note": "check the build",
                             "declare": {"x": "y"}})
    tick(d)
    assert d.pace[0] == 30 and d.rest_request[0] == 600
    assert d.world.get("control-note:1") is not None
    assert d.control_ack["seq"] == 1 and any("unknown key 'declare'" in r for r in d.control_ack["refused"])
    first_ack = dict(d.control_ack)
    d.rest_request = None
    tick(d)
    assert d.control_ack == first_ack                                  # seq didn't go up: not applied again
    assert d.rest_request is None
    time.sleep(0.2)   # the push runs on a thread
    assert d.machine.pushed and d.machine.pushed[-1]["tick"] == 2
    payload = d.machine.pushed[-1]
    assert payload["hud_lines"][0].startswith("FIELD") and "energy" in payload and payload["control"]["seq"] == 1


# ── the shipped configs ────────────────────────────────────────

ROOT = Path(__file__).parent.parent


def test_shipped_configs_load_and_the_blank_one_has_no_persona(tmp_path):
    example = LoopConfig.from_file(ROOT / "config.example.json")
    assert example.agent == "codex_animus" and (ROOT / example.soul_script).is_file()
    assert example.system_prompt == "" and example.llm == {} and example.quiet_gate is True
    blank = LoopConfig.from_file(ROOT / "config.blank.json")
    assert blank.agent == "mine" and "Name" in (ROOT / blank.soul_script).read_text(encoding="utf-8")
    assert not blank.system_prompt


def test_codex_animus_runs_a_tick_end_to_end_offline(tmp_path):
    from soulscript_loop import EchoBackend, build_loop
    cfg = LoopConfig.from_file(ROOT / "config.example.json")
    cfg.soul_script = str(ROOT / cfg.soul_script)
    cfg.data_dir = str(tmp_path)
    d = build_loop(cfg, backend=EchoBackend())
    asyncio.run(d.tick())
    assert d.ticks.tail(1)[0]["response"].startswith("I see it.")
    system = d.host.prepare("codex_animus", "")[0][0]["content"]
    assert "Codex Animus" in system and "In the Loop" in system
