# pc-control → integrator: protocol-browser-act
Status: DONE — PRE-GRANTED. The §7 line already carries
`browser{op, ...}` (Wave 5U P1 pre-approval, quoted verbatim from
docs/PROTOCOL.md): "structured CDP ops — status|tabs|activate|navigate|
back|forward|reload|find|click|type|press|scroll|read; dedicated profile,
CDP bound 127.0.0.1, password-field typing and javascript:/file:/data:
navigation refused; request pc-control__to__integrator__protocol-browser-act".

## What (design record for the shipped shape)
```
`browser{op, ...}` — raw CDP driver over the hash-pinned `websockets`
package (SEC-9: no runtime installs; Playwright connect_over_cdp is the
documented fallback ONLY after 2 raw-CDP failures, then hash-pinned):
  status  {}                    -> {up, port, profile, active:{id,url,title}}
  tabs    {}                    -> {tabs:[{id,url,title}], active_id}
  activate{id}                  -> focus a tab (HTTP /json/activate)
  navigate{url, new_tab=false}  -> active tab Page.navigate (http/https
                                   only; javascript:/file:/data: REFUSED)
  back{} forward{} reload{}     -> history nav / Page.reload
  find{text?, role?, name?}     -> Accessibility.getFullAXTree filter ->
                                   refs [{ref, role, name, value}] (cap 50)
  click{ref}                    -> DOM.getBoxModel(backendNodeId) center ->
                                   Input.dispatchMouseEvent (needs_lock)
  type{text, ref?, submit=false}-> DOM.focus/elementFromPoint + Input.
                                   insertText (needs_lock; REFUSED when the
                                   focused element is a password field)
  press{key}                    -> Input.dispatchKeyEvent (whitelisted keys)
  scroll{dy}                    -> bounded window.scrollBy (|dy| <= 5000)
  read{max_chars}               -> AX text tree, CAPPED, data-only (no
                                   screenshots, no cloud vision for pages)
Profile/launch: `--user-data-dir=<instance data-dir>/browser-profile`,
`--remote-debugging-port=<instance cdp_port()>` (INTERFACES Wave-5U
addendum: main 9500, lanes 9500+idx; RAPHAEL_CDP_PORT override),
`--no-first-run --no-default-browser-check`; auto-attach when up, launch on
explicit browser ops; launch_url/search_youtube only REUSE when already up
(fallback open_url).
Privacy reads: `privacy.blocklist_apps` + `computer_use.sensitive_title_
patterns` gate find/read on the active tab (refuse + short reason).
```

## Why
Charter §5.2 P1 tasks 2-7 (docs/USEFUL-NOW-PLAN.md) — the request-first
step; §7 pre-approval landed [45], so this file records the shipped shape
for the audit trail.
