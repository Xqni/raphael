"""Evolution controller — the end-to-end cycle (design 01 §2), propose-first.

Ties together what already exists:
  guard verify (rollback.py) -> zone classification (zones.py) -> mode gate
  -> isolated git worktree branch -> shadow verification (shadow.py)
  -> baseline compare (baseline.py) -> journal + PROPOSAL file (journal.py)
  -> probation window (persona.probation — dry-run only until approved).

Hard gates (design 01 §6): fail-closed guard; `mode=off` skips everything;
`mode=propose` NEVER merges/promotes — it only writes a proposal + journal
entry; `mode=auto_safe` may auto-promote MUTABLE-zone changes only (and that
path is not exercised by the first run). Nothing here edits the working tree:
patches are applied inside a throwaway worktree branch and removed after.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List

from brain.evolution import baseline as B
from brain.evolution import journal as J
from brain.evolution import rollback as R
from brain.evolution import shadow as S
from brain.evolution import zones as Z

REPO_ROOT = Path(__file__).resolve().parents[2]
PROPOSAL_DIR = REPO_ROOT / "docs" / "evolution" / "proposals"


def decide(mode: str, zone: Z.Zone) -> str:
    """Pure mode/zone gate -> proposal | promote | skip. Fail-closed."""
    if mode == "off":
        return "skip"
    if mode == "propose":
        return "proposal"
    if mode == "auto_safe":
        return "promote" if zone is Z.Zone.MUTABLE else "proposal"
    return "skip"                                # unknown mode = no action


def _unified(rel: str, before: str, after: str) -> str:
    return "".join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=f"a/{rel}", tofile=f"b/{rel}"))


def safe_rel(base: Path, rel: str) -> str:
    """AUD-26: validated repo-relative path — rejects absolute paths,
    drive letters, home expansion, `..` traversal and symlink escapes
    BEFORE any file access. Returns the normalized relative path or raises
    ValueError (callers turn that into a fail-closed `refused` trace)."""
    if not isinstance(rel, str) or not rel.strip():
        raise ValueError("empty path")
    if rel.startswith("/") or rel.startswith("~") or re.match(r"^[A-Za-z]:[\\/]", rel):
        raise ValueError(f"absolute path rejected: {rel!r}")
    p = PurePosixPath(rel)
    if not p.parts:
        raise ValueError(f"empty path rejected: {rel!r}")
    if ".." in p.parts:
        raise ValueError(f"traversal rejected: {rel!r}")
    base_r = base.resolve()
    # resolve() follows existing symlinks in the prefix even when the leaf
    # does not exist yet — containment must hold on the RESOLVED path.
    resolved = (base / rel).resolve()
    if resolved != base_r and base_r not in resolved.parents:
        raise ValueError(f"path escapes base via symlink: {rel!r} -> {resolved}")
    return str(p)


def _git(repo: Path, *args: str) -> str:
    # Explicit identity: throwaway worktrees/commits must work on CI runners
    # where no user.name/user.email is configured (found by branch CI run
    # 37777566560 — "Author identity unknown"). Same identity as rollback._git.
    out = subprocess.run(
        ["git", "-c", "user.name=raphael-evolution", "-c",
         "user.email=raphael@localhost", *args],
        cwd=str(repo), capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {out.stderr.strip()}")
    return out.stdout.strip()


def _goldens() -> List[Dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(B.GOLDEN_DIR.glob("*.json"))
            if p.name != "baseline.json"]


def run_cycle(mode: str, changes: Dict[str, str],
              targets: List[str], repo: Path = REPO_ROOT,
              slug: str = "cycle", python: str = sys.executable,
              now_ms: int | None = None,
              proposal_dir: Path = PROPOSAL_DIR,
              journal_dir: Path | None = None) -> Dict[str, Any]:
    """One evolution cycle. `changes` = {relpath: new_content}. Read-only over
    the caller's tree: the patch lands on a worktree branch, never here."""
    trace: Dict[str, Any] = {"ts": int(now_ms or time.time() * 1000),
                             "mode": mode, "slug": slug,
                             "changes": sorted(changes), "steps": []}

    def step(name: str, **kw: Any) -> None:
        trace["steps"].append({"step": name, **kw})

    # 0. AUD-26 path-escape guard — validate EVERY path BEFORE any file access
    # (no reads, no guard subprocess, no worktree until this passes).
    safe_changes: Dict[str, str] = {}
    for rel, new in changes.items():
        try:
            safe_changes[safe_rel(repo, rel)] = new
        except ValueError as exc:
            step("path_guard", ok=False, path=rel, error=str(exc))
            trace.update(status="refused", reason=f"unsafe path: {exc}")
            return trace
    changes = safe_changes
    step("path_guard", ok=True, paths=sorted(changes))

    # 1. Core Guard gate (fail-closed)
    guard_ok, guard_msg = R.verify_core_guard(repo, python)
    step("core_guard", ok=guard_ok, msg=guard_msg)
    if not guard_ok:
        trace.update(status="refused", reason="core guard not OK")
        return trace

    # 2. classify + mode gate
    diff_text = "".join(
        _unified(rel, (repo / rel).read_text(encoding="utf-8"), new)
        for rel, new in changes.items() if (repo / rel).is_file())
    zone = Z.classify(changes, diff_text)
    action = decide(mode, zone)
    step("classify", zone=zone.value, action=action)
    if action == "skip":
        trace.update(status="skipped", reason=f"mode={mode}")
        return trace

    # 3. baseline = current (pre-patch) state, shadow-verified
    pre = S.run_tests(repo, targets, python=python)
    base = B.capture(repo, pre, transcripts=_goldens())
    step("baseline", shadow_ok=bool(pre.get("ok")), rc=pre.get("rc"),
         core_guard=bool(base["core_guard"]["ok"]),
         transcripts=len(base["transcripts"]))

    # 4. patch on an isolated worktree branch (never the caller's tree)
    slug_safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in slug)
    branch = f"evo/{slug_safe}"
    wt = Path(tempfile.mkdtemp(prefix=f"evo-{slug_safe}-"))
    created = False
    try:
        _git(repo, "worktree", "add", "-q", "-b", branch, str(wt), "HEAD")
        created = True
        step("worktree", branch=branch, path=str(wt))
        for rel, new in changes.items():
            try:
                safe_rel(wt, rel)          # re-validated against the worktree
            except ValueError as exc:
                step("path_guard", ok=False, phase="worktree", path=rel,
                     error=str(exc))
                trace.update(status="refused",
                             reason=f"unsafe path (worktree): {exc}")
                return trace
            target = wt / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(new, encoding="utf-8")
        _git(wt, "add", "-A")
        _git(wt, "commit", "-q", "-m", f"[evolution] {slug} ({mode} cycle)")
        patch_commit = _git(wt, "rev-parse", "HEAD")
        step("patch", commit=patch_commit, files=sorted(changes))

        # 5. shadow verification of the PATCHED tree
        post = S.run_tests(wt, targets, python=python)
        cur = B.capture(wt, post, transcripts=_goldens())
        verdict = B.compare(cur, base)
        step("shadow_verify", ok=bool(post.get("ok")), rc=post.get("rc"),
             output_tail=(post.get("output") or "")[-600:])
        step("compare", ok=verdict["ok"], deltas=verdict["deltas"])

        # 6. decision — propose NEVER merges; auto_safe promotion = a REAL
        #    fast-forward merge through the approved gate (AUD-26: a commit
        #    that gets deleted with its temp worktree was never promoted).
        #    Any refusal fails CLOSED to proposal — caller's dirty tree is
        #    left untouched (git refuses the merge; we never force).
        wants_promote = (action == "promote" and verdict["ok"]
                         and zone is Z.Zone.MUTABLE)
        promoted = False
        if wants_promote:
            try:
                _git(repo, "merge", "--ff-only", patch_commit)
                R.tag_last_known_good(repo, patch_commit, slug)
                promoted = True
                promote_reason = ("fast-forwarded into the current branch; "
                                  "last-known-good tagged at the patch")
            except RuntimeError as exc:
                promote_reason = (f"merge refused — fail closed to proposal, "
                                  f"caller tree preserved: {exc}")
        elif action == "promote":
            promote_reason = "gates not green / not mutable — fail closed to proposal"
        else:
            promote_reason = "propose mode never merges"
        decision = "promoted" if promoted else "proposal"
        entry = J.make_entry(
            finding=slug, zone=zone.value, mode=mode, decision=decision,
            paths=sorted(changes),
            reason=f"cycle: {zone.value} target, mode={mode}; {promote_reason}",
            tests=(f"shadow: {'green' if post.get('ok') else 'RED'} "
                   f"(rc={post.get('rc')}); compare ok={verdict['ok']} "
                   f"deltas={verdict['deltas']}"),
            diff=diff_text, diff_commit=patch_commit,
            baseline_compare=f"ok={verdict['ok']} deltas={verdict['deltas']}",
            budget={"targets": targets})
        step("decision", decision=decision,
             merged=promoted,
             reason=promote_reason)

        # 7. proposal file (or journal-only for a promote)
        proposal_path = None
        if decision == "proposal":
            proposal_dir.mkdir(parents=True, exist_ok=True)
            proposal_path = proposal_dir / f"{time.strftime('%Y-%m-%d')}-{slug_safe}.md"
            proposal_path.write_text("\n".join([
                f"# PROPOSAL: {slug}", "",
                f"- mode: `{mode}`   zone: `{zone.value}`   branch: `{branch}`",
                f"- patch commit: `{patch_commit}` (worktree branch, NOT merged)",
                f"- guard: `{guard_msg}`", "",
                "## Before / after", "", "```diff", diff_text.rstrip(), "```", "",
                "## Quality report", "",
                f"- shadow tests: {'GREEN' if post.get('ok') else 'RED'} "
                f"(rc={post.get('rc')}), targets={targets}",
                f"- baseline compare: ok={verdict['ok']}, deltas={verdict['deltas']}",
                f"- core guard: {'OK' if base['core_guard']['ok'] else 'DRIFT'}",
                f"- golden transcripts: {len(base['transcripts'])} compared, "
                f"{'identical' if not any('transcript' in d for d in verdict['deltas']) else 'DELTA'}",
                "",
                "## Rollback", "",
                f"`git revert --no-edit {patch_commit}` (branch only — nothing to revert "
                "on main until/unless the user approves)",
                "",
                "> **Auto-apply: NEVER in propose mode.** Approval = user says yes.",
            ]) + "\n", encoding="utf-8")
        jdir = journal_dir or (repo / "docs" / "evolution" / "journal")
        jpath = J.write_entry(jdir, entry)
        step("journal", entry=str(jpath), proposal=str(proposal_path) if proposal_path else None)

        # 8. probation is an APPROVAL artifact — dry-run only, tmp state
        from brain.persona import probation as P
        with tempfile.TemporaryDirectory(prefix="evo-probation-") as td:
            st = P.start("great_sage", "raphael", {"jobs": 20, "hours": 24},
                         path=Path(td) / "state.json")
            P.record(st, ok=True, reason="dry-run cycle", path=Path(td) / "state.json")
            v = P.evaluate(st, path=Path(td) / "state.json")
        step("probation_dryrun", started=st["status"], verdict=v["status"],
             reason=v["reason"], note="SIMULATED in tmp — real probation starts "
             "only after an approved promotion")

        trace.update(status="proposal_written" if decision == "proposal"
                     else "promoted",
                     merged=promoted,
                     proposal=str(proposal_path) if proposal_path else None,
                     branch=branch, patch_commit=patch_commit)
        return trace
    finally:
        if created:
            subprocess.run(["git", "worktree", "remove", "--force", str(wt)],
                           cwd=str(repo), capture_output=True, timeout=120)
            subprocess.run(["git", "branch", "-D", f"evo/{slug_safe}"],
                           cwd=str(repo), capture_output=True, timeout=120)
            subprocess.run(["git", "worktree", "prune"],
                           cwd=str(repo), capture_output=True, timeout=60)


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="run one evolution cycle")
    ap.add_argument("--change", action="append", required=True,
                    metavar="REL=NEWFILE", help="patch: repo path = file with new content")
    ap.add_argument("--target", action="append", default=None,
                    help="pytest targets for the shadow run")
    ap.add_argument("--mode", default=None, help="off|propose|auto_safe "
                    "(default: evolution.mode from config)")
    ap.add_argument("--slug", default="cycle")
    args = ap.parse_args(argv)

    from brain import config as cfg
    mode = args.mode or cfg.cfg_get(cfg.load_config(), "evolution.mode", "propose")
    changes = {}
    for spec in args.change:
        rel, _, src = spec.partition("=")
        changes[rel] = Path(src).read_text(encoding="utf-8")
    targets = args.target or ["brain/evolution/tests", "brain/persona/tests"]
    trace = run_cycle(mode, changes, targets, slug=args.slug)
    print(json.dumps(trace, indent=2, sort_keys=True))
    return 0 if trace.get("status") in ("proposal_written", "skipped",
                                        "promoted") else 1


if __name__ == "__main__":
    raise SystemExit(main())
