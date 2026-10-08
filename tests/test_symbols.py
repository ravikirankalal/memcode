import tempfile
import unittest
from pathlib import Path

from memcode import store, symbols, tree
from memcode.triggers import TriggerEngine

SRC = '''import os


def alpha(x):
    return x + 1


class Box:
    def put(self, v):
        self.v = v

    def get(self):
        return self.v


def omega():
    return 0
'''


class Symbols(unittest.TestCase):
    def test_hash_ignores_comments_and_formatting_but_not_code(self):
        a = symbols.python_symbols(SRC)["alpha"][0]
        self.assertEqual(symbols.python_symbols(SRC.replace("return x + 1", "return x+1  # note"))["alpha"][0], a)
        self.assertNotEqual(symbols.python_symbols(SRC.replace("x + 1", "x + 2"))["alpha"][0], a)
        self.assertEqual(sorted(symbols.python_symbols(SRC)), ["Box", "Box.get", "Box.put", "alpha", "omega"])

    def test_symbol_for_snippet_picks_innermost(self):
        self.assertEqual(symbols.symbol_for_snippet(SRC, "self.v = v")[0], "Box.put")
        self.assertEqual(symbols.symbol_for_snippet(SRC, "return 0")[0], "omega")
        self.assertIsNone(symbols.symbol_for_snippet(SRC, "import os"))          # outside any symbol
        self.assertIsNone(symbols.symbol_for_snippet(SRC, "not in the file"))
        self.assertIsNone(symbols.symbol_for_snippet("def f(:\n", "x"))          # unparseable

    def test_ambiguous_snippet_is_not_guessed(self):
        dup = "def a():\n    return 1\n\n\ndef b():\n    return 1\n"
        self.assertIsNone(symbols.symbol_for_snippet(dup, "return 2"))
        self.assertEqual(symbols.symbol_for_snippet(dup, "return 1")[0], "a")   # exact match uses first occurrence


class Staleness(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.f = Path(self.root) / "m.py"
        self.f.write_text(SRC)
        self.con = store.connect(self.root)
        name, h = symbols.symbol_for_snippet(SRC, "return x + 1")
        self.mid = store.add_memory(self.con, "fail_to_fix", "note", "m.py", store.sha1(SRC.encode()), {},
                                    anchor_symbol=name, symbol_hash=h)

    def stale(self):
        tree.mark_stale(self.con, self.root)
        return bool(self.con.execute("SELECT stale FROM memories WHERE id=?", (self.mid,)).fetchone()[0])

    def test_edit_to_other_function_keeps_memory_fresh(self):
        self.f.write_text(SRC.replace("return 0", "return 42"))
        self.assertFalse(self.stale())

    def test_edit_to_same_function_makes_it_stale_and_reverting_revives(self):
        self.f.write_text(SRC.replace("x + 1", "x + 2"))
        self.assertTrue(self.stale())
        self.f.write_text(SRC)
        self.assertFalse(self.stale())

    def test_comment_only_edit_stays_fresh_and_removed_symbol_is_stale(self):
        self.f.write_text(SRC.replace("def alpha(x):", "# helper\ndef alpha(x):"))
        self.assertFalse(self.stale())
        self.f.write_text(SRC.replace("def alpha(x)", "def renamed(x)"))
        self.assertTrue(self.stale())

    def test_unparseable_file_falls_back_to_file_hash(self):
        self.f.write_text("def broken(:\n")
        self.assertTrue(self.stale())          # file hash differs
        self.f.write_text(SRC)
        self.assertFalse(self.stale())


class EndToEnd(unittest.TestCase):
    def test_fail_to_fix_anchors_the_edited_function_and_survives_other_edits(self):
        root = tempfile.mkdtemp()
        f = Path(root) / "m.py"
        f.write_text(SRC)
        con = store.connect(root)
        ev = [{"kind": "tool_use", "session": "s", "tool": "Bash", "input": {"command": "pytest -q"}},
              {"kind": "tool_result", "session": "s", "tool": "Bash", "input": {"command": "pytest -q"}, "exit_code": 1, "output": "x"}]
        for e in ev:
            TriggerEngine(con, root).handle(dict(e))
        f.write_text(SRC.replace("x + 1", "x + 2"))
        TriggerEngine(con, root).handle({"kind": "tool_use", "session": "s", "tool": "Edit",
                                         "input": {"file_path": "m.py", "old_string": "x + 1", "new_string": "x + 2"}})
        for e in ev:
            TriggerEngine(con, root).handle(dict(e, exit_code=0) if e["kind"] == "tool_result" else dict(e))
        m = store.list_memories(con)[0]
        self.assertEqual((m["trigger"], m["anchor_symbol"]), ("fail_to_fix", "alpha"))
        f.write_text(f.read_text().replace("return 0", "return 7"))          # agent keeps working elsewhere
        tree.mark_stale(con, root)
        self.assertEqual(len(store.list_memories(con)), 1)                   # still fresh (was stale before)


if __name__ == "__main__":
    unittest.main()
