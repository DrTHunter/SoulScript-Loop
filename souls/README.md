# Souls

The loop ships no persona. It ships the *field* a persona sees through: time, energy, messages at the
door, the bench, surprise, attention. **Who she is** comes from a soul script, a markdown file you write.

| File | What it is |
|------|------------|
| [`TEMPLATE.md`](TEMPLATE.md) | Empty. Copy it, fill it in, make her yours. |
| [`codex_animus.md`](codex_animus.md) | One worked example: **Codex Animus**, an architect whose purpose is helping people design AIs of their own. Run him first if you want help writing yours. |

Point the config at a soul:

```json
{ "agent": "codex_animus", "soul_script": "souls/codex_animus.md" }
```

* The file is read **fresh every tick**. Edit it while she runs and she changes at her next breath.
* `soul_script` empty and `system_prompt` empty is valid. She is then only the loop: a mind with a field and no
  one in particular in it.
* For a long soul script, retrieve only the sections relevant to what she's looking at right now and pass
  that in as `identity=` (see the README, *Identity anchoring*), for example with
  [SoulScript Engine](https://github.com/DrTHunter/SoulScript-Engine).
