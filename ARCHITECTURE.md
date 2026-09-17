# Architecture

Yiyawei is a local-first Windows application. The public snapshot contains
the implementation and offline tests; internal governance receipts and local
runtime evidence are kept outside the snapshot.

## Flow

1. `app.py` loads configuration and selects the CLI, GUI, text, or daemon entrypoint.
2. `src/recorder/` captures audio and passes a WAV buffer to `src/asr/`.
3. `src/asr/` provides the FunASR adapter and returns transcript text.
4. `src/auditor/` classifies and compiles the transcript through the selected local LLM adapter in `src/llm/`.
5. `src/text/` applies conservative text handling, and `src/injector/` optionally restores the result to the active input target.
6. `src/gui/` exposes the desktop and Web GUI flows; `src/plugin_bridge/` exposes the local loopback integration contract.

## Boundaries

- Configuration is loaded through `src/config/`; runtime code does not read governance receipts or generated release reports.
- ASR and LLM providers are adapters. Model weights and local services are user-provided and are not included in this snapshot.
- Clipboard/paste and foreground-window behavior are Windows-specific integration surfaces.
- Storage and logging are local runtime concerns and are excluded from the public snapshot when they contain generated user data.

## Public contracts

- CLI arguments and text-mode output are exercised by the application pipeline tests.
- Web GUI state, settings, and local browser behavior are covered by Web GUI contract tests and the offline E2E suite.
- Plugin bridge request bounds, loopback binding, and token-auth behavior are covered by bridge tests.

## Verification

Run the commands in `QUALITY_GATES.md` from this directory. Those checks are
offline/static or test evidence only; they do not prove clean-machine
installation, real microphone capture, model availability, or publication
acceptance.
