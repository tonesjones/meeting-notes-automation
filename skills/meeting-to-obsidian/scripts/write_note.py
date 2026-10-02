#!/usr/bin/env python3
"""Write one Teams meeting note into an Obsidian vault.

Claude extracts a meeting through the M365 connector, builds a JSON payload and
pipes it to this script, which renders a markdown note deterministically.

Usage:
    python write_note.py [--input FILE] [--vault PATH] [--config PATH] [--update] [--dry-run]
    python write_note.py --filed [--since YYYY-MM-DD] [--vault PATH] [--config PATH]

Payload comes from --input or stdin. The vault is resolved from --vault, then
$OBSIDIAN_VAULT, then config "vault_path". Results are printed as JSON on
stdout; errors are {"status": "error", ...} with exit code 2.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

DEFAULT_CONFIG = {
    "vault_path": None,
    "meetings_subfolder": "Meetings",
    "default_tags": ["meeting"],
    "link_people": True,
    "link_company": True,
}

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HHMM = re.compile(r"^\d{2}:\d{2}$")


class PayloadError(ValueError):
    """Invalid payload or config."""


# ---------------------------------------------------------------- config / validation

def load_config(path: Path | None) -> dict:
    config = copy.deepcopy(DEFAULT_CONFIG)
    if path is None:
        return config
    path = Path(path)
    if not path.exists():
        raise PayloadError(f"Config not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise PayloadError(f"Cannot read config {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PayloadError(f"Config {path} must be a JSON object")
    config.update(data)
    return config


def _opt_str(payload: dict, field: str) -> str:
    value = payload.get(field)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise PayloadError(f"{field} must be a string")
    return value.strip()


def _str_list(payload: dict, field: str) -> list[str]:
    value = payload.get(field)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise PayloadError(f"{field} must be a list of strings")
    return [v.strip() for v in value if v.strip()]


def _dedup(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _action_items(payload: dict) -> list[dict]:
    value = payload.get("action_items")
    if value is None:
        return []
    if not isinstance(value, list):
        raise PayloadError("action_items must be a list of objects")
    items = []
    for i, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise PayloadError(f"action_items[{i}] must be an object")
        item = {key: _opt_str(raw, key) for key in ("task", "owner", "due")}
        if not item["task"]:
            raise PayloadError(f"action_items[{i}].task is required and must be a non-empty string")
        items.append(item)
    return items


def validate(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise PayloadError("payload must be a JSON object")
    out: dict = {}
    out["title"] = " ".join(_opt_str(payload, "title").split())  # one line: it's a heading and a filename
    if not out["title"]:
        raise PayloadError("title is required and must be a non-empty string")
    out["date"] = _opt_str(payload, "date")
    try:
        if not ISO_DATE.match(out["date"]):
            raise ValueError
        dt.datetime.strptime(out["date"], "%Y-%m-%d")
    except ValueError:
        raise PayloadError("date is required and must be a real date in YYYY-MM-DD format") from None
    for field in ("start_time", "end_time"):
        out[field] = _opt_str(payload, field)
        if out[field] and not HHMM.match(out[field]):
            raise PayloadError(f"{field} must be in HH:MM format")
    for field in ("organizer", "company", "notes", "source_url"):
        out[field] = _opt_str(payload, field)
    out["attendees"] = _dedup(_str_list(payload, "attendees"))
    out["tags"] = _dedup(_str_list(payload, "tags"))
    out["summary"] = _str_list(payload, "summary")
    out["decisions"] = _str_list(payload, "decisions")
    out["action_items"] = _action_items(payload)
    out["meeting_id"] = _opt_str(payload, "meeting_id")
    out["meeting_id"] = meeting_id_for(out)
    return out


def meeting_id_for(payload: dict) -> str:
    explicit = payload.get("meeting_id")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    return f"{payload['date']}|{payload['title'].strip().lower()}"


# ---------------------------------------------------------------- rendering

def sanitize_tag(tag: str) -> str:
    return re.sub(r"\s+", "-", tag.strip().lstrip("#").strip())


def _tags(payload: dict, config: dict) -> list[str]:
    raw = list(config.get("default_tags") or []) + list(payload.get("tags") or [])
    return _dedup([t for t in (sanitize_tag(str(t)) for t in raw) if t])


def _link(name: str, enabled: bool) -> str:
    if not enabled:
        return name
    safe = re.sub(r"\s+", " ", re.sub(r"[\[\]|#^]", "", name)).strip()
    return f"[[{safe}]]" if safe else name


def _yaml(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _time_range(payload: dict) -> str:
    start, end = payload.get("start_time"), payload.get("end_time")
    if not start:
        return ""
    return f"{start}-{end}" if end else start


def _frontmatter(payload: dict, config: dict, people: bool, company: bool) -> list[str]:
    time_range = _time_range(payload)
    lines = ["---", f"meeting_id: {_yaml(meeting_id_for(payload))}", f"date: {payload['date']}"]
    if time_range:
        lines.append(f"time: {_yaml(time_range)}")
    if payload.get("organizer"):
        lines.append(f"organizer: {_yaml(_link(payload['organizer'], people))}")
    if payload.get("company"):
        lines.append(f"company: {_yaml(_link(payload['company'], company))}")
    if payload.get("attendees"):
        lines.append("attendees:")
        lines += [f"  - {_yaml(_link(a, people))}" for a in payload["attendees"]]
    tags = _tags(payload, config)
    if tags:
        lines.append("tags:")
        lines += [f"  - {t}" for t in tags]
    else:
        lines.append("tags: []")
    if payload.get("source_url"):
        lines.append(f"source: {_yaml(payload['source_url'])}")
    lines.append("---")
    return lines


def _action_line(item: dict, people: bool) -> str:
    line = f"- [ ] {item['task']}"
    if item.get("owner"):
        line += f" — {_link(item['owner'], people)}"
    due = item.get("due") or ""
    if ISO_DATE.match(due):
        line += f" \U0001F4C5 {due}"
    elif due:
        line += f" (due {due})"
    return line


def render_note(payload: dict, config: dict) -> str:
    people = bool(config.get("link_people", True))
    company = bool(config.get("link_company", True))
    time_range = _time_range(payload)

    header = [f"# {payload['title']}", "",
              f"**Date:** {payload['date']}" + (f" {time_range}" if time_range else "")]
    if payload.get("company"):
        header.append(f"**Company:** {_link(payload['company'], company)}")
    if payload.get("attendees"):
        header.append("**Attendees:** " + ", ".join(_link(a, people) for a in payload["attendees"]))

    summary = [f"- {s}" for s in payload.get("summary") or []] or ["_No summary captured._"]
    sections = [_frontmatter(payload, config, people, company), header,
                ["## Summary"] + summary]
    if payload.get("decisions"):
        sections.append(["## Decisions"] + [f"- {d}" for d in payload["decisions"]])
    actions = [_action_line(i, people) for i in payload.get("action_items") or []] or ["_None._"]
    sections.append(["## Action Items"] + actions)
    notes = (payload.get("notes") or "").rstrip()
    if notes.strip():
        sections.append(["## Notes", notes])
    if payload.get("source_url"):
        sections.append([f"[Open Teams recap]({payload['source_url']})"])
    return "\n\n".join("\n".join(s) for s in sections) + "\n"


# ---------------------------------------------------------------- vault / filing

def _filename(payload: dict) -> str:
    name = f"{payload['date']} - {payload['title']}"
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", name)
    name = re.sub(r"\s+", " ", name).strip().rstrip(". ")
    return name[:150].rstrip(". ") + ".md"  # Windows rejects trailing dots/spaces


def _meetings_dir(vault: Path, config: dict) -> Path:
    return vault / config.get("meetings_subfolder", "Meetings")


def note_path(payload: dict, config: dict, vault: Path) -> Path:
    return _meetings_dir(vault, config) / payload["date"][:4] / _filename(payload)


def _parse_value(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith('"'):
        try:
            return json.loads(raw)
        except ValueError:
            pass
    return raw


def _read_frontmatter(path: Path) -> dict[str, str]:
    """Return the meeting_id and date values from a note's frontmatter."""
    found: dict[str, str] = {}
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    if not lines or lines[0].strip() != "---":
        return found
    for line in lines[1:]:
        if line.strip() == "---":
            break
        for key in ("meeting_id", "date"):
            if line.startswith(f"{key}:"):
                found[key] = _parse_value(line[len(key) + 1:])
    return found


