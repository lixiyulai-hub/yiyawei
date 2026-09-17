# Quality Gates

Governance level: G2

## Fast
- affected.compile: `python -B -X utf8 -m compileall -q app.py src tests scripts e2e` (.governance/policy.toml)
- affected.core-contracts: `python -B -X utf8 -m pytest -q tests/test_app_pipeline.py tests/test_config_defaults.py tests/test_plugin_bridge.py tests/test_paste_injector.py tests/test_web_gui_contracts.py tests/test_ci_contract.py` (.governance/policy.toml)

## Full
- full.package-preflight: `python -B -X utf8 scripts/package_preflight.py --print-json --fail-on-error` (.governance/policy.toml)
- full.pyinstaller-readiness: `python -B -X utf8 scripts/pyinstaller_readiness.py --print-json --fail-on-error` (.governance/policy.toml)
- full.pytest: `python -B -X utf8 -m pytest -q` (.governance/policy.toml)
- full.web-e2e: `python -B -X utf8 -m pytest -c pytest.e2e.ini e2e -q` (.governance/policy.toml)

## Release
- Confirm the project command with evidence.

## Native command inventory
- affected.compile: `python -B -X utf8 -m compileall -q app.py src tests scripts e2e` (.governance/policy.toml)
- affected.core-contracts: `python -B -X utf8 -m pytest -q tests/test_app_pipeline.py tests/test_config_defaults.py tests/test_plugin_bridge.py tests/test_paste_injector.py tests/test_web_gui_contracts.py tests/test_ci_contract.py` (.governance/policy.toml)
- full.package-preflight: `python -B -X utf8 scripts/package_preflight.py --print-json --fail-on-error` (.governance/policy.toml)
- full.pyinstaller-readiness: `python -B -X utf8 scripts/pyinstaller_readiness.py --print-json --fail-on-error` (.governance/policy.toml)
- full.pytest: `python -B -X utf8 -m pytest -q` (.governance/policy.toml)
- full.web-e2e: `python -B -X utf8 -m pytest -c pytest.e2e.ini e2e -q` (.governance/policy.toml)

Every discovered command above is evidence-bearing. Commands without a recognized phase remain mapped to an **unknown phase** and require an evidence task before assignment to Fast, Full, or Release.

## Baseline policy
Unknown failures require an evidence-backed decision; no check is claimed without execution evidence.
