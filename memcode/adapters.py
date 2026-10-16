"""Hook payload adapters: one agent's hook event -> an engine action (Phase 4: scale out).

  python3 -m memcode.hook_cli <Event> [agent]       agent: claude (default) | codex | gemini

Sources (read 2026-10-16): Codex CLI source (codex-rs/hooks schemas, tools/handlers), Gemini CLI docs/hooks/reference.md.
  claude  SessionStart, UserPromptSubmit, PostToolUse, PostToolUseFailure, PreCompact; Bash/Edit/Write/MultiEdit
  codex   same event names and payload fields as Claude Code. Shell results arrive as tool_name "Bash" with the
          output as a plain string and NO exit code, so failure-based triggers (fail-to-fix, retry) cannot run;
          edits arrive as tool_name "apply_patch" with the patch text in tool_input.command
  gemini  SessionStart, BeforeAgent (prompt), AfterTool, PreCompress; run_shell_command / write_file / replace
All three accept {"hookSpecificOutput": {"hookEventName", "additionalContext"}} on session start and per prompt.
An exit code memcode cannot know is reported as None, never guessed: the triggers then skip that result.
"""
from __future__ import annotations

import re

_EXIT_RE = re.compile(r"Exit code (-?\d+)")
_GEMINI_EXIT_RE = re.compile(r"Exit Code:\s*(-?\d+)")
_PATCH_FILE_RE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+?)\s*$", re.M)

AGENTS = ("claude", "codex", "gemini")

# agent -> {event name: action}
EVENTS = {
    "claude": {"SessionStart": "start", "PreCompact": "prepare", "UserPromptSubmit": "prompt",
               "PostToolUse": "tool", "PostToolUseFailure": "tool_failure"},
    "codex": {"SessionStart": "start", "PreCompact": "prepare", "UserPromptSubmit": "prompt", "PostToolUse": "tool"},
    "gemini": {"SessionStart": "start", "PreCompress": "prepare", "BeforeAgent": "prompt", "AfterTool": "tool"},
}


def _text(v) -> str:
    return v if isinstance(v, str) else ("" if v is None else str(v))


def _base(d: dict, tool: str, inp: dict, code, output: str) -> dict:
    return {"kind": "tool_result", "session": d.get("session_id", "unknown"), "tool": tool, "input": inp,
            "command": inp.get("command"), "file_path": inp.get("file_path"), "exit_code": code,
            "output": output.strip()}


def _claude_tool(d: dict, failed: bool) -> list[dict]:
    resp = d.get("tool_response")
    if not isinstance(resp, dict):
        resp = {"output": _text(resp)}
    inp = d.get("tool_input") or {}
    if not isinstance(inp, dict):
        inp = {"command": _text(inp)}
    code = resp.get("exit_code", resp.get("returnCode"))
    out = _text(resp.get("stdout", resp.get("output", "")))
    err = _text(resp.get("stderr"))
    if failed:
        # PostToolUseFailure: {"error": "Exit code 1\n<stderr>", "is_interrupt": bool}
        msg = _text(d.get("error") or resp.get("error"))
        m = _EXIT_RE.search(msg)
        code = int(m.group(1)) if m else (130 if d.get("is_interrupt") else 1)
        out, err = msg, ""
    elif code is None:
        code = 130 if resp.get("interrupted") else 0   # PostToolUse only fires on success
    return [_base(d, d.get("tool_name", ""), inp, code, out + ("\n" + err if err else ""))]


def _codex_tool(d: dict) -> list[dict]:
    tool = d.get("tool_name", "")
    inp = d.get("tool_input") if isinstance(d.get("tool_input"), dict) else {}
    resp = d.get("tool_response")
    if tool == "apply_patch":                           # one Edit per file named in the patch
        files = _PATCH_FILE_RE.findall(_text(inp.get("command")))
        return [_base(d, "Edit", {"file_path": f}, 0, "") for f in dict.fromkeys(files)]
    code = None
    if isinstance(resp, dict):                          # future-proof: use an exit code if Codex ever sends one
        code = resp.get("exit_code")
        out = _text(resp.get("output", resp.get("stdout", "")))
    else:
        out = _text(resp)
    return [_base(d, tool, inp, code, out)]


def _gemini_tool(d: dict) -> list[dict]:
    name = d.get("tool_name", "")
    inp = d.get("tool_input") if isinstance(d.get("tool_input"), dict) else {}
    resp = d.get("tool_response") if isinstance(d.get("tool_response"), dict) else {}
    out = _text(resp.get("llmContent"))
    if name in ("write_file", "replace"):
        return [_base(d, "Write" if name == "write_file" else "Edit", inp, 0, "")]
    if name != "run_shell_command":
        return [_base(d, name, inp, 0, out)]
    m = _GEMINI_EXIT_RE.search(out)
    code = int(m.group(1)) if m else (1 if resp.get("error") else None)
    return [_base(d, "Bash", inp, code, out)]


def normalize(agent: str, event: str, d: dict) -> tuple[str, object]:
    """-> (action, data). action: start | prepare | prompt (data: text) | tool (data: [events]) | none."""
    action = EVENTS.get(agent, EVENTS["claude"]).get(event, "none")
    if action == "prompt":
        return "prompt", _text(d.get("prompt"))
    if action in ("tool", "tool_failure"):
        if agent == "codex":
            return "tool", _codex_tool(d)
        if agent == "gemini":
            return "tool", _gemini_tool(d)
        return "tool", _claude_tool(d, failed=(action == "tool_failure"))
    return action, None
