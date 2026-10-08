# GIT-SCRUB-PLAN.md — history scrub via git-filter-repo (PREPARED, NEVER RUN)

**Status: plan only.** Running it rewrites every commit in a 10-lane shared
repo — that is an integrator+human decision, coordinated AFTER the GitHub
visibility decision (scripts/SECRETS.md). Nothing here has been executed
(SEC-1: "prepare, do not run").

## Why it might be needed

`scripts/scan_personal.py` (SEC-1) reports personal details in TRACKED
files today (usernames, home/drive paths, IPs, voice-clip names — 415
findings on 2026-10-07, locations only). A top-of-tree scrub fixes FUTURE
commits; the historical copies need a history rewrite ONLY if the repo
ever goes public or the human asks.

## Preconditions (all must be true)

1. Human decision recorded (coord `attention` + docs/PAID_USAGE-style
   log): visibility goal + which rules are in scope.
2. Repo mirror backup: `git clone --mirror git@github.com:<org>/<repo>.git
   /path/to/backup-$(date +%F).git` (verify: `git -C backup fsck --full`).
3. All lane sessions IDLE (coordinator holds every lane lock); integrator
   announces a freeze window; CI disabled during the window.
4. `gitleaks` + `scripts/scan_personal.py --strict` green on the
   TOP-OF-TREE first (don't rewrite history holding live secrets — rotate
   first: scripts/SECRETS.md).

## Procedure (integrator, from a disposable clone)

```bash
pip install git-filter-repo
git clone --mirror git@github.com:<org>/<repo>.git repo-scrub.git
cd repo-scrub.git
# example: replace the Linux username everywhere (pick exact patterns
# from scripts/scan_personal.py RULES; each is a separate --replace-text)
git filter-repo --replace-text <(
  echo 'dami==>REDACTED-LINUXUSER'
  echo 'C:\Users\jxesu==>C:\Users\REDACTED'
  echo 'github.com/Xqni==>github.com/REDACTED'
) 2>&1 | tee /tmp/scrub.log
```

Rules of engagement:
- ONE pattern batch per run; verify between runs (below); never `--force`
  on the real remote without the mirror backup verified.
- Tags: filter-repo rewrites tag refs too — list them before/after
  (`git for-each-ref`) and diff counts.
- Filter out any file the human designates (e.g. SYSTEM_REPORT.md) with
  `--path ... --invert-paths` in a SEPARATE run.

## Verification (both sides)

```bash
# 1. old strings gone from ALL history:
git log --all -S 'jxesu' --oneline        # must be empty
git grep -I 'jxesu' $(git rev-list --all) 2>/dev/null | head   # empty
# 2. scanner strict on the rewritten tree:
python3 scripts/scan_personal.py --strict  # must exit 0
# 3. integrity:
git fsck --full                           # no errors
# 4. suite green at the new HEAD (integrator reruns CI, QA-4 link)
```

## Push + fallout (human steps)

1. `git push --force --mirror` (or push the scrubbed clone as a NEW
   private repo and swap remotes — SAFER: history-in-place force-push
   requires every lane worktree to re-clone; a new repo needs only remote
   changes).
2. Every worktree: `git fetch --all --tags` is NOT enough after a rewrite —
   each lane re-clones or runs `git rebase`-free reset to the new origin
   (coordinator broadcasts the exact commands).
3. Old commits may still exist server-side (GitHub keeps unreachable
   objects until GC / support ticket) — for a real purge, contact GitHub
   support or rotate-and-accept residual risk (documented decision).
4. Re-run `scripts/secret-scan.sh` + gitleaks after push.

## If the repo stays private (current state)

Top-of-tree scrub only (lane docs + integrator docs) + the scanner as a
standing gate. History rewrite deferred indefinitely — recorded here so it
is never improvised under time pressure.