def _scan(vault: Path, config: dict) -> list[tuple[str, str, Path]]:
    """All filed notes as (meeting_id, date, path), sorted by path."""
    root = _meetings_dir(vault, config)
    if not root.is_dir():
        return []
    entries = []
    for path in sorted(root.rglob("*.md")):
        try:
            meta = _read_frontmatter(path)
        except (OSError, UnicodeDecodeError):
            continue
        if meta.get("meeting_id"):
            entries.append((meta["meeting_id"], meta.get("date", ""), path))
    return entries


def find_filed(vault: Path, config: dict) -> dict[str, Path]:
    filed: dict[str, Path] = {}
    for meeting_id, _date, path in _scan(vault, config):
        filed.setdefault(meeting_id, path)
    return filed


def _free_path(path: Path) -> Path:
    candidate, n = path, 2
    while candidate.exists():
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        n += 1
    return candidate


def write(payload: dict, config: dict, vault: Path, update: bool = False) -> dict:
    meeting_id = meeting_id_for(payload)
    existing = find_filed(vault, config).get(meeting_id)
    if existing is not None and not update:
        return {"status": "exists", "path": str(existing), "meeting_id": meeting_id}
    if existing is not None:
        target, status = existing, "updated"
    else:
        target, status = _free_path(note_path(payload, config, vault)), "created"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_note(payload, config), encoding="utf-8", newline="\n")
    return {"status": status, "path": str(target), "meeting_id": meeting_id}


