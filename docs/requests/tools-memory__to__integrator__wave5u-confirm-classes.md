# tools-memory → integrator: Wave 5U/5.4 P0 — confirm-class additions to safety.confirm_policy
Status: OPEN

## What
Wave-5U §5.4 P0 task 1 (dispatch [32]) requires tagging every tools-memory
tool with a confirm class. Existing `safety.confirm_policy.classes` covers
file_write/files_delete/web_fetch, but these charter-mandated classes do NOT
exist yet (config = integrator-owned + Core Guard per P0.1):

```yaml
safety:
  confirm_policy:
    classes:
      # tools-memory Wave 5U additions (charter docs/USEFUL-NOW-PLAN.md §5.4)
      read_only: auto        # file_read, file_search, shell_list, github_status,
                             # mcp_list, timer_list, schedule_list (pure reads)
      schedule: auto         # timer_set/timer_cancel/reminder_set/schedule_*
                             # (reversible local, act-first per charter)
      system_command: confirm  # shell — explicit (currently falls to default)
      web_publish: confirm   # github_push (publish; default-confirm today too)
      mcp_tool: confirm      # MCP wrapped tools + mcp_refresh (spawn) — default
                             # per charter "MCP wrapped tools default confirm"
```

Tool→class map I am tagging NOW (brain-core P0.2 coordination, names above +
existing): web_fetch/web_search/web_summarize → `web_fetch` (existing auto);
file_write → `files_write`; file_trash → `delete_files`; shell →
`system_command`; github_push → `web_publish`; github_status → `read_only`;
file_read/file_search/shell_list → `read_only`; all schedule writers →
`schedule`, schedule readers → `read_only`; mcp_list → `read_only`,
mcp_refresh + dynamic wrapped tools → `mcp_tool`.

## Why
P0.2 (plan review #2): "tool with no class → confirm (fail closed)". Reads
must still carry an explicit class or they fail closed to confirm after
P0.1/P0.2 land. Classes must be in the map first, else `default: confirm`
nags on every read. Until your entry lands, tags are fail-CLOSED (safe
direction, never a loosening).

## Impact
- Config-only + Core Guard-adjacent: values above are the charter's own
  verdicts (auto = reversible/unambiguous; confirm = destructive/publish/
  spawn). No behavior loosening vs today: system_command/web_publish/mcp_tool
  already resolve confirm via `default`.
- One YAML block + your approval; brain-core's P0.1 resolver reads it as-is.
