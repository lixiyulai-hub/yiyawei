# Architecture Stability

## Local Gates

Run the same ordered gates locally before handing work off:

```powershell
python -X utf8 -m pytest -q
python -X utf8 -m pytest -c pytest.e2e.ini e2e -q
python -X utf8 -m compileall app.py src tests scripts e2e
python scripts/package_preflight.py --out "$env:TEMP/package_preflight.json" --fail-on-error
git diff --check
```

These gates are offline apart from installing declared tool dependencies. They do
not call an external model, run benchmarks, run governance hot paths, or upload
user data. Package preflight may report optional ASR/model dependencies as
warnings because the CI environment intentionally excludes those heavy runtimes.

## Change Discipline

For a bug, write a failing test first, then make the smallest repair that makes
the test pass. Keep refactor commits separate from feature commits so that a
regression can be located without mixing behavior changes and code movement.

Use a feature flag only for a high-risk, short-lived rollout. Record its owner
and removal condition when the flag is introduced, and remove it once the
condition is met. Do not use a flag to defer an unclear design decision.

## Regression Isolation

Use git bisect when a known-good and known-bad revision are available:

```powershell
git bisect start
git bisect bad <known-bad>
git bisect good <known-good>
git bisect run python -X utf8 -m pytest -q
git bisect reset
```

Use the narrowest deterministic test that demonstrates the regression before
using the full gate sequence.

## Windows Manual Smoke

Automated gates cannot prove the Windows input path. Manually verify a selected
microphone records audio, the intended target window retains focus behavior, and
the clipboard plus Ctrl+V paste reaches that target without activating the web
GUI window. Repeat the smoke after changes to recorder, foreground-window, or
paste behavior.

## Optional Hosted Checks

The workflow file is inert when this local repository has no remote. Only after
the user explicitly authorizes a private GitHub repository may an operator add a
remote, push this workflow, and configure branch protection. The required branch
check context is `windows` from the `architecture-gates` workflow. This document
does not configure a remote or grant that authorization.
