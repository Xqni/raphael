"""Baseline capture + comparison (design 01 §2.5: compare before any promote).

A baseline is the last-known-good snapshot: commit, `last-known-good` tag,
core-guard status, shadow test result, and optional golden transcripts.
`compare()` is pure and fail-closed: any regression it can see (more failures,
a core-guard flip, transcript drift) ⇒ verdict `fail` ⇒ no promote.

Storage: `brain/evolution/golden/baseline.json` (lane-owned, git-tracked) —
golden transcripts live beside it as `<name>.json`.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from brain.evolution import rollback as R

REPO_ROOT = R.REPO_ROOT
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
BASELINE_FILE = GOLDEN_DIR / "baseline.json"


# ---- capture ---------------------------------------------------------------
def _git_head(repo: Path) -> Optional[str]:
    try:
        return R._git(Path(repo), "rev-parse", "HEAD") or None
    except Exception:  # noqa: BLE001
        return None


def capture(repo: Path, shadow_result: Dict[str, Any],
            transcripts: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Snapshot everything the promote gate compares against."""
    repo = Path(repo)
    guard_ok, guard_msg = R.verify_core_guard(repo)
    return {
        "commit": _git_head(repo),
        "last_known_good": R.last_known_good(repo),
        "core_guard": {"ok": guard_ok, "msg": guard_msg},
        "shadow": {
            "ok": bool(shadow_result.get("ok")),
            "rc": shadow_result.get("rc"),
            "command": shadow_result.get("command"),
            # keep output tail only — baselines stay small and secret-free
            "output_tail": (shadow_result.get("output") or "")[-2000:],
        },
        "transcripts": list(transcripts or []),
    }


def save(baseline: Dict[str, Any], path: Path = BASELINE_FILE) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    return path


def load(path: Path = BASELINE_FILE) -> Optional[Dict[str, Any]]:
    path = Path(path)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# ---- compare ---------------------------------------------------------------
def _key(step: Dict[str, Any]) -> str:
    """Identity of a transcript step: type + name (+ target when present)."""
    return f"{step.get('type', '?')}:{step.get('name', '?')}:{step.get('target', '')}"


def compare_transcripts(expected: List[Dict[str, Any]],
                        actual: List[Dict[str, Any]]) -> List[str]:
    """Structured delta of two golden action streams. Empty list = identical.
    Order-sensitive on purpose: an act_req stream that reorders IS a behavior
    change (design 01 §2.5 — unintended delta ⇒ fail)."""
    diffs: List[str] = []
    exp_keys = [_key(s) for s in expected]
    act_keys = [_key(s) for s in actual]
    for i, (e, a) in enumerate(zip(exp_keys, act_keys)):
        if e != a:
            diffs.append(f"step[{i}] changed: {e!r} -> {a!r}")
    if len(exp_keys) != len(act_keys):
        longer, name = (exp_keys, "baseline") if len(exp_keys) > len(act_keys) else (act_keys, "candidate")
        for extra in longer[min(len(exp_keys), len(act_keys)):]:
            diffs.append(f"{name} has extra step: {extra!r}")
    return diffs


def compare(current: Dict[str, Any],
            baseline: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Verdict + deltas for the promote gate. Fail-closed: no baseline, a
    core-guard flip, or a shadow failure ⇒ ok=False."""
    deltas: List[str] = []
    if baseline is None:
        return {"ok": False, "deltas": ["no baseline captured"]}
    if not current.get("core_guard", {}).get("ok"):
        deltas.append("core guard NOT ok in candidate")
    if not baseline.get("core_guard", {}).get("ok"):
        deltas.append("core guard was NOT ok in baseline (bad baseline)")
    if not current.get("shadow", {}).get("ok"):
        deltas.append(f"shadow run failed (rc={current.get('shadow', {}).get('rc')})")
    if current.get("commit") and baseline.get("commit") and \
            current["commit"] != baseline["commit"]:
        deltas.append(f"commit moved: {baseline['commit'][:10]} -> {current['commit'][:10]}")
    for t_cur, t_base in zip(current.get("transcripts", []),
                             baseline.get("transcripts", [])):
        if t_cur.get("name") != t_base.get("name"):
            deltas.append(f"transcript set changed: {t_base.get('name')} -> {t_cur.get('name')}")
            continue
        for d in compare_transcripts(t_base.get("steps", []), t_cur.get("steps", [])):
            deltas.append(f"{t_cur.get('name')}: {d}")
    n_cur, n_base = len(current.get("transcripts", [])), len(baseline.get("transcripts", []))
    if n_cur != n_base:
        deltas.append(f"transcript count {n_base} -> {n_cur}")
    # a commit moving is EXPECTED for a candidate patch — it alone is not a failure;
    # the failure signals above are. Recompute the verdict explicitly:
    hard = [d for d in deltas if not d.startswith("commit moved")]
    return {"ok": not hard, "deltas": deltas}
