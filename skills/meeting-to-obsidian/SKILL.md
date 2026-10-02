---
name: meeting-to-obsidian
description: File Microsoft Teams meetings into the user's Obsidian vault as structured markdown notes (summary, decisions, action items, attendees, company). Use when the user asks to save, file, log, capture or sync a meeting, a meeting recap, or a day's/week's meetings into Obsidian or their vault, or pastes a Teams/Copilot recap and wants it filed.
---

# Meeting → Obsidian

Pull meetings from the Microsoft 365 connector, turn each one into a JSON payload, and hand it to
`scripts/write_note.py`, which writes the note. The script owns the file name, folder, frontmatter and
de-duplication. Your job is choosing the meetings and extracting good content.

## 1. Locate the vault

The script resolves the vault from `--vault`, then the `OBSIDIAN_VAULT` env var, then `vault_path` in
`config.json` (next to this file). Folder, default tags and wikilink settings also live in `config.json`.

- **Claude Code**: usually `config.json` already has the vault. Run the script without `--vault`.
- **Cowork**: the Windows path in `config.json` doesn't exist inside the sandbox. The vault must be a folder
  the user has shared with this session. Find the shared folder containing a `.obsidian/` directory and
  pass its path with `--vault`. If no such folder is shared, ask the user to share their vault folder.
  Don't guess.

If the script returns `Vault not found`, stop and ask. Don't create a vault.

## 2. Decide which meetings

- A specific meeting ("file the Acme call"): find that one.
- A time range ("file today's / yesterday's / this week's meetings"): list calendar events in the range
  that were Teams meetings and that the user attended. Skip declined, cancelled, and all-day events, and
  focus-time or personal blocks.
- Before fetching content for a range, check what's already filed:
  `python <skill-dir>/scripts/write_note.py --filed --since YYYY-MM-DD [--vault ...]`
  Skip meetings whose `meeting_id` is already in that list (unless the user asked to refresh them).

## 3. Get the content

Use the Microsoft 365 connector to fetch the meeting's Copilot / intelligent recap or AI notes. Fall back
to the transcript only if there's no recap. If neither exists (no recording or transcription),
don't invent a summary. Report the meeting as skipped, or file it with only the metadata if the user wants
a stub.

If the user pastes recap text instead, use it as the content source. Still try the connector for the
meeting id and attendees, and if that fails, leave `meeting_id` out.

## 4. Build the payload

```json
{
  "meeting_id": "<M365 event or online-meeting id>",
  "title": "Acme Corp Quarterly Review",
  "date": "2026-06-25",
  "start_time": "14:00",
  "end_time": "15:00",
  "organizer": "Tony Jiang",
  "company": "Acme Corp",
  "attendees": ["Tony Jiang", "Alice Chen"],
  "tags": ["customer"],
  "summary": ["Reviewed Q2 numbers; Acme up 12% on renewal-weighted ARR."],
  "decisions": ["Proceed with EU pilot in Q4."],
  "action_items": [{"task": "Send updated pricing FAQ", "owner": "Tony Jiang", "due": "2026-06-27"}],
  "notes": "",
  "source_url": "<link to the recap in Teams, if available>"
}
```

Required: `title` and `date`. Always include `meeting_id` when the connector gives you one. It's what keeps
re-runs from creating duplicate notes. Extraction guidance:

- **Dates and times** are in the user's local time zone, not UTC. `date` is `YYYY-MM-DD`, times are 24h `HH:MM`.
- **title**: the calendar subject, cleaned up. Drop prefixes like "FW:", "[External]" and Teams boilerplate.
- **attendees**: people who actually joined, if the recap says so, otherwise the invitees who accepted.
  Use display names ("First Last"), not emails. Leave out rooms and distribution lists.
- **company**: the external organization for customer or partner meetings, inferred from the subject or
  attendee email domains. Leave it out for internal meetings. Use the same spelling every time (it becomes a link).
- **tags**: add `customer` for meetings with an external company and `internal` otherwise. Add more only if
  the user's existing notes use them.
- **summary**: 3–8 concise bullets of what was discussed and learned. Facts, numbers and concerns, not narration.
- **decisions**: only things explicitly agreed. Omit the field if there are none.
- **action_items**: one per task, phrased as a verb-first task. `owner` is a display name. Set `due` as
  `YYYY-MM-DD` only when a date was stated or is unambiguous ("by Friday" relative to the meeting date).
  Otherwise leave it out.
- **notes**: optional. Use it for anything worth keeping that doesn't fit above (open questions, risks).
  Never paste the transcript.

Don't fabricate. If the recap doesn't say something, leave that field out.

## 5. Write

Write the payload to a temp file and pass it with `--input` (more reliable than piping, especially on Windows):

```
python <skill-dir>/scripts/write_note.py --input <payload.json> [--vault <vault>]
```

On Windows, if `python` isn't found, try `py`. The script prints one JSON line:

- `created`: new note at `path`.
- `exists`: already filed. Nothing was written. Re-run with `--update` only if the user asked to refresh it,
  because `--update` overwrites any edits they made to that note.
- `updated`: only with `--update`; the existing note was overwritten in place.
- `error`: fix the payload per the message and retry. If it's a vault problem (`Vault not found`,
  `No vault configured`), go back to step 1 and don't retry blindly.

Use `--dry-run` to preview the markdown without writing anything.

## 6. Report

Finish with a short list: each meeting and its outcome (created / already filed / skipped and why), with the
note path. If several action items are owned by the user, list them so they can see their to-dos at a glance.
