import asyncio
import json

from soulscript_loop import Completion, EchoBackend, LoopConfig, LoopRunner, LoopState


def _config(tmp_path, **overrides):
    base = dict(
        ticks_per_loop=5,
        max_loops=1,
        loop_interval_seconds=0,
        data_dir=str(tmp_path),
    )
    base.update(overrides)
    return LoopConfig(**base)


class ScriptedBackend:
    """Returns a fixed sequence of completions, then repeats the last one."""

    model = "scripted"

    def __init__(self, completions):
        self.completions = list(completions)
        self.calls = []

    async def complete(self, messages, tools):
        self.calls.append(messages)
        return self.completions.pop(0) if len(self.completions) > 1 else self.completions[0]


def _say(text, cost=0.0):
    return Completion(message={"role": "assistant", "content": text}, cost=cost)


def _stop_call(reason="done"):
    return Completion(
        message={
            "role": "assistant",
            "tool_calls": [{
                "id": "c1",
                "function": {
                    "name": "loop_control",
                    "arguments": json.dumps({"action": "request_stop", "reason": reason}),
                },
            }],
        },
        finish_reason="tool_calls",
    )


def test_runs_all_ticks_with_echo(tmp_path):
    runner = LoopRunner(_config(tmp_path, stale_streak_limit=0), EchoBackend())
    asyncio.run(runner.run())
    assert runner.state.total_ticks == 5
    assert runner.state.stop_reason == "max_loops_reached"
    assert (tmp_path / "loop_history.jsonl").is_file()
    assert (tmp_path / "loop_journal.jsonl").is_file()


def test_stimulus_carries_senses(tmp_path):
    backend = ScriptedBackend([_say("first"), _say("second"), _say("third")])
    runner = LoopRunner(_config(tmp_path, ticks_per_loop=2), backend)
    asyncio.run(runner.run())
    second_stimulus = backend.calls[1][-1]["content"]
    assert "SENSES" in second_stimulus
    assert "clock:" in second_stimulus
    assert "budget:" in second_stimulus
    assert "last tick: first" in second_stimulus


def test_agent_can_stop_itself(tmp_path):
    backend = ScriptedBackend([_stop_call("nothing left"), _say("stopping")])
    runner = LoopRunner(_config(tmp_path), backend)
    asyncio.run(runner.run())
    assert runner.state.total_ticks == 1
    assert runner.state.stop_reason == "agent_requested: nothing left"


def test_stale_ticks_auto_stop(tmp_path):
    runner = LoopRunner(_config(tmp_path, stale_streak_limit=2), ScriptedBackend([_say("same")]))
    asyncio.run(runner.run())
    assert runner.state.stop_reason == "stale_streak_exceeded"
    assert runner.state.total_ticks == 3


def test_session_budget_stops(tmp_path):
    backend = ScriptedBackend([_say("a", 0.6), _say("b", 0.6), _say("c", 0.6)])
    runner = LoopRunner(_config(tmp_path, per_session_cap=1.0, per_tick_cap=1.0), backend)
    asyncio.run(runner.run())
    assert runner.state.stop_reason == "session_budget_exceeded"
    assert runner.state.total_ticks == 2


def test_error_streak_stops(tmp_path):
    class Broken:
        async def complete(self, messages, tools):
            raise RuntimeError("model down")

    runner = LoopRunner(_config(tmp_path, ticks_per_loop=10, auto_pause_on_error_streak=3), Broken())
    asyncio.run(runner.run())
    assert runner.state.stop_reason == "error_streak_exceeded"
    assert runner.state.total_ticks == 3


def test_inbox_message_arrives_mid_stream(tmp_path):
    backend = ScriptedBackend([_say("one"), _say("two"), _say("three")])
    runner = LoopRunner(_config(tmp_path, ticks_per_loop=3), backend)

    async def scenario():
        runner.post_message("are you there?", sender="Trent")
        await runner.run()

    asyncio.run(scenario())
    assert "are you there?" in backend.calls[0][-1]["content"]
    assert "are you there?" not in backend.calls[1][-1]["content"]


def test_broken_sense_does_not_crash_loop(tmp_path):
    from soulscript_loop import DEFAULT_SENSES

    def broken_sense(ctx):
        raise OSError("no sensor")

    backend = ScriptedBackend([_say("a"), _say("b")])
    runner = LoopRunner(_config(tmp_path, ticks_per_loop=2), backend, senses=DEFAULT_SENSES + [broken_sense])
    asyncio.run(runner.run())
    assert runner.state.total_ticks == 2
    assert "broken_sense: (no signal" in backend.calls[0][-1]["content"]


def test_history_survives_restart(tmp_path):
    runner = LoopRunner(_config(tmp_path, ticks_per_loop=2), ScriptedBackend([_say("x"), _say("y")]))
    asyncio.run(runner.run())
    reborn = LoopRunner(_config(tmp_path), EchoBackend(), state=LoopState(tmp_path))
    assert [m["content"] for m in reborn.history if m["role"] == "assistant"] == ["x", "y"]
