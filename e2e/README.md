# Web GUI browser characterization

These tests run the real `WebGuiController` loopback HTTP server and the real
`index.html`, the `styles.css` entrypoint and its seven imported CSS modules, and native ES modules
rooted at `main.js`. Only the recorder, application pipeline, window discovery, and paste integration
are deterministic fakes.
No microphone, LLM, paste target, foreground window, or external network is
used.

## Browser path

The fixture prefers system Edge through `channel="msedge"`; when Edge is
absent or cannot launch it uses an already installed Playwright Chromium. It
never downloads a browser during tests. A new development machine therefore
needs a separately provisioned browser before running this suite.

Each test gets a fresh controller, loopback server, browser context, and page.
The browser process may be shared for speed. Requests outside that test's
loopback origin are aborted and fail the test.

## Run

Install declared development dependencies and a browser separately when
preparing a new development machine. The E2E run itself is offline.

```powershell
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
python -X utf8 -m pytest -c pytest.e2e.ini e2e -q
```

The suite covers warming to ready, user-clicked recording through processing
and done, exactly-once auto-stop, dirty edit protection and restore, fast-mode
and custom-select settings/theme persistence, and fixed 700x640 plus 390x720
layout checks.

## Screenshot evidence

Committed PNGs under `e2e/baselines` are deterministic state evidence, not
cross-platform golden-image assertions. Tests disable CSS motion, hide the
continuously animated canvas, fix the theme and dynamic fake values, then
verify that both current captures and baselines are non-empty PNGs with the
expected dimensions. DOM state and element geometry carry the behavioral
assertions, so font rasterization or browser patch versions do not cause a
pixel-diff failure.

Refresh baselines intentionally with:

```powershell
$env:UPDATE_E2E_BASELINES = "1"
python -X utf8 -m pytest -c pytest.e2e.ini e2e -q -k "warming or recording or fixed_viewports"
Remove-Item Env:UPDATE_E2E_BASELINES
```

Review all changed PNGs before keeping an update. Normal test runs write
screenshots only to pytest's system temporary directory.
