# Replay benchmark harness

Offline, deterministic; no LLM or network. Run: `python3 bench/run.py [--configs none,triggers]`
(prints a markdown table, writes `bench/results.json`).

**Smoke test, not evidence.** The simulated agent avoids a mistake iff a retrieved
memory text contains the mistake's `key_phrase`, and skips an exploratory call iff a
memory contains its `skip_if_memory` phrase. It only validates the plumbing.

## Metrics
- repeated-mistake rate: scripted mistakes in later sessions that the agent still makes
  (also split into runs where a relevant memory existed vs not).
- exploratory calls: tool_use commands starting with ls/find/grep/rg not skipped.
- context tokens: len(retrieved memory text)/4 injected at later session starts.

## Configs
`none`, `triggers` (memcode.triggers.TriggerEngine; clear error if not importable),
`stub` (placeholder). Add one to `CONFIGS` in `run.py`: a class with `feed(event)`
and `memories() -> list[str]`.

## Adding a scenario
Add `bench/scenarios/<name>.json`:
```
{"name": ..., "description": ...,
 "mistakes": [{"id": ..., "key_phrase": "text a memory must contain", "session": 3, "event": {...}}],
 "events": [ {"kind": "prompt", "session": 1, "text": "..."},
             {"kind": "tool_use", "session": 1, "tool": "Bash", "input": {"command": "..."}},
             {"kind": "tool_result", "session": 1, "exit_code": 1, "output": "..."} ]}
```
Session 1 introduces the convention/bug and the correction; session 3 needs it. Optional
`skip_if_memory` on an exploratory tool_use marks it avoidable given that memory phrase.
