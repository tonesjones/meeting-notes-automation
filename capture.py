"""Capture a Teams Copilot meeting recap from the clipboard into an Obsidian vault.

Trigger via a Windows shortcut hotkey after copying the recap (Ctrl+A, Ctrl+C
inside the Teams recap pane). Writes a markdown file under
<vault>/<meetings_subfolder>/<year>/.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


CONFIG_PATH = Path(__file__).with_name("config.json")

ATTENDEES_HEADING = re.compile(r"^\s*(attendees|participants)\s*:?\s*$", re.I)
SUMMARY_HEADING = re.compile(
    r"^\s*(summary|recap|notes|key\s*points|meeting\s*notes|overview)\s*:?\s*$", re.I
)
ACTIONS_HEADING = re.compile(
    r"^\s*(action\s*items|follow[-\s]?ups?|next\s*steps|tasks|follow[-\s]?up\s*tasks)\s*:?\s*$", re.I
)
ANY_HEADING = re.compile(r"^.+:\s*$")
GENERIC_SECTION = re.compile(
    r"^\s*(attendees|participants|summary|recap|notes|key\s*points|meeting\s*notes|overview|"
    r"action\s*items|follow[-\s]?ups?|next\s*steps|tasks|follow[-\s]?up\s+tasks|transcript|chapters)\s*:?\s*$",
    re.I,
)

DATE_PATTERNS = [
    re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"),
    re.compile(
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b",
        re.I,
    ),
    re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"),
]
TIME_PATTERN = re.compile(r"\b(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)\b")

ILLEGAL_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass
class Recap:
    title: str = "Untitled Meeting"
    date: str = ""
    time: str = ""
    attendees: list[str] = field(default_factory=list)
    summary: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    raw: str = ""


def load_config() -> dict:
    with CONFIG_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def read_clipboard() -> str:
    try:
        import pyperclip
    except ImportError as e:
        raise SystemExit("pyperclip not installed — run: pip install -r requirements.txt") from e
    text = pyperclip.paste()
    if not text or not text.strip():
        raise SystemExit("Clipboard is empty. Copy the Teams recap first.")
    return text


def _strip_bullet(line: str) -> str:
    return re.sub(r"^\s*[-*•·]\s*", "", line).strip()


def _split_attendees(line: str) -> list[str]:
    parts = re.split(r"[,;]|\band\b", line, flags=re.I)
    return [p.strip() for p in parts if p.strip()]


def parse_recap(text: str) -> Recap:
    """Parse Teams Copilot recap text into structured fields.

    Strategy: scan for lines ending in ':' (section headers). Collect content into
    the appropriate bucket (attendees/summary/actions) until the next header or EOF.
    Gracefully skip unknown sections.
    """
    recap = Recap(raw=text)
    lines = [ln.rstrip() for ln in text.splitlines()]

    # Title: look for "Meeting notes:" followed by first actual heading, or use first heading if no "Meeting notes".
    meeting_notes_idx = None
    for i, ln in enumerate(lines):
        if re.match(r"^\s*meeting\s+notes\s*:?\s*$", ln.strip(), re.I):
            meeting_notes_idx = i
            break
    if meeting_notes_idx is not None:
        for ln in lines[meeting_notes_idx + 1 :]:
            s = ln.strip()
            if s and ANY_HEADING.match(s) and not re.search(r"^(Generated|Be\s)", s):
                recap.title = s.rstrip(":").strip()
                break
    if not recap.title or recap.title.startswith("Generated"):
        for ln in lines:
            s = ln.strip()
            if s and ANY_HEADING.match(s) and not re.search(r"^(Generated|Meeting\s)", s):
                recap.title = s.rstrip(":").strip()
                break

    # Date / time: scan first ~20 lines.
    head_blob = "\n".join(lines[:20])
    for pat in DATE_PATTERNS:
        m = pat.search(head_blob)
        if m:
            recap.date = _normalize_date(m.group(0))
            break
    if not recap.date:
        recap.date = datetime.now().strftime("%Y-%m-%d")
    tm = TIME_PATTERN.search(head_blob)
    if tm:
        recap.time = tm.group(1).strip()

    # Section walk: any line ending in ':' is a section header.
    section: str | None = None
    buf: list[str] = []

    def flush():
        nonlocal buf
        if section == "attendees":
            joined = " ".join(buf).strip()
            if joined:
                recap.attendees = _split_attendees(joined)
        elif section == "summary":
            items = [_strip_bullet(b) for b in buf if b.strip()]
            recap.summary.extend(items)
        elif section == "actions":
            if in_action_block:
                joined = " ".join(b.strip() for b in buf if b.strip())
                if joined:
                    recap.actions.append(joined)
            else:
                items = [_strip_bullet(b) for b in buf if b.strip()]
                recap.actions.extend(items)
        buf = []

    def classify_section(header: str) -> str | None:
        if ATTENDEES_HEADING.match(header):
            return "attendees"
        if ACTIONS_HEADING.match(header):
            return "actions"
        if re.search(r"(transcript|chapters|generated by ai)", header, re.I):
            return None
        # Default: treat any heading as summary unless it's explicitly something else.
        if ":" in header or SUMMARY_HEADING.match(header):
            return "summary"
        return None

    in_action_block = False
    for i, ln in enumerate(lines):
        s = ln.strip()
        indent = len(ln) - len(ln.lstrip())

        if ACTIONS_HEADING.match(s):
            flush()
            section = "actions"
            in_action_block = True
            continue

        # Inside an action block, treat lines ending with ':' as action titles.
        if in_action_block and ANY_HEADING.match(s):
            flush()
            action_title = s.rstrip(":").strip()
            if action_title:
                buf = [action_title]
            continue

        # Main section heading (no indent). Skip indented subsection headers.
        if not in_action_block and ANY_HEADING.match(s) and indent == 0:
            flush()
            section = classify_section(s)
            continue

        if section is not None:
            buf.append(ln)
    flush()

    # Note: attendee extraction is best-effort and often unreliable without explicit "Attendees:" header.
    # Skipping automatic extraction to avoid noise.

    return recap


def _normalize_date(raw: str) -> str:
    raw = raw.strip().rstrip(",")
    fmts = ["%Y-%m-%d", "%B %d %Y", "%B %d, %Y", "%b %d %Y", "%b %d, %Y",
            "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y"]
    for f in fmts:
        try:
            return datetime.strptime(raw, f).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return raw


def render_markdown(recap: Recap, tags: list[str]) -> str:
    attendees_yaml = "[" + ", ".join(recap.attendees) + "]" if recap.attendees else "[]"
    tags_yaml = "[" + ", ".join(tags) + "]"
    parts = [
        "---",
        f"date: {recap.date}",
    ]
    if recap.time:
        parts.append(f"time: {recap.time}")
    parts.extend([
        f"attendees: {attendees_yaml}",
        f"tags: {tags_yaml}",
        "---",
        "",
        f"# {recap.title}",
        "",
    ])
    meta = f"**Date:** {recap.date}"
    if recap.time:
        meta += f" {recap.time}"
    parts.append(meta)
    if recap.attendees:
        parts.append(f"**Attendees:** {', '.join(recap.attendees)}")
    parts.append("")
    parts.append("## Summary")
    if recap.summary:
        parts.extend(f"- {s}" for s in recap.summary)
    else:
        parts.append("_No summary captured — see raw recap below._")
    parts.append("")
    parts.append("## Action Items")
    if recap.actions:
        parts.extend(f"- [ ] {a}" for a in recap.actions)
    else:
        parts.append("_None._")
    parts.append("")
    return "\n".join(parts)


def safe_filename(recap: Recap) -> str:
    name = f"{recap.date} - {recap.title}"
    name = ILLEGAL_FILENAME.sub("-", name).strip().rstrip(".")
    return name[:180] + ".md"


def write_note(recap: Recap, config: dict) -> Path:
    vault = Path(config["vault_path"]).expanduser()
    folder = vault / config.get("meetings_subfolder", "Customer Meetings") / recap.date[:4]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / safe_filename(recap)
    # Avoid clobbering an existing note from the same day with same title.
    if path.exists():
        stem, suffix = path.stem, path.suffix
        i = 2
        while (folder / f"{stem} ({i}){suffix}").exists():
            i += 1
        path = folder / f"{stem} ({i}){suffix}"
    body = render_markdown(recap, config.get("default_tags", ["meeting"]))
    path.write_text(body, encoding="utf-8")
    return path


def notify(message: str) -> None:
    print(message)
    try:
        from win10toast import ToastNotifier
        ToastNotifier().show_toast("Meeting captured", message, duration=4, threaded=True)
    except Exception:
        pass


def main() -> int:
    try:
        config = load_config()
        text = read_clipboard()
        recap = parse_recap(text)
        path = write_note(recap, config)
        notify(f"Saved: {path}")
        return 0
    except SystemExit as e:
        notify(str(e))
        return 1
    except Exception as e:
        notify(f"Error: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