# ---------------------------------------------------------------- CLI

def _read_payload(input_file: str | None) -> dict:
    raw = Path(input_file).read_bytes() if input_file else sys.stdin.buffer.read()
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise PayloadError(f"Invalid JSON payload: {exc}") from exc


def _resolve_vault(arg: str | None, config: dict) -> Path:
    chosen = arg or os.environ.get("OBSIDIAN_VAULT") or config.get("vault_path")
    if not chosen:
        raise PayloadError("No vault configured: use --vault, $OBSIDIAN_VAULT or config vault_path")
    vault = Path(chosen).expanduser()
    if not vault.is_dir():
        raise PayloadError(f"Vault not found: {vault}")
    return vault


def _load_config_for_cli(arg: str | None) -> dict:
    if arg:
        return load_config(Path(arg))
    default = Path(__file__).resolve().parent.parent / "config.json"
    return load_config(default if default.exists() else None)


def _list_filed(vault: Path, config: dict, since: str | None) -> list[dict]:
    if since:
        try:
            dt.datetime.strptime(since, "%Y-%m-%d")
        except ValueError:
            raise PayloadError("--since must be a real date in YYYY-MM-DD format") from None
    return [{"meeting_id": mid, "date": date, "path": str(path)}
            for mid, date, path in _scan(vault, config)
            if not since or (date and date >= since)]


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Write a meeting note into an Obsidian vault.")
    p.add_argument("--input", help="payload JSON file (default: stdin)")
    p.add_argument("--vault", help="vault directory")
    p.add_argument("--config", help="config JSON file")
    p.add_argument("--update", action="store_true", help="overwrite an already-filed meeting")
    p.add_argument("--dry-run", action="store_true", help="print the note, write nothing")
    p.add_argument("--filed", action="store_true", help="list filed meetings as JSON")
    p.add_argument("--since", help="with --filed: only meetings on/after YYYY-MM-DD")
    return p


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = _build_parser().parse_args(argv)
    try:
        config = _load_config_for_cli(args.config)
        if args.filed:
            vault = _resolve_vault(args.vault, config)
            print(json.dumps(_list_filed(vault, config, args.since), ensure_ascii=False))
            return 0
        payload = validate(_read_payload(args.input))
        if args.dry_run:  # no vault needed: nothing is written
            sys.stdout.write(render_note(payload, config))
            return 0
        vault = _resolve_vault(args.vault, config)
        print(json.dumps(write(payload, config, vault, update=args.update), ensure_ascii=False))
        return 0
    except (PayloadError, OSError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
