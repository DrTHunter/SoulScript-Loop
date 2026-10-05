import asyncio
import json

import time

from soulscript_loop import Completion, EchoBackend, HashEmbedder, LoopConfig, Workbench, build_loop
from soulscript_loop.budget import DailyBudget
from soulscript_loop.channels import ChannelContext, bench_channel
from soulscript_loop.world import InnerWorld


def test_write_read_append_list_delete(tmp_path):
    wb = Workbench(tmp_path)
    assert json.loads(wb.execute({"action": "write", "path": "drafts/poem.md", "content": "line one\n"}))["ok"]
    wb.execute({"action": "append", "path": "drafts/poem.md", "content": "line two\n"})
    assert wb.execute({"action": "read", "path": "drafts/poem.md"}) == "line one\nline two\n"
    assert [f["path"] for f in json.loads(wb.execute({"action": "list"}))["files"]] == ["drafts/poem.md"]
    assert json.loads(wb.execute({"action": "delete", "path": "drafts/poem.md"}))["ok"]
    assert json.loads(wb.execute({"action": "list"}))["files"] == []


def test_paths_cannot_escape(tmp_path):
    wb = Workbench(tmp_path / "bench")
    (tmp_path / "secret.txt").write_text("nope")
    for bad in ["../secret.txt", str(tmp_path / "secret.txt"), "a/../../secret.txt"]:
        result = json.loads(wb.execute({"action": "read", "path": bad}))
        assert result["ok"] is False and "outside" in result["reason"]
    result = json.loads(wb.execute({"action": "write", "path": "../escape.txt", "content": "x"}))
    assert result["ok"] is False
    assert not (tmp_path / "escape.txt").exists()


def test_size_limits(tmp_path):
    wb = Workbench(tmp_path, max_file_bytes=10, max_total_bytes=15)
    assert json.loads(wb.execute({"action": "write", "path": "a", "content": "x" * 11}))["ok"] is False
    assert json.loads(wb.execute({"action": "write", "path": "a", "content": "x" * 10}))["ok"]
    assert json.loads(wb.execute({"action": "write", "path": "b", "content": "x" * 10}))["ok"] is False


def test_reflections_are_protected_and_sensed(tmp_path):
    wb = Workbench(tmp_path)
    assert json.loads(wb.execute({"action": "write", "path": ".reflections.jsonl", "content": "x"}))["ok"] is False
    wb.execute({"action": "write", "path": "tool_idea.md", "content": "sketch"})
    wb.execute({"action": "reflect", "built": "a sketch", "worked": "outline", "didnt": "naming", "next": "finish the parser"})
    ctx = ChannelContext(now=time.time(), tick=1, world=InnerWorld(), budget=DailyBudget(tmp_path / "b.json", 1000),
                         workbench=wb)
    sig = bench_channel(ctx)
    texts = [i["text"] for i in sig.items]
    assert any(t.startswith("tool_idea.md") for t in texts)
    assert "you planned next: finish the parser" in texts


def test_runner_gives_persona_a_workbench(tmp_path):
    class Builder:
        def __init__(self):
            self.calls = []

        async def complete(self, messages, tools):
            self.calls.append(messages)
            if len(self.calls) == 1:
                return Completion(
                    message={"role": "assistant", "tool_calls": [{
                        "id": "w1",
                        "function": {"name": "workbench", "arguments": json.dumps(
                            {"action": "write", "path": "plan.md", "content": "step 1"})},
                    }]},
                    finish_reason="tool_calls",
                )
            return Completion(message={"role": "assistant", "content": f"tick {len(self.calls)}"})

    backend = Builder()
    daemon = build_loop(LoopConfig(data_dir=str(tmp_path)), backend=backend, embedder=HashEmbedder())
    asyncio.run(daemon.tick())
    asyncio.run(daemon.tick())
    assert (tmp_path / "workbench" / "plan.md").read_text() == "step 1"
    assert "plan.md" in backend.calls[-1][-1]["content"]


def test_workbench_can_be_disabled(tmp_path):
    daemon = build_loop(LoopConfig(data_dir=str(tmp_path), workbench=False), backend=EchoBackend(), embedder=HashEmbedder())
    assert daemon.workbench is None
    assert "workbench" not in daemon.tools.names()
