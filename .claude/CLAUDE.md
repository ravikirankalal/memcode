# memcode

A memory agent for Claude Code (see README.md and docs/architecture.md).

- Keep `PLAN.md` and `STATE.md` current. After every change that lands, update `STATE.md` (what changed, versions,
  what is pending, test counts). When the direction or the next steps change, update `PLAN.md`.
- Before committing: `python3 -m unittest discover -s tests`, `claude plugin test mods/memcode-status`, and
  `claude plugin validate .claude-plugin/plugin.json --strict`.
- Releases follow the steps at the end of `STATE.md`.
