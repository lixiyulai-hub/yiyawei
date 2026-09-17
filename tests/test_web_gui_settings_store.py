from __future__ import annotations

from src.gui.web.settings_store import WebGuiSettingsStore


def test_web_gui_settings_store_defaults_when_missing(tmp_path):
    store = WebGuiSettingsStore(tmp_path / "web_gui_settings.log")

    assert store.load() == {}


def test_web_gui_settings_store_round_trips_toggles(tmp_path):
    path = tmp_path / "web_gui_settings.log"
    store = WebGuiSettingsStore(path)

    store.save(use_fast=False, intelligent_output=False)

    assert WebGuiSettingsStore(path).load() == {
        "useFast": False,
        "intelligentOutput": False,
    }
