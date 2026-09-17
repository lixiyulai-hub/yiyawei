from __future__ import annotations

import re
from pathlib import Path

from src.gui.web_gui import ASSETS_DIR


CSS_DIR = Path(ASSETS_DIR / "css")
ENTRY_PATH = Path(ASSETS_DIR / "styles.css")
MODULE_NAMES = (
    "tokens.css",
    "themes.css",
    "base.css",
    "layout.css",
    "controls.css",
    "recording.css",
    "editor.css",
)
MODULE_MARKERS = {
    "tokens.css": ":root {",
    "themes.css": '[data-theme="silver-frost"] {',
    "base.css": "body::before,",
    "layout.css": ".status-pill.done .status-dot {",
    "controls.css": ".select-trigger {",
    "recording.css": ".record-stage > .shine-border-layer {",
    "editor.css": ".confirm-dialog {",
}
IMPORT_RE = re.compile(r'^@import url\("(?P<href>\./css/[^"\n]+)"\);$', re.MULTILINE)


def _read_modules() -> dict[str, str]:
    return {
        name: (CSS_DIR / name).read_text(encoding="utf-8")
        for name in MODULE_NAMES
    }


def _assert_balanced_delimiters(source: str) -> None:
    stack: list[str] = []
    opening = {"{", "(", "["}
    closing = {"}": "{", ")": "(", "]": "["}
    quote = ""
    escaped = False
    in_comment = False
    index = 0
    while index < len(source):
        current = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if in_comment:
            if current == "*" and following == "/":
                in_comment = False
                index += 2
                continue
        elif quote:
            if escaped:
                escaped = False
            elif current == "\\":
                escaped = True
            elif current == quote:
                quote = ""
        elif current == "/" and following == "*":
            in_comment = True
            index += 2
            continue
        elif current in {'"', "'"}:
            quote = current
        elif current in opening:
            stack.append(current)
        elif current in closing:
            assert stack and stack.pop() == closing[current]
        index += 1
    assert not in_comment
    assert not quote
    assert not stack


def test_styles_entry_imports_modules_in_order_before_responsive_rules() -> None:
    entry = ENTRY_PATH.read_text(encoding="utf-8")
    expected_hrefs = [f"./css/{name}" for name in MODULE_NAMES]
    expected_prelude = "".join(f'@import url("{href}");\n' for href in expected_hrefs)

    assert [match.group("href") for match in IMPORT_RE.finditer(entry)] == expected_hrefs
    assert entry.startswith(expected_prelude)
    assert entry[len(expected_prelude) :].startswith("@media (max-width: 720px) {")
    assert "@import" not in entry[len(expected_prelude) :]
    assert entry.count("@media") == 3
    assert entry.index("@media") > entry.rindex("@import")


def test_css_source_partition_has_expected_files_and_balanced_blocks() -> None:
    actual_module_names = {path.name for path in CSS_DIR.glob("*.css")}
    modules = _read_modules()
    entry = ENTRY_PATH.read_text(encoding="utf-8")

    assert actual_module_names == set(MODULE_NAMES)
    assert entry
    assert entry.endswith("\n")
    _assert_balanced_delimiters(entry)
    for name, source in modules.items():
        assert source
        assert source.endswith("\n")
        assert "@import" not in source
        _assert_balanced_delimiters(source)


def test_theme_count_and_key_selectors_have_unique_module_owners() -> None:
    modules = _read_modules()
    entry = ENTRY_PATH.read_text(encoding="utf-8")
    themes = modules["themes.css"]

    assert len(re.findall(r'^\[data-theme="[^"]+"\] \{$', themes, re.MULTILINE)) == 50
    for owner, marker in MODULE_MARKERS.items():
        assert modules[owner].count(marker) == 1
        assert marker not in entry
        assert all(marker not in source for name, source in modules.items() if name != owner)

    fragment_fill = 'fill: url("#micGradient");'
    assert modules["recording.css"].count(fragment_fill) == 1
    assert entry.count(fragment_fill) == 0
    assert sum(source.count(fragment_fill) for source in modules.values()) == 1
