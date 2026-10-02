# Routing log

`date | task | model | inline/delegated | result | tokens (subagent total) | notes`

2026-10-02 | T1 writer spec + SKILL.md + config example | Opus | inline | pass | n/a | design work; spec doubled as brief for T2/T3/T5
2026-10-02 | T2 write_note.py | Sonnet | delegated | fix | 61.4k | 389 lines vs ~250 asked; Opus fixed trailing-dot truncation and multiline titles
2026-10-02 | T3 unittest suite (written blind from spec) | Sonnet | delegated | pass | 64.9k | 65 tests, all green against T2 first try; Opus added 2 tests for the fixes
2026-10-02 | T4 remove v1 code, package_skill.py | Opus | inline | pass | n/a | small, context loaded
2026-10-02 | T5 README rewrite | Sonnet | delegated | fix | 61.4k | Opus tweaked Tasks-plugin note; flagged missing `updated` outcome in SKILL.md
2026-10-02 | T6 review + integration | Opus | inline | pass | n/a | ran tests, packaging; reconciled SKILL.md/README/spec

Takeaway: spec-first + blind tests from a second Sonnet worker caught zero drift here; worth repeating for well-specified scripts.
