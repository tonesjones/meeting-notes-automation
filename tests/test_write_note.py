"""Tests for skills/meeting-to-obsidian/scripts/write_note.py (written from the spec)."""

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
SCRIPTS_DIR = REPO_ROOT / "skills" / "meeting-to-obsidian" / "scripts"
SCRIPT = SCRIPTS_DIR / "write_note.py"
FIXTURES = TESTS_DIR / "fixtures"

sys.path.insert(0, str(SCRIPTS_DIR))

import write_note  # noqa: E402


def read_text_exact(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def minimal(**overrides):
    payload = {"title": "Standup", "date": "2026-06-25"}
    payload.update(overrides)
    return payload


def config(**overrides):
    cfg = copy.deepcopy(write_note.DEFAULT_CONFIG)
    cfg.update(overrides)
    return cfg


def render(payload, **cfg_overrides):
    return write_note.render_note(write_note.validate(payload), config(**cfg_overrides))


class FullRenderTests(unittest.TestCase):
    def test_full_render_matches_fixture_byte_exact(self):
        payload = json.loads(read_text_exact(FIXTURES / "full_meeting.json"))
        expected = read_text_exact(FIXTURES / "full_meeting.expected.md")
        actual = write_note.render_note(write_note.validate(payload), config())
        self.assertEqual(actual, expected)
        self.assertTrue(actual.endswith("\n"))
        self.assertFalse(actual.endswith("\n\n"))
        self.assertNotIn("\r", actual)


class RenderTests(unittest.TestCase):
    def test_minimal_payload(self):
        out = render(minimal())
        expected = (
            "---\n"
            'meeting_id: "2026-06-25|standup"\n'
            "date: 2026-06-25\n"
            "tags:\n"
            "  - meeting\n"
            "---\n"
            "\n"
            "# Standup\n"
            "\n"
            "**Date:** 2026-06-25\n"
            "\n"
            "## Summary\n"
            "_No summary captured._\n"
            "\n"
            "## Action Items\n"
            "_None._\n"
        )
        self.assertEqual(out, expected)

    def test_minimal_omits_optional_lines_and_sections(self):
        out = render(minimal())
        for absent in ("time:", "organizer:", "company:", "attendees:", "source:",
                       "**Company:**", "**Attendees:**", "## Decisions", "## Notes",
                       "Open Teams recap"):
            self.assertNotIn(absent, out)

    def test_start_time_only(self):
        out = render(minimal(start_time="09:30"))
        self.assertIn('time: "09:30"\n', out)
        self.assertIn("**Date:** 2026-06-25 09:30\n", out)

    def test_end_time_without_start_is_ignored(self):
        out = render(minimal(end_time="10:00"))
        self.assertNotIn("time:", out)
        self.assertNotIn("10:00", out)

    def test_link_flags_off_gives_plain_names(self):
        payload = json.loads(read_text_exact(FIXTURES / "full_meeting.json"))
        out = render(payload, link_people=False, link_company=False)
        self.assertNotIn("[[", out)
        self.assertIn('organizer: "Tony Jiang"\n', out)
        self.assertIn('company: "Acme Corp"\n', out)
        self.assertIn('  - "Alice Chen"\n', out)
        self.assertIn("**Attendees:** Tony Jiang, Alice Chen\n", out)
        self.assertIn("- [ ] Schedule procurement follow-up — Bob Rivera\n", out)

    def test_link_flags_are_independent(self):
        out = render(minimal(company="Acme", organizer="Tony"),
                     link_people=False, link_company=True)
        self.assertIn('company: "[[Acme]]"', out)
        self.assertIn('organizer: "Tony"', out)

    def test_link_names_drop_wikilink_unsafe_chars(self):
        out = render(minimal(attendees=["Al [Chen] | A#B ^C   D"]))
        self.assertIn('  - "[[Al Chen AB C D]]"\n', out)

    def test_tags_sanitized_merged_and_deduped(self):
        out = render(minimal(tags=["#customer", "  big deal  ", "meeting", "customer", "#", "  "]))
        tags_block = out.split("tags:\n", 1)[1].split("---", 1)[0]
        self.assertEqual(tags_block, "  - meeting\n  - customer\n  - big-deal\n")

    def test_tags_whitespace_runs_become_single_dash(self):
        out = render(minimal(tags=["q3   planning\tkickoff"]))
        self.assertIn("  - q3-planning-kickoff\n", out)

    def test_empty_merged_tags_emit_empty_list(self):
        out = render(minimal(), default_tags=[])
        self.assertIn("tags: []\n", out)

    def test_attendees_deduped_preserving_order(self):
        out = render(minimal(attendees=["Bob", " Alice ", "Bob", "", "Alice", "Carol"]))
        self.assertIn("**Attendees:** [[Bob]], [[Alice]], [[Carol]]\n", out)
        self.assertEqual(out.count('  - "[[Bob]]"'), 1)

    def test_yaml_quoting_of_colon_and_double_quote(self):
        tricky = 'Tony: "TJ" Jiang'
        out = render(minimal(title='Review: "Q2" plan', organizer=tricky,
                             attendees=[tricky]),
                     link_people=False)
        quoted = json.dumps(tricky, ensure_ascii=False)
        self.assertIn("organizer: " + quoted + "\n", out)
        self.assertIn("  - " + quoted + "\n", out)
        # the heading is plain markdown, not quoted
        self.assertIn('# Review: "Q2" plan\n', out)

    def test_yaml_quoting_keeps_non_ascii_unescaped(self):
        out = render(minimal(organizer="José Núñez"), link_people=False)
        self.assertIn('organizer: "José Núñez"\n', out)

    def test_iso_due_gets_calendar_marker(self):
        out = render(minimal(action_items=[{"task": "Ship it", "owner": "Bob", "due": "2026-07-01"}]))
        self.assertIn("- [ ] Ship it — [[Bob]] \U0001F4C5 2026-07-01\n", out)

    def test_non_iso_due_rendered_as_due_text(self):
        out = render(minimal(action_items=[{"task": "Ship it", "due": "next Friday"}]))
        self.assertIn("- [ ] Ship it (due next Friday)\n", out)
        self.assertNotIn("\U0001F4C5", out)

    def test_notes_inserted_verbatim_with_rstrip(self):
        out = render(minimal(notes="Line one\n\n- item\n\n\n"))
        self.assertTrue(out.endswith("## Notes\nLine one\n\n- item\n"))

    def test_source_link_after_blank_line_without_notes(self):
        out = render(minimal(source_url="https://example.com/r"))
        self.assertTrue(out.endswith("_None._\n\n[Open Teams recap](https://example.com/r)\n"))
        self.assertIn('source: "https://example.com/r"\n', out)


class MeetingIdTests(unittest.TestCase):
    def test_derived_meeting_id(self):
        payload = write_note.validate(minimal(title="  Weekly SYNC  "))
        self.assertEqual(write_note.meeting_id_for(payload), "2026-06-25|weekly sync")

    def test_explicit_meeting_id_wins(self):
        payload = write_note.validate(minimal(meeting_id="abc123"))
        self.assertEqual(write_note.meeting_id_for(payload), "abc123")

    def test_blank_meeting_id_falls_back_to_derived(self):
        payload = write_note.validate(minimal(meeting_id=""))
        self.assertEqual(write_note.meeting_id_for(payload), "2026-06-25|standup")

    def test_derived_id_written_into_frontmatter(self):
        self.assertIn('meeting_id: "2026-06-25|standup"\n', render(minimal()))


class NotePathTests(unittest.TestCase):
    def test_path_uses_subfolder_year_and_date_title(self):
        vault = Path("vault")
        p = write_note.note_path(write_note.validate(minimal()), config(), vault)
        self.assertEqual(p, vault / "Meetings" / "2026" / "2026-06-25 - Standup.md")

    def test_custom_subfolder(self):
        vault = Path("vault")
        p = write_note.note_path(write_note.validate(minimal()),
                                 config(meetings_subfolder="Work/Calls"), vault)
        self.assertEqual(p, vault / "Work" / "Calls" / "2026" / "2026-06-25 - Standup.md")

    def test_filename_illegal_characters_replaced(self):
        payload = write_note.validate(minimal(title='A<b>:c"d/e\\f|g?h*i\tj'))
        name = write_note.note_path(payload, config(), Path("vault")).name
        for ch in '<>:"/\\|?*\t':
            self.assertNotIn(ch, name)
        self.assertTrue(name.startswith("2026-06-25 - A-b"))
        self.assertTrue(name.endswith(".md"))

    def test_filename_trailing_dots_and_spaces_stripped(self):
        payload = write_note.validate(minimal(title="Wrap up...  "))
        name = write_note.note_path(payload, config(), Path("vault")).name
        self.assertEqual(name, "2026-06-25 - Wrap up.md")

    def test_filename_truncated(self):
        payload = write_note.validate(minimal(title="x" * 400))
        name = write_note.note_path(payload, config(), Path("vault")).name
        self.assertTrue(name.endswith(".md"))
        self.assertLessEqual(len(name), 150 + len(".md"))

    def test_truncation_does_not_leave_trailing_dot_or_space(self):
        # "2026-06-25 - " is 13 chars; put a space then dots right at the 150 cut.
        payload = write_note.validate(minimal(title="x" * 135 + " ...." + "y" * 20))
        stem = write_note.note_path(payload, config(), Path("vault")).stem
        self.assertFalse(stem.endswith((".", " ")), stem)

    def test_multiline_title_collapsed_to_one_line(self):
        payload = write_note.validate(minimal(title="Acme\nQuarterly  Review"))
        self.assertEqual(payload["title"], "Acme Quarterly Review")
        self.assertIn("# Acme Quarterly Review\n", write_note.render_note(payload, config()))


class ValidationTests(unittest.TestCase):
    def assertInvalid(self, payload, field):
        with self.assertRaises(write_note.PayloadError) as ctx:
            write_note.validate(payload)
        self.assertIn(field, str(ctx.exception))

    def test_payload_error_is_value_error(self):
        self.assertTrue(issubclass(write_note.PayloadError, ValueError))

    def test_missing_title(self):
        self.assertInvalid({"date": "2026-06-25"}, "title")

    def test_blank_title(self):
        self.assertInvalid(minimal(title="   "), "title")

    def test_missing_date(self):
        self.assertInvalid({"title": "X"}, "date")

    def test_bad_date_format(self):
        self.assertInvalid(minimal(date="25/06/2026"), "date")

    def test_impossible_date(self):
        self.assertInvalid(minimal(date="2026-02-30"), "date")

    def test_bad_start_time(self):
        self.assertInvalid(minimal(start_time="2pm"), "start_time")

    def test_bad_end_time(self):
        self.assertInvalid(minimal(end_time="9:5"), "end_time")

    def test_attendees_not_a_list(self):
        self.assertInvalid(minimal(attendees="Alice, Bob"), "attendees")

    def test_attendees_with_non_string_item(self):
        self.assertInvalid(minimal(attendees=["Alice", 7]), "attendees")

    def test_action_item_without_task(self):
        self.assertInvalid(minimal(action_items=[{"owner": "Bob"}]), "task")

    def test_action_item_with_blank_task(self):
        self.assertInvalid(minimal(action_items=[{"task": "  "}]), "task")

    def test_valid_payload_normalized_and_input_not_mutated(self):
        original = minimal(attendees=[" A ", "", "A", "B"], summary=["  s  ", ""],
                           bogus="ignored")
        snapshot = copy.deepcopy(original)
        result = write_note.validate(original)
        self.assertEqual(original, snapshot)
        self.assertEqual(result["attendees"], ["A", "B"])
        self.assertEqual(result["summary"], ["s"])


class LoadConfigTests(unittest.TestCase):
    def test_none_gives_defaults(self):
        self.assertEqual(write_note.load_config(None), write_note.DEFAULT_CONFIG)

    def test_file_values_merged_over_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "c.json"
            p.write_text(json.dumps({"link_people": False, "meetings_subfolder": "Calls"}),
                         encoding="utf-8")
            cfg = write_note.load_config(p)
        self.assertFalse(cfg["link_people"])
        self.assertEqual(cfg["meetings_subfolder"], "Calls")
        self.assertTrue(cfg["link_company"])
        self.assertEqual(cfg["default_tags"], ["meeting"])

    def test_explicit_missing_path_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(write_note.PayloadError):
                write_note.load_config(Path(tmp) / "nope.json")


class WriteTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.vault = Path(self._tmp.name)
        self.cfg = config()

    def do_write(self, payload, update=False):
        return write_note.write(write_note.validate(payload), self.cfg, self.vault, update=update)

    def test_write_twice_created_then_exists(self):
        first = self.do_write(minimal(meeting_id="m1"))
        self.assertEqual(first["status"], "created")
        self.assertEqual(first["meeting_id"], "m1")
        path = Path(first["path"])
        self.assertTrue(path.is_file())
        self.assertEqual(path, self.vault / "Meetings" / "2026" / "2026-06-25 - Standup.md")

        before = path.read_bytes()
        second = self.do_write(minimal(meeting_id="m1", summary=["changed"]))
        self.assertEqual(second["status"], "exists")
        self.assertEqual(second["path"], first["path"])
        self.assertEqual(path.read_bytes(), before)

    def test_written_file_is_utf8_with_lf_newlines(self):
        res = self.do_write(minimal(meeting_id="m1", organizer="José Núñez"))
        raw = Path(res["path"]).read_bytes()
        self.assertNotIn(b"\r", raw)
        self.assertIn("José Núñez".encode("utf-8"), raw)

    def test_derived_id_deduplicates(self):
        self.assertEqual(self.do_write(minimal())["status"], "created")
        res = self.do_write(minimal())
        self.assertEqual(res["status"], "exists")
        self.assertEqual(res["meeting_id"], "2026-06-25|standup")

    def test_update_overwrites_same_path_even_if_title_changes(self):
        first = self.do_write(minimal(meeting_id="m1"))
        res = self.do_write(minimal(meeting_id="m1", title="Renamed", date="2026-07-01",
                                    summary=["new summary"]), update=True)
        self.assertEqual(res["status"], "updated")
        self.assertEqual(res["path"], first["path"])
        text = read_text_exact(first["path"])
        self.assertIn("new summary", text)
        self.assertIn("# Renamed", text)
        md_files = list((self.vault / "Meetings").rglob("*.md"))
        self.assertEqual(len(md_files), 1)

    def test_update_without_existing_note_creates(self):
        res = self.do_write(minimal(meeting_id="m1"), update=True)
        self.assertEqual(res["status"], "created")

    def test_same_date_and_title_different_id_gets_numeric_suffix(self):
        a = self.do_write(minimal(meeting_id="a"))
        b = self.do_write(minimal(meeting_id="b"))
        c = self.do_write(minimal(meeting_id="c"))
        self.assertEqual(b["status"], "created")
        self.assertNotEqual(a["path"], b["path"])
        self.assertEqual(Path(b["path"]).name, "2026-06-25 - Standup (2).md")
        self.assertEqual(Path(c["path"]).name, "2026-06-25 - Standup (3).md")

    def test_find_filed_maps_ids_to_paths(self):
        a = self.do_write(minimal(meeting_id="a"))
        b = self.do_write(minimal(meeting_id='we"ird: id', title="Other", date="2025-01-02"))
        filed = write_note.find_filed(self.vault, self.cfg)
        self.assertEqual(filed, {"a": Path(a["path"]), 'we"ird: id': Path(b["path"])})

    def test_find_filed_without_meetings_folder_is_empty(self):
        self.assertEqual(write_note.find_filed(self.vault, self.cfg), {})

    def test_find_filed_reads_unquoted_ids_and_ignores_other_notes(self):
        folder = self.vault / "Meetings" / "2024"
        folder.mkdir(parents=True)
        (folder / "hand.md").write_text("---\nmeeting_id: plain-id\ndate: 2024-01-01\n---\n\nbody\n",
                                        encoding="utf-8")
        (folder / "nofm.md").write_text("# no frontmatter\n", encoding="utf-8")
        filed = write_note.find_filed(self.vault, self.cfg)
        self.assertEqual(filed, {"plain-id": folder / "hand.md"})


class CliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.vault = self.tmp / "vault"
        self.vault.mkdir()
        self.config_path = self.tmp / "config.json"
        self.config_path.write_text("{}", encoding="utf-8")

    def run_cli(self, *args, stdin=None, env_extra=None):
        env = {k: v for k, v in os.environ.items() if k != "OBSIDIAN_VAULT"}
        if env_extra:
            env.update(env_extra)
        if isinstance(stdin, str):
            stdin = stdin.encode("utf-8")
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            input=stdin if stdin is not None else b"",
            capture_output=True, env=env, cwd=str(self.tmp), timeout=60,
        )
        return proc.returncode, proc.stdout.decode("utf-8"), proc.stderr.decode("utf-8", "replace")

    def base_args(self, *extra):
        return ["--config", str(self.config_path), "--vault", str(self.vault), *extra]

    def test_normal_run_prints_result_json_and_writes_note(self):
        code, out, err = self.run_cli(*self.base_args(), stdin=json.dumps(minimal(meeting_id="m1")))
        self.assertEqual(code, 0, err)
        result = json.loads(out)
        self.assertEqual(result["status"], "created")
        self.assertEqual(result["meeting_id"], "m1")
        self.assertTrue(Path(result["path"]).is_file())
        self.assertEqual(len(out.strip().splitlines()), 1)

        code, out, _ = self.run_cli(*self.base_args(), stdin=json.dumps(minimal(meeting_id="m1")))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["status"], "exists")

    def test_input_file_and_update_flag(self):
        src = self.tmp / "payload.json"
        src.write_text(json.dumps(minimal(meeting_id="m1")), encoding="utf-8")
        code, out, err = self.run_cli(*self.base_args("--input", str(src)))
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["status"], "created")

        src.write_text(json.dumps(minimal(meeting_id="m1", summary=["v2"])), encoding="utf-8")
        code, out, err = self.run_cli(*self.base_args("--input", str(src), "--update"))
        self.assertEqual(code, 0, err)
        result = json.loads(out)
        self.assertEqual(result["status"], "updated")
        self.assertIn("v2", read_text_exact(result["path"]))

    def test_dry_run_prints_markdown_and_writes_nothing(self):
        code, out, err = self.run_cli(*self.base_args("--dry-run"), stdin=json.dumps(minimal()))
        self.assertEqual(code, 0, err)
        self.assertTrue(out.startswith("---\n"))
        self.assertIn("# Standup", out)
        self.assertEqual(list(self.vault.rglob("*.md")), [])
        self.assertEqual(list(self.vault.iterdir()), [])

    def test_filed_lists_notes_and_since_filters(self):
        cfg = config()
        for mid, date in (("old", "2026-01-10"), ("mid", "2026-03-05"), ("new", "2026-06-25")):
            write_note.write(write_note.validate(minimal(meeting_id=mid, date=date)), cfg, self.vault)

        code, out, err = self.run_cli(*self.base_args("--filed"))
        self.assertEqual(code, 0, err)
        entries = json.loads(out)
        self.assertEqual([e["meeting_id"] for e in entries], ["old", "mid", "new"])
        self.assertEqual([e["date"] for e in entries], ["2026-01-10", "2026-03-05", "2026-06-25"])
        self.assertEqual([e["path"] for e in entries], sorted(e["path"] for e in entries))

        code, out, err = self.run_cli(*self.base_args("--filed", "--since", "2026-03-05"))
        self.assertEqual(code, 0, err)
        self.assertEqual([e["meeting_id"] for e in json.loads(out)], ["mid", "new"])

    def test_invalid_payload_gives_error_json_and_exit_2(self):
        code, out, err = self.run_cli(*self.base_args(), stdin=json.dumps({"date": "2026-06-25"}))
        self.assertEqual(code, 2)
        result = json.loads(out)
        self.assertEqual(result["status"], "error")
        self.assertIn("title", result["error"])
        self.assertNotIn("Traceback", err)
        self.assertEqual(list(self.vault.rglob("*.md")), [])

    def test_malformed_json_gives_error_json_and_exit_2(self):
        code, out, err = self.run_cli(*self.base_args(), stdin="{not json")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["status"], "error")
        self.assertNotIn("Traceback", err)

    def test_no_vault_configured_is_error(self):
        code, out, err = self.run_cli("--config", str(self.config_path), stdin=json.dumps(minimal()))
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["status"], "error")
        self.assertNotIn("Traceback", err)

    def test_nonexistent_vault_is_error(self):
        missing = self.tmp / "does-not-exist"
        code, out, err = self.run_cli("--config", str(self.config_path), "--vault", str(missing),
                                      stdin=json.dumps(minimal()))
        self.assertEqual(code, 2)
        result = json.loads(out)
        self.assertEqual(result["status"], "error")
        self.assertIn("Vault not found", result["error"])
        self.assertFalse(missing.exists())

    def test_obsidian_vault_env_is_used(self):
        code, out, err = self.run_cli("--config", str(self.config_path), stdin=json.dumps(minimal()),
                                      env_extra={"OBSIDIAN_VAULT": str(self.vault)})
        self.assertEqual(code, 0, err)
        path = Path(json.loads(out)["path"])
        self.assertTrue(path.is_file())
        self.assertIn(self.vault.resolve(), path.resolve().parents)

    def test_vault_flag_beats_env(self):
        other = self.tmp / "other"
        other.mkdir()
        code, out, err = self.run_cli(*self.base_args(), stdin=json.dumps(minimal()),
                                      env_extra={"OBSIDIAN_VAULT": str(other)})
        self.assertEqual(code, 0, err)
        self.assertIn(self.vault.resolve(), Path(json.loads(out)["path"]).resolve().parents)
        self.assertEqual(list(other.iterdir()), [])

    def test_vault_path_from_config(self):
        self.config_path.write_text(json.dumps({"vault_path": str(self.vault)}), encoding="utf-8")
        code, out, err = self.run_cli("--config", str(self.config_path), stdin=json.dumps(minimal()))
        self.assertEqual(code, 0, err)
        self.assertTrue(Path(json.loads(out)["path"]).is_file())

    def test_stdin_non_ascii_and_utf8_bom(self):
        payload = minimal(title="Café sync", attendees=["José Núñez"], meeting_id="u1")
        raw = b"\xef\xbb\xbf" + json.dumps(payload, ensure_ascii=False).encode("utf-8")
        code, out, err = self.run_cli(*self.base_args(), stdin=raw)
        self.assertEqual(code, 0, err)
        result = json.loads(out)
        self.assertEqual(result["status"], "created")
        self.assertIn("Café sync", Path(result["path"]).name)
        text = read_text_exact(result["path"])
        self.assertIn("[[José Núñez]]", text)
        self.assertIn("# Café sync", text)

    def test_dry_run_stdout_is_utf8_for_non_ascii(self):
        code, out, err = self.run_cli(*self.base_args("--dry-run"),
                                      stdin=json.dumps(minimal(organizer="José Núñez"),
                                                       ensure_ascii=False))
        self.assertEqual(code, 0, err)
        self.assertIn("José Núñez", out)


if __name__ == "__main__":
    unittest.main()
