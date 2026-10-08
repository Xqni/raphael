#!/usr/bin/env python3
"""handler_dryrun — MECHANICAL reference implementation of the integrator event handler.

Non-LLM: used by tests and rehearsals to prove the coord event flow end to end. The REAL
integrator handler is the prompt ~/.raphael-coord/prompts/integrator_event.md executed by a
fresh `opencode run` (LLM judgment for decisions); this file mirrors its deterministic steps:

  1. read unread events per lane (state.json cursors)
  2. dispatch by type:
       task_done / test_result -> progress note (logged)
       request                 -> decision written to inbox(requester) + inbox(owner)
                                   (shared-contract refs notify every lane)
       blocked                 -> escalated: attention + answer to the lane
       error / user_attention  -> attention
       wave_done               -> ownership check (docs/OWNERSHIP.md + git diff paths),
                                   tests (logged), MERGE MOCKED -> decision "merged <sha>"
  3. advance the cursor ONLY after the lane's batch is handled
  4. wave gate: when every required lane (wave >= min_wave, not paused) has merged ->
       --mock-gate: bump current_wave, post wave_open to every lane inbox
       wave in live-gate list: coord attention (LIVE gate — never auto-passed)
       otherwise: bump

Merges are ALWAYS mocked here (it is the dry-run handler); real merges happen only in the
LLM handler per the prompt. Exit 0 on success; "no new events" = idempotent no-op.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coord  # noqa: E402
from coord import LANES, coord_dir, line_count, read_jsonl, read_state  # noqa: E402

SHARED_PREFIX = ("docs/PROTOCOL", "docs/ARCHITECTURE", "docs/INTERFACES", "docs/WAVES",
                 "docs/OWNERSHIP", "docs/AGENT_RULES", "config.yaml")


# --------------------------------------------------------------- OWNERSHIP parsing

def expand_braces(pat: str) -> list[str]:
    m = re.search(r"\{([^{}]*)\}", pat)
    if not m:
        return [pat]
    out = []
    for alt in m.group(1).split(","):
        out.extend(expand_braces(pat[:m.start()] + alt + pat[m.end():]))
    return out


def parse_ownership(text: str) -> dict[str, list[str]]:
    lanes: dict[str, list[str]] = {}
    for row in text.splitlines():
        row = row.strip()
        if not row.startswith("|"):
            continue
        cells = [c.strip() for c in row.strip("|").split("|")]
        if len(cells) < 2:
            continue
        m = re.match(r"\*\*(.+?)\*\*", cells[0])
        if not m or m.group(1) == "Lane":
            continue
        lane = m.group(1)
        pats = []
        for raw in re.findall(r"`([^`]+)`", cells[1]):
            for p in expand_braces(raw):
                pats.append(p.replace("**", "*"))
        if pats:
            lanes[lane] = pats
    return lanes


def owners_of(path: str, ownership: dict[str, list[str]]) -> list[str]:
    hits = []
    for lane, pats in ownership.items():
        for pat in pats:
            if fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(path, pat.rstrip("*")):
                hits.append(lane)
                break
    return hits


def git(repo: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(repo), *args],
                           capture_output=True, text=True, timeout=30)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def ownership_check(lane: str, repo: Path, ownership: dict[str, list[str]],
                    base: str = "main") -> tuple[list[str], list[str], str]:
    """-> (veto_paths, advisory_paths, note). Read-only."""
    if not repo.is_dir():
        return [], [], f"no worktree at {repo} — check skipped"
    diff = git(repo, "diff", "--name-only", f"{base}...agent/{lane}")
    if diff is None:
        return [], [], "git diff failed — check skipped"
    if not diff:
        return [], [], f"no committed diff vs {base}"
    veto, advisory = [], []
    for p in diff.splitlines():
        p = p.strip()
        if not p:
            continue
        owns = owners_of(p, ownership)
        if lane not in owns:
            veto.append(f"{p} (owned by: {', '.join(owns) or 'nobody/unlisted=integrator'})")
        elif len(owns) > 1:
            advisory.append(f"{p} (also matches {', '.join(o for o in owns if o != lane)})")
    return veto, advisory, f"{len(diff.splitlines())} changed file(s)"


# --------------------------------------------------------------- dispatchers

def handle_request(cd: Path, ev: dict, ownership: dict[str, list[str]], dry: bool) -> None:
    requester = ev["lane"]
    ref = ev.get("ref") or ""
    owner = None
    for lane, pats in ownership.items():
        if any(fnmatch.fnmatch(ref, p.replace("**", "*")) for p in pats if ref):
            owner = lane
            break
    decision = (f"decision: accepted — {ev.get('msg', '')[:180]} "
                f"(ref: {ref or 'n/a'}); owner implements and reports via coord.")
    coord.cmd_reply(_ns(lane=requester, type="decision", msg=decision, ref=ref, data=None))
    if owner and owner != requester:
        coord.cmd_reply(_ns(lane=owner, type="decision",
                            msg=f"request from {requester}: {decision}", ref=ref, data=None))
    if ref.startswith(SHARED_PREFIX):
        for ln in LANES:
            if ln not in (requester, owner):
                coord.cmd_reply(_ns(lane=ln, type="nudge",
                                    msg=f"shared contract change requested by {requester}: {ref}",
                                    ref=ref, data=None))
    print(f"  request({requester}): decision written" + (f" -> {owner}" if owner else ""))


def handle_wave_done(cd: Path, ev: dict, ownership: dict[str, list[str]],
                     repo_root: Path, wt_root: Path, dry: bool) -> bool:
    """Returns True if merged (mocked), False if rejected."""
    lane = ev["lane"]
    repo = wt_root / lane
    veto, advisory, note = ownership_check(lane, repo, ownership)
    print(f"  wave_done({lane}): ownership — {note}")
    for a in advisory:
        print(f"    advisory: {a}")
    if veto:
        msg = ("decision: REJECTED — ownership violations in this branch: "
               + "; ".join(veto) + ". Fix or move the change behind a docs/requests/ request.")
        coord.cmd_reply(_ns(lane=lane, type="decision", msg=msg, ref="docs/OWNERSHIP.md",
                            data={"veto": veto}))
        print(f"  wave_done({lane}): REJECTED")
        return False
    sha = (git(repo, "rev-parse", "--short", "HEAD") or "DRYRUN")
    print(f"  wave_done({lane}): tests — would run the lane test suite (mocked)")
    print(f"  wave_done({lane}): merge agent/{lane} @ {sha} — MOCKED (dry-run)")
    coord.cmd_reply(_ns(lane=lane, type="decision",
                        msg=f"decision: merged agent/{lane} {sha} (dry-run merge; "
                            f"tests mocked)",
                        ref=None, data={"sha": sha, "dry_run": True}))
    return True


def _ns(**kw):
    class NS:
        pass
    n = NS()
    n.lane = kw.get("lane")
    n.type = kw.get("type")
    n.msg = kw.get("msg")
    n.ref = kw.get("ref")
    n.data = kw.get("data")
    n.set = kw.get("set")
    n.wave = kw.get("wave")
    n.json = False
    n.mark_read = False
    n.unread = False
    return n


# --------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="mechanical integrator event handler (dry-run)")
    ap.add_argument("--dry-run", action="store_true", default=True,
                    help="mock merges/tests (always true — see module docstring)")
    ap.add_argument("--mock-gate", action="store_true",
                    help="test-only: bypass the LIVE wave gate and bump the wave")
    ap.add_argument("--live-gate-waves", default="2",
                    help="comma list of waves requiring a LIVE E2E before bumping")
    ap.add_argument("--wt-root", default=str(Path.home() / "raphael-wt"))
    ap.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument("--write-progress", action="store_true",
                    help="append task_done notes to PROGRESS.md (off in tests)")
    args = ap.parse_args(argv)

    cd = coord_dir()
    st = read_state(cd)
    own_text = (Path(args.repo_root) / "docs" / "OWNERSHIP.md").read_text(encoding="utf-8") \
        if (Path(args.repo_root) / "docs" / "OWNERSHIP.md").exists() else ""
    ownership = parse_ownership(own_text)
    wt_root = Path(args.wt_root)

    # 1) gather unread
    unread: dict[str, list] = {}
    cursors = coord.read_cursors(cd)
    for lane in LANES:
        evs = read_jsonl(cd / "events" / f"{lane}.jsonl")
        cur = int(cursors.get(lane, 0))
        if len(evs) > cur:
            unread[lane] = evs[cur:]
    if not unread:
        print("handler: no new events — nothing to do (idempotent)")
        return 0
    print(f"handler: {sum(len(v) for v in unread.values())} event(s) across {len(unread)} lane(s)")

    wave = int(st["current_wave"])
    merged_now: list[str] = []

    # 2) dispatch
    for lane, evs in sorted(unread.items()):
        print(f"[{lane}]")
        for ev in evs:
            t = ev.get("type")
            if t in ("task_done", "test_result"):
                print(f"  {t}: {ev.get('msg', '')[:120]}")
                if args.write_progress:
                    with (Path(args.repo_root) / "PROGRESS.md").open("a") as f:
                        f.write(f"- {t} ({lane}): {ev.get('msg', '')}\n")
            elif t == "heartbeat":
                pass
            elif t == "request":
                handle_request(cd, ev, ownership, args.dry_run)
            elif t == "blocked":
                need_human = any(k in (ev.get("msg", "").lower())
                                 for k in ("human", "user", "money", "key", "uncertain"))
                if need_human:
                    subprocess.run([sys.executable, str(Path(coord.__file__)), "attention",
                                    f"blocked({lane}): {ev.get('msg', '')}"],
                                   capture_output=True, timeout=30)
                    print(f"  blocked: escalated to the human")
                coord.cmd_reply(_ns(lane=lane, type="answer",
                                    msg=f"blocked escalated: {ev.get('msg', '')[:160]}",
                                    ref=ev.get("ref"), data=None))
            elif t == "error" or t == "user_attention":
                subprocess.run([sys.executable, str(Path(coord.__file__)), "attention",
                                f"{t}({lane}): {ev.get('msg', '')}"],
                               capture_output=True, timeout=30)
                print(f"  {t}: escalated to the human")
            elif t == "wave_done":
                if handle_wave_done(cd, ev, ownership, Path(args.repo_root), wt_root,
                                    args.dry_run):
                    merged_now.append(lane)
            else:
                print(f"  unhandled type {t!r} (acknowledged)")
        # 3) cursor advance AFTER the batch is handled
        coord.cmd_cursor(_ns(lane=lane, set=line_count(cd / "events" / f"{lane}.jsonl")))

    # record merges into state
    def _mark(s):
        for ln in merged_now:
            s["lanes"].setdefault(ln, {})["merged_wave"] = s["current_wave"]
    coord.mutate_state(cd, _mark)
    st = read_state(cd)

    # 4) wave gate
    def required(s) -> list[str]:
        conds = s.get("start_conditions", {})
        out = []
        for ln in LANES:
            if s["lanes"].get(ln, {}).get("paused"):
                continue
            mw = int(conds.get(ln, {}).get("min_wave", 1))
            if s["current_wave"] >= mw:
                out.append(ln)
        return out

    req = required(st)
    not_merged = [ln for ln in req
                  if st["lanes"].get(ln, {}).get("merged_wave") != st["current_wave"]]
    if req and not not_merged:
        if args.mock_gate:
            new_wave = int(st["current_wave"]) + 1
            coord.cmd_wave_bump(_ns(wave=new_wave))
            for ln in LANES:
                coord.cmd_reply(_ns(lane=ln, type="wave_open",
                                    msg=f"wave {new_wave} is open — read docs/WAVES.md, your "
                                        f"inbox, rebase on main, continue your work loop, "
                                        f"report via coord.",
                                    ref=None, data={"wave": new_wave}))
            print(f"handler: all required lanes merged -> WAVE {st['current_wave']} -> "
                  f"{new_wave} (mock gate)")
            return 0
        live = {int(x) for x in args.live_gate_waves.split(",") if x.strip()}
        if int(st["current_wave"]) in live:
            subprocess.run([sys.executable, str(Path(coord.__file__)), "attention",
                            f"Wave {st['current_wave']} gate ready: all required lanes merged; "
                            f"say go for the live E2E on the real instance."],
                           capture_output=True, timeout=30)
            print(f"handler: wave {st['current_wave']} gate READY — awaiting the human "
                  f"(live E2E required; not bumping)")
            return 0
        new_wave = int(st["current_wave"]) + 1
        coord.cmd_wave_bump(_ns(wave=new_wave))
        for ln in LANES:
            coord.cmd_reply(_ns(lane=ln, type="wave_open",
                                msg=f"wave {new_wave} is open — continue your work loop.",
                                ref=None, data={"wave": new_wave}))
        print(f"handler: bumped wave {st['current_wave']} -> {new_wave}")
        return 0
    print(f"handler: wave {st['current_wave']} not complete — waiting on: "
          f"{', '.join(not_merged)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
