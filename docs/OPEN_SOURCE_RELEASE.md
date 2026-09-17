# Open-Source Release Checklist

> This file is the public-facing release summary for this snapshot. Internal
> release reports and governance receipts remain outside the snapshot.

This project is released under Apache-2.0 for the project code. The release
scope is currently Windows 10/11 only.

## Before publishing

- Confirm `LICENSE` is present and the copyright holder wording is correct.
- Keep dependency and model licenses separate from the project license.
- Do not commit `.env` files, credentials, API keys, tokens, passwords, or
  private endpoint configuration.
- Do not commit recordings, SQLite databases, runtime logs, browser profiles,
  model caches, model weights, build directories, or generated installers.
- Review tracked Markdown, JSON, YAML, and PowerShell files for personal paths,
  desktop shortcuts, machine names, and local cache locations.
- Keep internal governance receipts, handoff packages, and private evaluation
  artifacts outside the public source distribution.
- Re-run the commands listed in `QUALITY_GATES.md` from this snapshot root after cleanup.

## Platform support

The product core is Python-based and local-first. The current desktop
integration is Windows-specific: global hotkeys, foreground-window discovery,
window activation, and paste injection use Windows-oriented behavior.

macOS contributions should add a platform adapter rather than changing the
core ASR/LLM pipeline. A complete contribution should document microphone and
Accessibility permissions, target-application behavior, Apple Silicon/Intel
coverage, packaging, and end-to-end verification. Until that evidence exists,
macOS remains community work in progress and is not an official supported
platform.

## Suggested public repository contents

Keep source code, tests, configuration templates, examples, documentation,
and reproducible offline checks. Exclude local evidence and machine-specific
artifacts even when they are useful during private development.
