# Meeting Notes Automation

Ask Claude to "file yesterday's meetings to Obsidian" and get structured markdown notes (summary, decisions, action items, attendees, company) in your vault. It is a Claude skill that reads your Teams meetings through the Microsoft 365 connector and writes each one with a small deterministic Python script.

It replaces the v1 Windows clipboard + hotkey macro and its regex parser. Nothing to copy, paste or trigger by hand.

## How It Works

1. You ask Claude (Cowork or Claude Code) to file one or more meetings.
2. Claude finds the meetings through the Microsoft 365 connector and skips any that are already filed.
3. Claude extracts the summary, decisions and action items from each meeting's Copilot recap (or the transcript if there is no recap).
4. `write_note.py` writes the note deterministically: fixed folder, filename and frontmatter, and de-duplication by meeting id, so re-runs never create duplicates.

## Requirements

- Python 3.10+ (standard library only, nothing to `pip install`)
- Claude with the Microsoft 365 connector enabled
- An Obsidian vault (a local folder)

## Setup: Claude Code

1. Copy `skills/meeting-to-obsidian/config.example.json` to `skills/meeting-to-obsidian/config.json` and edit it (see [Configuration](#configuration)).
2. Install the skill into `%USERPROFILE%\.claude\skills\`. A directory junction keeps it in sync with `git pull` and works without admin rights:

   ```bat
   mklink /J "%USERPROFILE%\.claude\skills\meeting-to-obsidian" "C:\path\to\meeting-notes-automation\skills\meeting-to-obsidian"
   ```

   Or simply copy the `meeting-to-obsidian` folder there. On macOS/Linux use `ln -s` to `~/.claude/skills/meeting-to-obsidian`.
3. Check that the Microsoft 365 connector is available in your session with `/mcp`.

## Setup: Cowork

1. Create `skills/meeting-to-obsidian/config.json` as above. `vault_path` doesn't matter in Cowork; the other keys do.
2. Package the skill:

   ```bash
   python scripts/package_skill.py
   ```

   This writes `dist/meeting-to-obsidian.zip` (your `config.json` is included if present).
3. In Claude, go to Settings → Capabilities → Skills and upload `dist/meeting-to-obsidian.zip`.
4. When you start a Cowork task, give it access to your vault folder. The skill finds the shared folder that contains `.obsidian/`.

## Usage

Example prompts:

- "File yesterday's meetings to Obsidian"
- "Save the Acme quarterly review to my vault"
- "File this week's customer meetings"
- "File this recap: `<paste>`"
- "Refresh the note for today's standup" (uses `--update`)

Claude finishes with a short list of each meeting and its outcome, with the note path:

| Outcome | Meaning |
|---|---|
| created | A new note was written. |
| already filed | A note with that meeting id exists; nothing was written. |
| skipped | The meeting has no recap or transcript, so there is nothing to file. |

Refreshing overwrites the existing note, including any edits you made to it, so Claude only does it when you ask.

## Automating It

Create a Cowork scheduled task, for example weekdays at end of day with the prompt "File today's meetings to Obsidian". It runs on your machine, so it can reach your local vault. Your computer must be awake and the Claude desktop app running.

Cloud-run routines can't see a local vault; they would need the vault synced to a git remote.

## Note Format

Notes are written to `<vault>/<meetings_subfolder>/<YYYY>/YYYY-MM-DD - Title.md`. A note with every field set:

```markdown
---
meeting_id: "AAMkAGI2TG93AAA="
date: 2026-06-25
time: "14:00-15:00"
organizer: "[[Tony Jiang]]"
company: "[[Acme Corp]]"
attendees:
  - "[[Tony Jiang]]"
  - "[[Alice Chen]]"
tags:
  - meeting
  - customer
source: "https://teams.microsoft.com/l/meetingrecap?x=1"
---

# Acme Corp Quarterly Review

**Date:** 2026-06-25 14:00-15:00
**Company:** [[Acme Corp]]
**Attendees:** [[Tony Jiang]], [[Alice Chen]]

## Summary
- Reviewed Q2 numbers.
- Discussed EU expansion.

## Decisions
- Proceed with EU pilot in Q4.

## Action Items
- [ ] Send updated pricing FAQ — [[Tony Jiang]] 📅 2026-06-27
- [ ] Schedule procurement follow-up — [[Bob Rivera]]
- [ ] Draft EU compliance one-pager

## Notes
Free-form markdown here.

[Open Teams recap](https://teams.microsoft.com/l/meetingrecap?x=1)
```

Optional lines and sections are omitted when empty. Action items use Obsidian Tasks-compatible syntax, so you can list every open item across all meetings with the Tasks plugin (put your own `meetings_subfolder` in the `path` line):

````markdown
```tasks
not done
path includes Customer Meetings
```
````

## Configuration

`config.json` lives in the skill folder (`skills/meeting-to-obsidian/config.json`). Missing keys fall back to the defaults.

| Key | Default | Description |
|---|---|---|
| `vault_path` | none | Absolute path to your Obsidian vault. |
| `meetings_subfolder` | `Meetings` | Folder inside the vault where notes go. |
| `default_tags` | `["meeting"]` | Tags added to every note, before any tags in the payload. |
| `link_people` | `true` | Write attendees, organizer and action-item owners as `[[wikilinks]]`. |
| `link_company` | `true` | Write the company as a `[[wikilink]]`. |

The vault is resolved in this order: `--vault`, then the `OBSIDIAN_VAULT` environment variable, then `vault_path` in `config.json`.

## Writer CLI Reference

Claude calls this for you, but you can use it without Claude by hand-writing a JSON payload (`title` and `date` are required; see `SKILL.md` for the full field list).

```bash
# Write a note from a JSON payload on stdin
python skills/meeting-to-obsidian/scripts/write_note.py

# Read the payload from a file instead of stdin
python skills/meeting-to-obsidian/scripts/write_note.py --input payload.json

# Print the rendered markdown without writing anything
python skills/meeting-to-obsidian/scripts/write_note.py --input payload.json --dry-run

# Overwrite an already-filed note (replaces any edits you made to it)
python skills/meeting-to-obsidian/scripts/write_note.py --input payload.json --update

# List filed meetings (JSON) with dates on or after the given day
python skills/meeting-to-obsidian/scripts/write_note.py --filed --since 2026-06-01
```

Other flags: `--vault PATH` and `--config PATH` (use a different config file). On Windows, use `py` if `python` isn't found.

A normal run prints one JSON line:

```json
{"status": "created", "path": "<vault>/Meetings/2026/2026-06-25 - Acme Corp Quarterly Review.md", "meeting_id": "AAMkAGI2TG93AAA="}
```

`status` is `created`, `exists` (already filed, nothing written) or `updated` (with `--update`). Errors print `{"status": "error", "error": "..."}` and exit with code 2.

## Testing

```bash
python -m unittest discover -s tests -v
```

## Repo Layout

```
meeting-notes-automation/
├── skills/
│   └── meeting-to-obsidian/
│       ├── SKILL.md               # The skill's workflow
│       ├── config.example.json    # Copy to config.json and edit
│       └── scripts/
│           └── write_note.py      # Deterministic note writer
├── scripts/
│   └── package_skill.py           # Builds dist/meeting-to-obsidian.zip
├── tests/
│   ├── test_write_note.py
│   └── fixtures/
├── routing-log.md                 # Planning and cost log
└── README.md
```

## Privacy

Notes are written only to your local vault, and the script makes no network calls. Meeting content passes through Claude and your Microsoft 365 connector under your organization's policies.

## Changelog

- **v2.0** (2026-10-02): Replaced the clipboard macro and regex parser with a Claude skill
  - Claude reads meetings through the Microsoft 365 connector and extracts summary, decisions and action items
  - Deterministic writer script: fixed folder, filename and frontmatter, de-duplicated by meeting id
  - Cowork packaging script and scheduled-task automation
- **v1.0** (2026-07-13): Initial release
  - Clipboard → Obsidian vault pipeline
  - Deterministic regex parser for Teams recaps
  - Windows hotkey support via `.lnk` shortcut
  - Regression test suite

## License

MIT License. See LICENSE for details (or add your preferred license).
