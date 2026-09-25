# Dashboard

`svrf dashboard` turns the train's round receipts into a static site: one `index.html`
with its CSS, JavaScript and data inline. It makes no network requests, so it works
opened straight from disk (`file://`) and served from GitHub Pages or any static host.

```sh
svrf dashboard --receipts ~/.local/share/svrf/state/receipts --out site/
open site/index.html            # or xdg-open
```

It needs no `svrf.toml` and no token: it only reads `train-*.json` receipts
(`<state_dir>/receipts/`). A file that can't be parsed is skipped and counted in the
footer.

Try it on the bundled sample, which is anonymized receipts from a real day of runs:

```sh
make dashboard-sample           # writes build/dashboard/index.html
```

![Dashboard, light](img/dashboard.png)

## What it shows

| Section | Read from the receipts |
| --- | --- |
| **Totals** | merged pull requests, gate runs (a reused red result is not counted as a run), gates per merged PR, wall time per merged PR (finished rounds' duration ÷ merged), holds |
| **Live queue** | the latest receipt: each requested pull request's position, its batch (family), and its state (`gating`, `queued`, `landing`, `landed`, `held`, `retry`, `out`). A round still running shows *Round running* in the header. |
| **Landed tree = gated tree** | every merge record: *identical* (the fetched merge commit's tree equals the gated tree), *mismatch*, or *unread* (the merge commit couldn't be fetched when it was compared; that is retried, never counted as a mismatch) |
| **Throughput** | merges per UTC hour, empty hours included |
| **Gates per PR, wall time per PR** | one column per round that merged something, with the overall figure as a reference line |
| **Batch timeline** | per round, one row per gate run: waiting (from the round start, or for a bisected half from when its parent's gate came back red), gating (green or red), then landing up to the batch's last merge |
| **Bisection** | the family tree of every round that had a red batch: which halves were gated, which result was reused, which pull request ended up held |
| **Holds** | every hold with its reason and first failing line |

Light and dark follow the viewer's system setting; the *Theme* button overrides it and is
remembered in that browser. The layout works down to phone width.

![Timeline and bisection, dark](img/dashboard-bisection-dark.png)

## Publishing to GitHub Pages

Pages sites are public on most plans. Receipts carry pull-request numbers, commit shas
and your gate's failing lines; if those shouldn't be public, publish from a private
repository with Pages access control, or run the receipts through
`demo/anonymize_receipts.py` first (it keeps numbers and timings, and drops titles,
branch names, paths and output).

In the repository's **Settings → Pages**, set **Source** to **GitHub Actions**.

### From the machine that runs the train (self-hosted runner)

If SVRF runs under systemd or Docker on a machine that is also a self-hosted runner for
the repository, the receipts are already on disk:

```yaml
name: dashboard
on:
  schedule:
    - cron: "*/15 * * * *"
  workflow_dispatch: {}

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: true

jobs:
  publish:
    runs-on: [self-hosted, linux]
    environment:
      name: github-pages
      url: ${{ steps.deploy.outputs.page_url }}
    steps:
      - name: Build the dashboard from the train's receipts
        run: svrf dashboard --receipts "$HOME/.local/share/svrf/state/receipts" --out site
        # Docker instead of a pip install (the image's state volume is read only here):
        # run: |
        #   mkdir -p site
        #   docker run --rm -v svrf-state:/var/lib/svrf:ro -v "$PWD/site:/site" \
        #     --entrypoint svrf svrf dashboard --receipts /var/lib/svrf/receipts --out /site
      - uses: actions/upload-pages-artifact@v3
        with:
          path: site
      - id: deploy
        uses: actions/deploy-pages@v4
```

Point `--receipts` at your own `state_dir` if you changed it (`svrf config` prints it).
Reading the receipts doesn't take the train's lock, so this can run while a round is in
progress; a receipt is rewritten atomically after every event.

### From the train's own Action

When the train runs as a scheduled Action ([ACTION.md](ACTION.md)) with its state cached,
add the dashboard to the same job after the round:

```yaml
      - uses: nybarius/SVRF@v0.1.0
        with:
          github-token: ${{ secrets.SVRF_TOKEN }}
          config: svrf.toml

      - name: Build the dashboard
        if: always()
        run: svrf dashboard --receipts ~/.local/share/svrf/state/receipts --out site
      - uses: actions/upload-pages-artifact@v3
        if: always()
        with:
          path: site
      - uses: actions/deploy-pages@v4
        if: always()
```

The job then also needs `permissions: {pages: write, id-token: write}` and the
`github-pages` environment, as above. On a hosted runner the receipts only survive
between runs through the `actions/cache` step shown in [ACTION.md](ACTION.md), so the
dashboard covers the rounds that cache still holds.
