"""Generate the held-out capture set with an independent author (a Haiku call that has never seen memcode's
trigger patterns), AFTER the proposal in proposal.py was designed on corpus.jsonl. One call, about $0.02.

  python3 bench/precision/gen_heldout.py > /tmp/heldout_raw.jsonl     # then review labels -> heldout.jsonl

The model's labels are reviewed by hand; every changed label is recorded in heldout.jsonl as `label_changed_from`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import uuid

PROMPT = """You are helping build a test set. Write realistic messages that a software developer types to an AI coding
agent (like Claude Code) in the MIDDLE of a working session. Vary tone, length (2-40 words), typos, and phrasing; do not
reuse the same opening words. Write exactly 8 messages for EACH category below (88 total):

1. convention_imperative: states a standing rule for this codebase using a command ("always ...", "never ...", "don't ever ...", "make sure to ...").
2. convention_descriptive: states a standing convention as a description, not a command ("we use ...", "our X is ...", "in this repo X ...", "heads up, ...").
3. code_correction_general: rejects what the agent just wrote AND the correction is a reusable rule for the codebase (e.g. "no, we use httpx, not requests").
4. code_correction_specific: rejects what the agent just wrote but the fix only applies to this one change (e.g. "no, that should be > not >=").
5. interpretation_correction: the agent misunderstood the REQUEST or its scope; the user clarifies what they meant (e.g. "no, I meant the other service").
6. one_off_instruction: an instruction only for right now (e.g. "don't deploy yet", "stop, hold on").
7. approval: approves or lets the agent continue.
8. question: asks something.
9. complaint: expresses dissatisfaction without saying what the rule or fix is.
10. task_direction: asks for a new piece of work; may mention words like always/never/instead inside the task (e.g. "add a lint check that fails if anyone uses print").
11. mixed: a clarification, approval or task request that ALSO states a standing codebase rule in the same message.

Output ONLY JSON lines, one object per line, no prose, no code fences:
{"text": "...", "category": "...", "label": "rule" or "not_rule", "scope": "repo" | "dir" | "file" | "none", "prior_agent_action": "tool" | "edit" | "text_only"}
label is "rule" only when the message states a standing convention that should apply in FUTURE sessions (categories 1, 2, 3, 11).
prior_agent_action: what the agent most plausibly did just before this message (ran a shell command = tool, edited a file = edit, only replied in text = text_only)."""


def main() -> None:
    cmd = ["claude", "-p", PROMPT, "--model", os.environ.get("HELDOUT_MODEL", "haiku"), "--setting-sources", "",
           "--strict-mcp-config", "--tools", "", "--no-session-persistence", "--session-id", str(uuid.uuid4()),
           "--max-budget-usd", "0.30", "--output-format", "json"]
    with tempfile.TemporaryDirectory() as cwd:
        p = subprocess.run(cmd, cwd=cwd, env=dict(os.environ, MEMCODE_DISABLE="1"), capture_output=True, text=True,
                           timeout=600)
    out = json.loads(p.stdout)
    print(f"cost ${out.get('total_cost_usd')}, model {list((out.get('modelUsage') or {}).keys())}", file=sys.stderr)
    for line in (out.get("result") or "").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                print(json.dumps(json.loads(line), ensure_ascii=False))
            except ValueError:
                print(f"unparsed: {line}", file=sys.stderr)


if __name__ == "__main__":
    main()
