"""`memcode setup <agent>`: print the configuration that wires memcode into another agent (Phase 4).

Formats verified against the agents' sources on 2026-10-16: Codex CLI codex-rs/config/src/hook_config.rs
([[hooks.<Event>]] matcher groups with [[hooks.<Event>.hooks]] command handlers; [mcp_servers.<name>]) and Gemini CLI
docs/hooks/reference.md (settings.json "hooks" matcher groups, timeouts in ms; "mcpServers").
"""
from __future__ import annotations

import json
import os
import shlex
import sys

LAUNCHER = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "bin", "memcode")

# agent -> [(event, matcher or None, timeout seconds)]
HOOKS = {
    "codex": [("SessionStart", None, 30), ("UserPromptSubmit", None, 10), ("PostToolUse", "Bash|apply_patch", 10),
              ("PreCompact", None, 30)],
    "gemini": [("SessionStart", None, 30), ("BeforeAgent", None, 10),
               ("AfterTool", "run_shell_command|write_file|replace", 10), ("PreCompress", None, 30)],
}


def _cmd(event: str, agent: str) -> str:
    return " ".join(shlex.quote(p) for p in (sys.executable, LAUNCHER, "hook", event, agent))


def codex() -> str:
    q = json.dumps                                    # TOML basic strings share JSON's escaping for these values
    out = ["# memcode for Codex CLI: add to ~/.codex/config.toml (Codex may ask you to trust new hooks).",
           "[mcp_servers.memcode]", f"command = {q(sys.executable)}", f"args = [{q(LAUNCHER)}, \"mcp\"]", ""]
    for event, matcher, timeout in HOOKS["codex"]:
        out.append(f"[[hooks.{event}]]")
        if matcher:
            out.append(f"matcher = {q(matcher)}")
        out += [f"[[hooks.{event}.hooks]]", 'type = "command"', f"command = {q(_cmd(event, 'codex'))}",
                f"timeout = {timeout}", ""]
    out.append("# Limits under Codex: shell results carry no exit code, so fail-to-fix and retry memories are not")
    out.append("# captured; corrections, reverts and dependency changes are. Per-prompt retrieval works.")
    return "\n".join(out)


def gemini() -> str:
    cfg = {"mcpServers": {"memcode": {"command": sys.executable, "args": [LAUNCHER, "mcp"]}},
           "hooks": {event: [dict({"matcher": m} if m else {}, hooks=[{
               "type": "command", "name": f"memcode-{event}", "command": _cmd(event, "gemini"), "timeout": t * 1000}])]
               for event, m, t in HOOKS["gemini"]}}
    return ("// memcode for Gemini CLI: merge into .gemini/settings.json (project) or ~/.gemini/settings.json\n"
            + json.dumps(cfg, indent=2))


AGENTS = {"codex": codex, "gemini": gemini}


def render(agent: str) -> str:
    if agent not in AGENTS:
        raise ValueError(f"unknown agent {agent!r} (supported: {', '.join(AGENTS)}; Claude Code uses the plugin)")
    return AGENTS[agent]()
