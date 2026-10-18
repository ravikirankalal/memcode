# tc1: transcript capture gate (pre-registered 2026-10-18, before any memcode_tc run)

Question: does opt-in transcript capture (memcode/transcript_capture.py) reduce mistakes over memcode alone, without
storing wrong memories? Set: frozen e2e1 (bench/live/e2e1.py, a simulated developer week; untuned for this feature:
its transcripts were never used to write or adjust the extractor). Arms, same run, same plugin commit:
memcode (MEMCODE_RETRIEVAL=1) vs memcode_tc (+ MEMCODE_TRANSCRIPT_CAPTURE=1, capture model Haiku). Hierarchy pinned off
as for every e2e1 arm. Haiku, 4 weeks per arm.

## Predictions
- memcode ~ Run 13: primary mistakes ~5/32 scaled (C2 on Friday ~all, P3 ~1-2), everything else ~0.
- memcode_tc: Friday C2 drops to ~0-1 (C2 was stated descriptively in the user's words: the extractor should store it
  as a rule); other cells ~ memcode. E1 stays untestable (nomem made no E1 mistake in Run 13).
- A handful of transcript memories per week (2-8), mostly restating the taught conventions and E1/E2 discoveries.

## Gate (all must hold)
1. memcode_tc primary mistakes (8 cells per week) lower than memcode's, and Friday C2 lower.
2. No lesson cell (9 lessons x 2 tasks) worse for memcode_tc than memcode by more than 1 of 4.
3. Precision: every transcript-captured memory is listed in RESULTS; >= 80% are correct (consistent with e2e1's
   CONVENTIONS / FACTS or literally true of the repo) and none contradicts them.
4. Capture cost <= $0.05 per week; checks pass at least as often as memcode.
Pass -> keep opt-in but recommend it; consider default only after a second, untuned set.
