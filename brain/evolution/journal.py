"""Evolution journal (design 01 §4: docs/evolution/journal/).

Every change — promoted, proposed, rejected, rolled back — gets one
git-tracked markdown entry with structured YAML frontmatter, plus a line in
`INDEX.md`. The rollback command is a REQUIRED field for anything that
touched the tree, so `git revert` is always one copy-paste away (design 01 §4).

Journal entries are written by the controller; they are documentation of what
happened, not a promotion path — the classifier in `zones.py` decides that.
"""
from __future__ import annotations

import datetime as _dt
import re
import time as _time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

DECISIONS = frozenset({"promoted", "proposal", "rejected", "rolled_back", "no_change"})
MODES = frozenset({"off", "propose", "auto_safe"})

_FRONT = "---"


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "entry").lower()).strip("-")
    return s[:60] or "entry"


def rollback_command(commit: str) -> str:
    """The exact command recorded for a change that touched the tree."""
    return f"git revert --no-edit {commit}"


def make_entry(
    *,
    finding: str,
    zone: str,
    paths: Iterable[str],
    reason: str,
    tests: str,
    decision: str,
    mode: str = "propose",
    diff_commit: Optional[str] = None,
    diff: Optional[str] = None,
    baseline_compare: Optional[str] = None,
    rollback: Optional[str] = None,
    budget: Optional[Dict[str, Any]] = None,
    ts: Optional[int] = None,
) -> Dict[str, Any]:
    """Build one journal entry (design 01 §4 schema). Raises on bad enums —
    a journal entry with a decision outside the schema is a bug, not data."""
    if decision not in DECISIONS:
        raise ValueError(f"decision {decision!r} not in {sorted(DECISIONS)}")
    if mode not in MODES:
        raise ValueError(f"mode {mode!r} not in {sorted(MODES)}")
    paths = [str(p) for p in paths]
    if decision == "promoted" and not rollback:
        rollback = rollback_command(diff_commit or "UNKNOWN_COMMIT")
    ts_ms = int(ts or _time.time() * 1000)
    when = _dt.datetime.fromtimestamp(ts_ms / 1000)
    return {
        "id": f"evo_{when:%Y%m%d_%H%M%S}",
        "ts": ts_ms,
        "mode": mode,
        "finding": finding,
        "zone": zone,
        "paths": paths,
        "reason": reason,
        "tests": tests,
        "diff": diff,
        "diff_commit": diff_commit,
        "baseline_compare": baseline_compare,
        "decision": decision,
        "rollback": rollback,
        "budget": budget or {},
    }


def _frontmatter(entry: Dict[str, Any]) -> str:
    import yaml  # PyYAML is a hard repo dep (brain/config.py relies on it too)

    body = {k: entry[k] for k in sorted(entry) if k != "diff"}
    return yaml.safe_dump(body, sort_keys=True, allow_unicode=True).strip()


def write_entry(journal_dir: Path, entry: Dict[str, Any]) -> Path:
    """Write `<YYYY-MM-DD>-<slug>.md` + append to INDEX.md. Idempotent per id."""
    journal_dir = Path(journal_dir)
    journal_dir.mkdir(parents=True, exist_ok=True)
    day = _dt.datetime.fromtimestamp(entry["ts"] / 1000).strftime("%Y-%m-%d")
    name = f"{day}-{_slug(entry['finding'])}.md"
    path = journal_dir / name

    sections = [
        f"{_FRONT}",
        _frontmatter(entry),
        f"{_FRONT}",
        "",
        f"# {entry['finding']}",
        "",
        f"- **zone:** {entry['zone']}  **mode:** {entry['mode']}  **decision:** {entry['decision']}",
        f"- **paths:** {', '.join(entry['paths']) or '(none)'}",
        f"- **baseline compare:** {entry.get('baseline_compare') or '(n/a)'}",
        f"- **budget:** {entry.get('budget') or '{}'}",
        "",
        "## Reason",
        "",
        entry["reason"],
        "",
        "## Tests (real output only)",
        "",
        "```",
        entry["tests"].rstrip(),
        "```",
        "",
        "## Rollback",
        "",
        f"`{entry.get('rollback') or '(no tree change — nothing to roll back)'}`",
    ]
    if entry.get("diff"):
        sections += ["", "## Diff", "", "```diff", entry["diff"].rstrip(), "```"]
    path.write_text("\n".join(sections) + "\n", encoding="utf-8")

    index = journal_dir / "INDEX.md"
    line = f"- {day} | {entry['decision']} | {entry['zone']} | {entry['finding']} | `{name}`"
    if not index.exists():
        index.write_text("# Evolution journal index\n\n" + line + "\n", encoding="utf-8")
    elif line not in index.read_text(encoding="utf-8"):
        with index.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    return path


def load_entry(path: Path) -> Dict[str, Any]:
    """Parse a journal entry back (frontmatter only — body is for humans)."""
    import yaml

    text = Path(path).read_text(encoding="utf-8")
    if not text.startswith(_FRONT):
        raise ValueError(f"{path}: missing YAML frontmatter")
    fm_text = text[len(_FRONT) + 1:].split("\n" + _FRONT, 1)[0]
    data = yaml.safe_load(fm_text)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: frontmatter is not a mapping")
    return data


def iter_entries(journal_dir: Path) -> List[Dict[str, Any]]:
    journal_dir = Path(journal_dir)
    if not journal_dir.is_dir():
        return []
    out = []
    for p in sorted(journal_dir.glob("*.md")):
        if p.name == "INDEX.md":
            continue
        out.append(load_entry(p))
    return out


def weekly_summary(journal_dir: Path, days: int = 7) -> str:
    """Spoken weekly summary (design 01 §4): short, per item ≤2 sentences
    (voice_personality.spoken_reply_max_sentences), long detail stays on screen."""
    cutoff = _time.time() * 1000 - days * 86400 * 1000
    recent = [e for e in iter_entries(journal_dir) if e.get("ts", 0) >= cutoff]
    if not recent:
        return "No evolution changes in the last week."
    counts: Dict[str, int] = {}
    for e in recent:
        counts[e["decision"]] = counts.get(e["decision"], 0) + 1
    parts = [f"{v} {k}" for k, v in sorted(counts.items())]
    pending = [e for e in recent if e["decision"] == "proposal"]
    tail = ""
    if pending:
        tail = (f" {len(pending)} proposal{'s' if len(pending) > 1 else ''} "
                f"await{'s' if len(pending) == 1 else ''} your approval.")
    return f"{len(recent)} journal entries this week: {', '.join(parts)}.{tail}"
