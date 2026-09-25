# The pull-request surface

SVRF's decision about a pull request is visible on the pull request itself: a commit
status and one living comment, so a developer never has to go find the train's receipt or
log to know why their head is waiting, gating, landed, or held.

Controlled by two config keys, both on by default:

```toml
[ui]
pr_comments = true    # the living comment
status_checks = true  # the "svrf" commit status
dashboard_url = ""    # optional; becomes the status's target_url when set
```

## The commit status

One status, context `svrf`, on the candidate head SVRF is currently working with (the
original branch head while queued and gating; the branch's own commit, after SVRF has
merged the base into it, once landed):

| State | Description |
| --- | --- |
| pending | `queued (position 3, batch F2)` |
| pending | `gating batch F2 with #12 #15` |
| success | `landed in batch F2 (gate 1m32s)` |
| failure | `held: <one-line reason>` |

If `ui.dashboard_url` is set, the status's "Details" link (`target_url`) points at it.

## The living comment

One comment per pull request, created once and edited in place — found again on every
update by a hidden HTML marker, never duplicated. A rendered example, once a family
lands:

> ✅ **SVRF: landed**
>
> Batch `F2` with #12 #16
>
> ✅ queued → ✅ gating → ✅ landed
>
> Gate: 1m32s
>
> **landed tree = gated tree** ✔️

And once a gate holds it:

> 🛑 **SVRF: held**
>
> Batch `F2` with #15 #16
>
> ✅ queued → ✅ gating → ✖️ held
>
> **Next:** push a fix; SVRF retries automatically when your head changes
>
> <details><summary>Why it's held</summary>
>
> ```
> FAILED tests/test_login.py::test_expired_token - AssertionError
> ```
>
> </details>

A pull request left out of the round by a pairwise conflict (not a gate failure) gets the
same held rendering, with its next step naming the partner and the path instead:
`conflicts with #7 on src/app.py`.

## Rate limits and security

- **Batched, not chatty.** A comment is only re-rendered on a real phase change (queued →
  gating → landed/held); the rendered body is hashed and an unchanged comment is never
  re-edited (`receipt["surface"]["comment_skip"]`). Every status and comment call is
  counted in the run's receipt (`receipt["surface"]`), alongside the existing
  `api_calls` totals.
- **A pull request's title, branch name and gate output are attacker-controlled.** Every
  value that reaches the comment goes through `svrf.pr_surface.escape_md`, which strips
  control characters and escapes Markdown's structural characters (`` ` ``, `*`, `_`,
  `[`, `]`, `(`, `)`, `|`, `~`, `^`, plus `<`, `>`, `&` for raw HTML), so it can only ever
  render as literal text — never new Markdown structure and never raw HTML. Failing gate
  lines are additionally placed in a fenced code block wide enough to swallow any run of
  backticks already in the content, so held output cannot break out of the block.
- **Best-effort.** A rate-limited status or comment call is waited out and retried like
  any other GitHub call the train makes; any other failed read is skipped for that one
  update (the next phase transition tries again) and never turns into a hold or stops the
  round: the surface is a view onto the train's decision, not part of it.
