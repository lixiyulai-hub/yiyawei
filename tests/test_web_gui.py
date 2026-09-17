from __future__ import annotations

import json
import re
import subprocess
import textwrap
from pathlib import Path

from src.gui.web_gui import ASSETS_DIR, WebGuiController
from src.utils import window_style


CSS_IMPORT_RE = re.compile(
    r'^@import url\("(?P<href>\./css/[a-z-]+\.css)"\);\n',
    re.MULTILINE,
)


def _read_logical_css() -> str:
    entry_path = Path(ASSETS_DIR / "styles.css")
    entry = entry_path.read_text(encoding="utf-8")

    def expand_import(match: re.Match[str]) -> str:
        return (entry_path.parent / match.group("href")).read_text(encoding="utf-8")

    return CSS_IMPORT_RE.sub(expand_import, entry)


class FakeLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def exception(self, *args, **kwargs):
        pass


class FakeRecorder:
    sample_rate = 16000

    def close(self):
        pass


class FakeApp:
    default_mode = "cursor_prompt"
    output_cfg = {"script": "simplified"}
    config = {
        "hotkeys": {"gui_toggle": "ctrl+."},
        "recorder": {"auto_stop": {"enabled": False}},
    }
    logger = FakeLogger()
    recorder = FakeRecorder()
    _asr_warm_done = True
    injector_cfg = {"restore_clipboard": True, "paste_delay_ms": 0}
    confirm_calls = []

    def warm_asr(self):
        self._asr_warm_done = True

    def warm_fast_llm(self):
        pass

    def process_audio(self, audio, **kwargs):
        self.last_process_audio_kwargs = kwargs
        return {
            "record_id": 44,
            "pasted": bool(kwargs.get("allow_paste")),
            "debug": {
                "raw_asr_text": "我想做一张电商主图",
                "final_text": "作图提示词：请生成电商主图",
                "asr_model": "fake-asr",
                "asr_device": "cpu",
                "llm_model": "fake-llm",
                "asr_elapsed_ms": 1,
                "llm_elapsed_ms": 2,
                "risk_level": "low",
            },
        }

    def confirm_edit(self, **kwargs):
        self.confirm_calls.append(kwargs)
        return {
            "ok": True,
            "edit_id": len(self.confirm_calls),
            "learned_rules": [{"pattern": "EMG二点零", "replacement": "image 2.0"}],
        }


def test_web_gui_bootstrap_contains_modes_scripts_and_hotkey():
    controller = WebGuiController(FakeApp())
    data = controller.bootstrap()

    assert data["hotkey"] == "ctrl+."
    assert {"value": "cursor_prompt", "label": "AI 任务需求"} in data["modes"]
    assert {"value": "simplified", "label": "简体中文"} in data["scripts"]
    assert data["state"]["phase"] == "warming"
    assert data["state"]["mode"] == "cursor_prompt"


def test_web_gui_assets_include_white_glass_shell():
    index = Path(ASSETS_DIR / "index.html")
    styles = Path(ASSETS_DIR / "styles.css")
    script = Path(ASSETS_DIR / "main.js")
    api_client = Path(ASSETS_DIR / "js" / "api-client.js")
    custom_select = Path(ASSETS_DIR / "js" / "custom-select.js")
    editor_controller = Path(ASSETS_DIR / "js" / "editor-controller.js")
    settings_controller = Path(ASSETS_DIR / "js" / "settings-controller.js")
    theme_manager = Path(ASSETS_DIR / "js" / "theme-manager.js")

    assert index.exists()
    assert styles.exists()
    assert script.exists()
    assert api_client.exists()
    assert custom_select.exists()
    assert editor_controller.exists()
    assert settings_controller.exists()
    assert theme_manager.exists()
    assert not (ASSETS_DIR / "app.js").exists()

    css = _read_logical_css()
    assert "backdrop-filter" in css
    assert "rgba(255, 255, 255" in css
    assert ".record-orb" in css
    assert ".window-glass" in css
    assert ".mac-titlebar" in css


def test_web_gui_uses_generated_microphone_app_icon():
    index = Path(ASSETS_DIR / "index.html").read_text(encoding="utf-8")

    assert '<link rel="icon" href="/app-icon.ico" sizes="any" />' in index
    assert '<link rel="icon" href="/app-icon.png" type="image/png" />' in index
    assert '<link rel="apple-touch-icon" href="/app-icon.png" />' in index
    assert (ASSETS_DIR / "app-icon.ico").exists()
    assert (ASSETS_DIR / "app-icon.png").exists()


def test_web_gui_assets_include_50_theme_picker_options_and_auto_random():
    index = Path(ASSETS_DIR / "index.html").read_text(encoding="utf-8")
    styles = _read_logical_css()
    script = Path(ASSETS_DIR / "main.js").read_text(encoding="utf-8")
    catalog = Path(ASSETS_DIR / "js" / "theme-catalog.js").read_text(encoding="utf-8")
    manager = Path(ASSETS_DIR / "js" / "theme-manager.js").read_text(encoding="utf-8")

    assert 'name="theme-color"' in index
    assert 'id="themeSelect"' in index
    assert 'id="themeSwatches"' in index
    assert '<script type="module" src="/main.js"></script>' in index
    assert index.count("<script") == 1
    assert "/app.js" not in index
    assert 'import { createThemeManager } from "./js/theme-manager.js";' in script
    assert 'from "./theme-catalog.js";' in manager
    assert "const themes = [" in catalog
    assert catalog.count('id: "') == 50
    assert 'const AUTO_THEME_ID = "auto-random"' in catalog
    assert "const AUTO_THEME_INTERVAL_MS = 30000" in catalog
    assert "const CURRENT_THEME_STORAGE_VERSION = \"3\"" in catalog
    assert "THEME_STORAGE_VERSION_KEY" in catalog
    assert "persistThemePreference(AUTO_THEME_ID)" in manager
    assert "随机流光 · 30秒" in catalog
    assert "startAutoTheme" in manager
    assert "stopAutoTheme" in manager
    assert "applyRandomTheme" in manager
    assert "windowRef.setInterval(applyRandomTheme, AUTO_THEME_INTERVAL_MS)" in manager
    assert "银白霜璃" in catalog
    assert "雾粉白" in catalog
    assert "薄荷水光" in catalog
    assert "珊瑚晴空" in catalog
    assert "晨雾靛蓝" in catalog
    assert "棱镜白" in catalog
    assert "暗夜青渊" not in catalog
    assert "极地黑" not in catalog
    assert 'contrast: "dark"' not in catalog
    assert catalog.count("chrome:") >= 50
    assert "/api/theme" in manager
    assert "setTimeout" in manager
    assert "localStorage" in manager
    assert "documentRef.documentElement.dataset.contrast" in manager
    assert styles.count('[data-theme="') >= 50
    assert "--control-ink" in styles
    assert '[data-contrast="dark"]' not in styles
    assert '[data-theme="moonlight-indigo"]' in styles
    assert '[data-theme="obsidian-light"]' in styles
    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" in styles


def test_web_gui_assets_include_mac_glass_window_structure():
    index = Path(ASSETS_DIR / "index.html").read_text(encoding="utf-8")
    styles = _read_logical_css()

    assert 'class="window-glass"' in index
    assert 'class="mac-titlebar"' in index
    titlebar = index.split('<header class="mac-titlebar">', 1)[1].split("</header>", 1)[0]
    control_strip = index.split('<section class="control-strip"', 1)[1].split("</section>", 1)[0]
    assert 'id="statusPill"' in titlebar
    assert 'id="fastSwitch"' in titlebar
    assert 'id="fastSwitch"' not in control_strip
    assert "traffic-light" not in index
    assert "Yiyawei - 咿呀喂" in index
    assert 'class="info-strip"' in index
    assert 'class="result-section"' in index
    assert "识别原文" in index
    assert "最终输出" in index
    assert "grid-template-rows: 50px 66px 88px 62px minmax(126px, 1fr);" in styles
    assert "overflow: hidden;" in styles
    assert ">对照<" not in index
    assert ".info-strip" in styles


def test_web_gui_record_stage_has_shine_border_variant_c_active():
    index = Path(ASSETS_DIR / "index.html").read_text(encoding="utf-8")
    styles = _read_logical_css()

    assert 'class="record-stage shine-border-card"' in index
    assert 'class="shine-border-layer"' in index
    assert 'class="spotlight-layer"' in index
    assert 'class="edge-light"' in index
    assert ".record-stage > .shine-border-layer" in styles
    assert ".record-stage.shine-border-card" in styles
    assert "@keyframes shine-border-spin" in styles
    assert "conic-gradient" in styles
    assert "mask-composite: exclude" in styles


def test_web_gui_warming_state_keeps_record_controls_with_loading_label():
    index = Path(ASSETS_DIR / "index.html").read_text(encoding="utf-8")
    styles = _read_logical_css()
    renderer = Path(ASSETS_DIR / "js" / "state-renderer.js").read_text(
        encoding="utf-8"
    )

    assert 'class="loading-banner"' not in index
    assert 'class="loading-wordmark"' not in index
    assert "Please wait a moment" not in index
    assert 'class="record-stage shine-border-card"' in index
    assert 'id="recordButton"' in index
    assert 'id="recordTitle"' in index
    assert 'id="recordSubtitle"' in index
    assert 'classList.toggle("warming", state.phase === "warming")' in renderer
    assert 'recordTitle.textContent = "加载中"' in renderer
    assert 'recordButton.disabled = state.phase === "processing" || state.phase === "warming"' in renderer
    assert ".record-stage.warming .audio-capsule-canvas" in styles
    assert ".record-stage.warming .stage-state" not in styles
    assert ".record-stage.warming .record-orb" not in styles
    assert ".record-stage.warming .stage-time" not in styles
    assert "@keyframes loadingSweep" not in styles


def test_web_gui_recording_wave_follows_voice_level():
    styles = _read_logical_css()
    script = Path(ASSETS_DIR / "main.js").read_text(encoding="utf-8")
    visualizer = Path(ASSETS_DIR / "js" / "audio-visualizer.js").read_text(encoding="utf-8")
    renderer = Path(ASSETS_DIR / "js" / "state-renderer.js").read_text(
        encoding="utf-8"
    )

    assert 'import { createAudioCapsuleVisualizer } from "./js/audio-visualizer.js";' in script
    assert 'import { mapVoiceLevel } from "./audio-visualizer.js";' in renderer
    assert "function mapVoiceLevel(rawLevel)" in visualizer
    assert "function createAudioCapsuleVisualizer(canvas, host)" in visualizer
    assert "requestAnimationFrame(animate);" in visualizer
    assert "function mapVoiceLevel(rawLevel)" not in script
    assert "function createAudioCapsuleVisualizer(canvas, host)" not in script
    assert 'recordStage.style.setProperty("--voice-level", voiceLevel.toFixed(3))' in renderer
    assert "const voiceLevel = mapVoiceLevel(state.level);" in renderer
    assert 'recordStage.style.setProperty("--audio-capsule-level", voiceLevel.toFixed(3))' in renderer
    assert "audioCapsuleVisualizer.update({ level: voiceLevel, phase: state.phase });" in renderer
    flow = [
        "const voiceLevel = mapVoiceLevel(state.level);",
        'recordStage.style.setProperty("--voice-level", voiceLevel.toFixed(3))',
        'recordStage.style.setProperty("--audio-capsule-level", voiceLevel.toFixed(3))',
        "audioCapsuleVisualizer.update({ level: voiceLevel, phase: state.phase });",
    ]
    assert [renderer.index(statement) for statement in flow] == sorted(
        renderer.index(statement) for statement in flow
    )
    assert "--wave-1: calc(7px + var(--voice-level) * 13px);" in styles
    assert "--wave-4: calc(13px + var(--voice-level) * 24px);" in styles
    assert "height: var(--wave-1);" in styles
    assert "height: var(--wave-4);" in styles
    assert "--meter-4: calc(18px + var(--voice-level) * 28px);" in styles
    assert ".meter span:nth-child(4) { height: var(--meter-4);" in styles
    assert "@keyframes voice-breathe" in styles
    assert ".record-stage.recording .mini-wave i" in styles
    assert "animation: voice-breathe 720ms ease-in-out infinite;" in styles
    assert "calc(0.62 + var(--voice-level) * 0.38)" in styles


def test_web_gui_record_stage_keeps_variant_b_spotlight_available():
    styles = _read_logical_css()
    script = Path(ASSETS_DIR / "main.js").read_text(encoding="utf-8")
    visualizer = Path(ASSETS_DIR / "js" / "audio-visualizer.js").read_text(encoding="utf-8")

    assert ".record-stage.spotlight-card:hover" in styles
    assert ".record-stage > .spotlight-layer" in styles
    assert "--spotlight-x" in styles
    assert "--spotlight-y" in styles
    assert "--spotlight-opacity" in styles
    assert "function updateRecordSpotlight" in visualizer
    assert 'addEventListener("pointermove"' not in script
    assert 'addEventListener("pointermove"' not in visualizer


def test_web_gui_record_stage_keeps_variant_a_border_glow_available():
    styles = _read_logical_css()
    script = Path(ASSETS_DIR / "main.js").read_text(encoding="utf-8")
    visualizer = Path(ASSETS_DIR / "js" / "audio-visualizer.js").read_text(encoding="utf-8")

    assert ".record-stage > .edge-light" in styles
    assert "--cursor-angle" in styles
    assert "--edge-fill-opacity" not in styles
    assert ".record-stage.border-glow-card::after" not in styles
    assert "function updateRecordGlow" in visualizer
    assert "--edge-fill-opacity" not in visualizer
    assert 'addEventListener("pointermove"' not in script


def test_web_gui_record_button_uses_svg_microphone_icon():
    index = Path(ASSETS_DIR / "index.html").read_text(encoding="utf-8")
    styles = _read_logical_css()

    assert '<svg class="mic-icon"' in index
    assert 'class="mic-capsule"' in index
    assert 'class="mic-yoke"' in index
    assert 'class="mic-stem"' in index
    assert 'class="mic-base"' in index
    assert ".mic-icon::before" not in styles
    assert ".mic-icon::after" not in styles


def test_web_gui_record_button_uses_neumorphic_press_effect():
    styles = _read_logical_css()

    assert ".record-orb:active" in styles
    assert "6px 6px 14px rgba(197, 197, 197" in styles
    assert "-6px -6px 14px rgba(255, 255, 255" in styles
    assert "inset 4px 4px 12px rgba(197, 197, 197" in styles
    assert ".record-orb:active .orb-core" in styles


def test_web_gui_fast_switch_uses_elastic_neumorphic_style_and_settings_controller():
    index = Path(ASSETS_DIR / "index.html").read_text(encoding="utf-8")
    styles = _read_logical_css()
    script = Path(ASSETS_DIR / "main.js").read_text(encoding="utf-8")
    settings = Path(ASSETS_DIR / "js" / "settings-controller.js").read_text(encoding="utf-8")
    renderer = Path(ASSETS_DIR / "js" / "state-renderer.js").read_text(
        encoding="utf-8"
    )
    recording = Path(ASSETS_DIR / "js" / "recording-controller.js").read_text(
        encoding="utf-8"
    )

    assert "快速模式" in index
    assert 'id="fastModeLabel"' in index
    assert 'class="check"' in index
    assert 'class="switch-face"' in index
    assert 'id="fastSwitch"' in index
    assert "智能输出" in index
    assert 'id="intelligentOutputLabel"' in index
    assert 'id="intelligentOutputSwitch"' in index
    assert index.index('id="intelligentOutputSwitch"') < index.index('id="fastSwitch"')
    assert "cubic-bezier(0.85, 0.05, 0.18, 1.35)" in styles
    assert "transform: translate3d(-75%, 0, 0)" in styles
    assert "transform: translate3d(25%, 0, 0)" in styles
    assert "-6px -3px 8px 0 rgba(255, 255, 255" in styles
    assert "6px 4px 11px 0 rgba(209, 217, 230" in styles
    assert '.check input[type="checkbox"]:checked' in styles
    assert '.check input[type="checkbox"]:checked ~ .switch-face' in styles
    assert ".check .switch-face::before" not in styles
    assert ".check .switch-face::after" not in styles
    assert 'import { createSettingsController } from "./js/settings-controller.js";' in script
    assert "const settingsController = createSettingsController({" in script
    assert "settingsController.applyState(state);" in renderer
    assert "JSON.stringify(getSettingsPayload())" in recording
    assert "getSettingsPayload: () => settingsController.getPayload()" in script
    assert "settingsController.bind();" in script
    assert "function applyFastModeLabel" not in script
    assert "function syncSettings" not in script
    assert "/api/settings" not in script
    assert 'refs.modeSelect.addEventListener("change", syncSettings)' not in script
    assert 'refs.scriptSelect.addEventListener("change", syncSettings)' not in script
    assert 'refs.fastSwitch.addEventListener("change", () =>' not in script

    assert "export function createSettingsController" in settings
    assert "function applyFastModeLabel" in settings
    assert "function applyIntelligentOutputLabel" in settings
    assert 'enabled ? "智能输出" : "关闭智能"' in settings
    assert "稳定模式" in settings
    assert "快速模式" in settings
    assert "function getPayload" in settings
    assert "function applySettingsState" in settings
    assert "function syncSettings" in settings
    assert 'api("/api/settings"' in settings
    assert 'modeSelect.addEventListener("change", syncSettings)' in settings
    assert 'scriptSelect.addEventListener("change", syncSettings)' in settings
    assert 'fastSwitch.addEventListener("change", () =>' in settings
    assert 'intelligentOutputSwitch.addEventListener("change", () =>' in settings
    assert "applyIntelligentOutputLabel(intelligentOutputSwitch.checked)" in settings


def test_web_gui_uses_extracted_api_client_without_changing_endpoint_calls():
    script = Path(ASSETS_DIR / "main.js").read_text(encoding="utf-8")
    api_client = Path(ASSETS_DIR / "js" / "api-client.js").read_text(encoding="utf-8")
    theme_manager = Path(ASSETS_DIR / "js" / "theme-manager.js").read_text(encoding="utf-8")
    recording = Path(ASSETS_DIR / "js" / "recording-controller.js").read_text(
        encoding="utf-8"
    )

    assert 'import { createApiClient } from "./js/api-client.js";' in script
    assert "const api = createApiClient();" in script
    assert "async function api(" not in script
    assert "export function createApiClient" in api_client
    assert 'headers: { "Content-Type": "application/json" }' in api_client
    assert "...options" in api_client
    assert "throw new ApiError(response, path);" in api_client
    assert "super(`${response.status} ${response.statusText}`);" in api_client
    assert "return response.json();" in api_client
    assert 'api("/api/bootstrap")' in script
    assert 'api("/api/theme",' in theme_manager
    for endpoint in ("/api/toggle", "/api/state"):
        assert f'api("{endpoint}"' in recording
    assert "/api/confirm" not in script
    assert 'api("/api/confirm"' in Path(
        ASSETS_DIR / "js" / "editor-controller.js"
    ).read_text(encoding="utf-8")


def test_web_gui_selects_use_custom_neumorphic_dropdown_shell():
    styles = _read_logical_css()
    script = Path(ASSETS_DIR / "main.js").read_text(encoding="utf-8")
    custom_select = Path(ASSETS_DIR / "js" / "custom-select.js").read_text(encoding="utf-8")

    assert ".select-shell" in styles
    assert ".select-trigger" in styles
    assert ".select-menu" in styles
    assert ".select-option" in styles
    assert ".native-select" in styles
    assert "4px 2px 16px 0 rgba(var(--accent-rgb)" in styles
    assert "10px 12px 30px rgba(var(--accent-rgb)" in styles
    assert 'setAttribute("role", "combobox")' in custom_select
    assert "function ensure(" in custom_select
    assert "function rebuild(" in custom_select
    assert "customSelectManager.ensure(refs.modeSelect)" in script
    assert "customSelectManager.ensure(refs.scriptSelect)" in script
    assert "customSelectManager.ensure(themeSelect" in Path(
        ASSETS_DIR / "js" / "theme-manager.js"
    ).read_text(encoding="utf-8")
    assert "function closeAll(" in custom_select


def test_web_gui_result_panes_have_shine_border_effect():
    styles = _read_logical_css()

    assert ".text-pane::after" in styles
    assert "--result-shine-width" in styles
    assert "conic-gradient(" in styles
    assert "@property --result-shine-angle" in styles
    assert "@keyframes result-shine-border" in styles
    assert "mask-composite: exclude" in styles
    assert ".text-pane.featured::after" in styles


def test_web_gui_assets_include_confirm_restore_edit_flow():
    index = Path(ASSETS_DIR / "index.html").read_text(encoding="utf-8")
    styles = _read_logical_css()
    script = Path(ASSETS_DIR / "main.js").read_text(encoding="utf-8")
    editor = Path(ASSETS_DIR / "js" / "editor-controller.js").read_text(encoding="utf-8")
    state_machine = Path(ASSETS_DIR / "js" / "state-machine.js").read_text(
        encoding="utf-8"
    )
    renderer = Path(ASSETS_DIR / "js" / "state-renderer.js").read_text(
        encoding="utf-8"
    )

    assert 'id="rawText" placeholder=' in index
    assert 'id="finalText" placeholder=' in index
    assert 'readonly' not in index
    assert 'id="rawRestoreTextButton"' in index
    assert 'id="rawConfirmTextButton"' in index
    assert 'id="finalRestoreTextButton"' in index
    assert 'id="finalConfirmTextButton"' in index
    assert 'id="rawEditState"' in index
    assert 'id="finalEditState"' in index
    assert 'id="confirmDialog"' in index
    assert 'id="confirmDialogTitle"' in index
    assert 'id="confirmDialogMessage"' in index
    assert "确认使用当前修改" in index
    assert "识别原文编辑操作" in index
    assert ".pane-action.confirm.is-dirty" in styles
    assert "min-width: 38px;" in styles
    assert "height: 22px;" in styles
    assert ".confirm-dialog" in styles
    assert "color: #223047" in styles
    assert "color: #17233a" in styles
    assert "color: #506079" in styles
    assert ".dialog-actions" in styles
    assert 'import { createEditorController } from "./js/editor-controller.js";' in script
    assert "const editorController = createEditorController({" in script
    assert "applyState," in script
    assert "getCurrentPhase: () => stateMachine.getCurrentPhase()" in script
    assert "editorController.applyState(state);" in renderer
    assert "editorController.bind();" in script
    assert state_machine.index("currentPhase = state.phase;") < state_machine.index(
        "renderer(state);"
    )

    assert "export function createEditorController" in editor
    assert "function refreshEditControls" in editor
    assert "function markRawTextDirty" in editor
    assert "function markFinalTextDirty" in editor
    assert "function restoreRawTextSnapshot" in editor
    assert "function restoreFinalTextSnapshot" in editor
    assert "function confirmEditedText" in editor
    assert 'openConfirmDialog("raw")' in editor
    assert 'openConfirmDialog("final")' in editor
    assert "baseRawText: textSnapshot.rawText" in editor
    assert "baseFinalText: textSnapshot.finalText" in editor
    assert "确认后会保存这次 ASR 识别修正" in editor
    assert 'api("/api/confirm"' in editor
    assert "throw new Error(result.error" in editor
    assert "window.confirm(confirmDialogMessage.textContent)" in editor
    assert "if (bound) return;" in editor

    for residue in (
        "let textSnapshot",
        "let rawTextDirty",
        "let finalTextDirty",
        "let pendingConfirmScope",
        "function refreshEditControls",
        "function setRawEditDirty",
        "function setFinalEditDirty",
        "function applyTextState",
        "function markRawTextDirty",
        "function markFinalTextDirty",
        "function restoreRawTextSnapshot",
        "function restoreFinalTextSnapshot",
        "function openConfirmDialog",
        "function confirmEditedText",
        'refs.rawText.addEventListener("input"',
        'refs.finalText.addEventListener("input"',
        'refs.rawRestoreTextButton.addEventListener("click"',
        'refs.rawConfirmTextButton.addEventListener("click"',
        'refs.finalRestoreTextButton.addEventListener("click"',
        'refs.finalConfirmTextButton.addEventListener("click"',
        'refs.confirmDialog.addEventListener("close"',
    ):
        assert residue not in script


def test_editor_controller_imports_without_a_dom_in_node():
    module_url = (ASSETS_DIR / "js" / "editor-controller.js").resolve().as_uri()
    program = textwrap.dedent(
        f"""
        const loaded = await import({json.dumps(module_url)});
        if (typeof loaded.createEditorController !== "function") process.exit(2);
        process.stdout.write("ok");
        """
    )

    result = subprocess.run(
        ["node", "--input-type=module", "--eval", program],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.stdout == "ok"
    assert result.stderr == ""


def test_editor_controller_node_stub_preserves_edit_and_confirm_contract():
    module_url = (ASSETS_DIR / "js" / "editor-controller.js").resolve().as_uri()
    program = textwrap.dedent(
        f"""
        import assert from "node:assert/strict";
        const {{ createEditorController }} = await import({json.dumps(module_url)});

        function fakeElement(initial = {{}}) {{
          const listeners = new Map();
          const classes = new Set();
          return {{
            value: "",
            textContent: "",
            className: "",
            disabled: false,
            returnValue: "",
            ...initial,
            classList: {{
              toggle(name, enabled) {{
                if (enabled) classes.add(name);
                else classes.delete(name);
              }},
              contains(name) {{ return classes.has(name); }},
            }},
            addEventListener(type, listener) {{
              const registered = listeners.get(type) || [];
              registered.push(listener);
              listeners.set(type, registered);
            }},
            dispatch(type) {{
              for (const listener of listeners.get(type) || []) listener({{ type, target: this }});
            }},
            listenerCount(type) {{ return (listeners.get(type) || []).length; }},
          }};
        }}

        let dialogOpenCount = 0;
        const elements = {{
          rawText: fakeElement(),
          finalText: fakeElement(),
          rawEditState: fakeElement(),
          finalEditState: fakeElement(),
          rawRestoreTextButton: fakeElement(),
          rawConfirmTextButton: fakeElement(),
          finalRestoreTextButton: fakeElement(),
          finalConfirmTextButton: fakeElement(),
          confirmDialog: fakeElement({{ showModal() {{ dialogOpenCount += 1; }} }}),
          confirmDialogTitle: fakeElement(),
          confirmDialogMessage: fakeElement(),
          statusText: fakeElement(),
          statusPill: fakeElement(),
        }};
        const calls = [];
        let response;
        const api = async (path, options) => {{
          calls.push({{ path, options }});
          return response;
        }};
        let currentPhase = "done";
        let controller;
        const renderState = (state) => {{
          currentPhase = state.phase;
          controller.applyState(state);
        }};
        controller = createEditorController({{
          elements,
          api,
          applyState: renderState,
          getCurrentPhase: () => currentPhase,
        }});
        const initial = {{
          phase: "done",
          rawText: "raw base",
          finalText: "final base",
          recordId: "record-9",
          updatedAt: 1,
        }};
        controller.applyState(initial);
        controller.bind();
        controller.bind();

        for (const [element, type] of [
          [elements.rawText, "input"],
          [elements.finalText, "input"],
          [elements.rawRestoreTextButton, "click"],
          [elements.rawConfirmTextButton, "click"],
          [elements.finalRestoreTextButton, "click"],
          [elements.finalConfirmTextButton, "click"],
          [elements.confirmDialog, "close"],
        ]) assert.equal(element.listenerCount(type), 1);

        elements.rawText.value = "temporary raw edit";
        elements.rawText.dispatch("input");
        assert.equal(elements.rawEditState.textContent, "已修改");
        assert.equal(elements.rawRestoreTextButton.disabled, false);
        assert.equal(elements.rawConfirmTextButton.disabled, false);
        assert.equal(elements.rawConfirmTextButton.classList.contains("is-dirty"), true);
        elements.rawRestoreTextButton.dispatch("click");
        assert.equal(elements.rawText.value, "raw base");
        assert.equal(elements.rawEditState.textContent, "ASR");
        assert.equal(elements.rawRestoreTextButton.disabled, true);

        elements.rawText.value = "confirmed raw edit";
        elements.rawText.dispatch("input");
        response = {{
          ok: true,
          pasted: false,
          state: {{ ...initial, rawText: "confirmed raw edit", updatedAt: 2 }},
        }};
        elements.rawConfirmTextButton.dispatch("click");
        assert.equal(dialogOpenCount, 1);
        assert.equal(elements.confirmDialogTitle.textContent, "确认识别原文修改？");
        elements.confirmDialog.returnValue = "yes";
        elements.confirmDialog.dispatch("close");
        await new Promise((resolve) => setImmediate(resolve));

        assert.equal(calls.length, 1);
        assert.equal(calls[0].path, "/api/confirm");
        assert.equal(calls[0].options.method, "POST");
        assert.deepEqual(JSON.parse(calls[0].options.body), {{
          scope: "raw",
          recordId: "record-9",
          rawText: "confirmed raw edit",
          finalText: "final base",
          baseRawText: "raw base",
          baseFinalText: "final base",
        }});
        assert.equal(elements.rawEditState.textContent, "已保存");
        assert.equal(elements.rawRestoreTextButton.disabled, true);
        assert.equal(elements.rawConfirmTextButton.disabled, true);
        assert.equal(elements.rawConfirmTextButton.classList.contains("is-dirty"), false);
        controller.applyState({{ ...response.state, updatedAt: 3 }});
        assert.equal(elements.rawEditState.textContent, "已保存");

        elements.finalText.value = "stale final edit";
        elements.finalText.dispatch("input");
        response = {{ ok: false, error: "stale base" }};
        elements.finalConfirmTextButton.dispatch("click");
        assert.equal(dialogOpenCount, 2);
        elements.confirmDialog.returnValue = "yes";
        elements.confirmDialog.dispatch("close");
        await new Promise((resolve) => setImmediate(resolve));

        assert.equal(calls.length, 2);
        assert.equal(elements.finalEditState.textContent, "确认失败");
        assert.equal(elements.statusText.textContent, "确认失败");
        assert.equal(elements.statusPill.className, "status-pill error");
        assert.equal(elements.finalConfirmTextButton.disabled, false);
        assert.equal(elements.finalRestoreTextButton.disabled, false);
        assert.equal(elements.finalConfirmTextButton.classList.contains("is-dirty"), true);
        """
    )

    result = subprocess.run(
        ["node", "--input-type=module", "--eval", program],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.stdout == ""
    assert result.stderr == ""


def test_web_gui_uses_compact_desktop_window_size():
    styles = _read_logical_css()

    assert "height: 100dvh;" in styles
    assert "min-height: 0;" in styles
    assert "width: 100vw;" in styles


def test_web_gui_update_settings_persists_processing_choices(tmp_path):
    class PersistedApp(FakeApp):
        def __init__(self) -> None:
            super().__init__()
            self.config["storage"] = {"log_dir": str(tmp_path)}
            self.warm_calls = 0

        def warm_fast_llm(self) -> None:
            self.warm_calls += 1

    app = PersistedApp()
    controller = WebGuiController(app)

    result = controller.update_settings(
        {
            "mode": "normal_dictation",
            "outputScript": "traditional",
            "useFast": False,
            "intelligentOutput": False,
        }
    )

    assert result["ok"] is True
    assert result["state"]["useFast"] is False
    assert result["state"]["intelligentOutput"] is False
    assert result["state"]["mode"] == "normal_dictation"
    assert result["state"]["outputScript"] == "traditional"
    assert controller.get_state()["useFast"] is False
    restored = WebGuiController(app)
    assert restored.get_state()["useFast"] is False
    assert restored.get_state()["intelligentOutput"] is False


def test_web_gui_confirm_text_saves_edits_before_paste(monkeypatch):
    app = FakeApp()
    app.confirm_calls = []
    controller = WebGuiController(app)
    controller.state.phase = "done"
    controller.state.raw_text = "请用EMG二点零生成图"
    controller.state.final_text = "作图提示词：请用EMG二点零生成图"
    controller.state.record_id = "42"
    controller.state.mode = "cursor_prompt"
    controller.state.output_script = "simplified"
    pasted = {}

    def fake_paste_text(text, restore_clipboard=True, delay_ms=0, target_hwnd=None):
        pasted["text"] = text
        pasted["target_hwnd"] = target_hwnd
        return True

    monkeypatch.setattr("src.gui.web_gui.paste_text", fake_paste_text)

    result = controller.confirm_text(
        {
            "recordId": "42",
            "rawText": "请用image 2.0生成图",
            "finalText": "作图提示词：请用image 2.0生成图",
            "baseFinalText": "作图提示词：请用EMG二点零生成图",
        }
    )

    assert result["ok"] is True
    assert result["pasted"] is True
    assert pasted["text"] == "作图提示词：请用image 2.0生成图"
    assert controller.state.status == "已确认并粘贴"
    assert len(app.confirm_calls) == 2
    assert app.confirm_calls[0]["source_kind"] == "asr_text"
    assert app.confirm_calls[1]["source_kind"] == "final_output"
    assert app.confirm_calls[0]["record_id"] == 42


def test_web_gui_confirm_raw_text_saves_asr_correction_without_paste(monkeypatch):
    app = FakeApp()
    app.confirm_calls = []
    controller = WebGuiController(app)
    controller.state.phase = "done"
    controller.state.raw_text = "我想用EMG二点零"
    controller.state.final_text = "作图提示词：我想用EMG二点零"
    controller.state.record_id = "43"
    pasted = {"called": False}

    def fake_paste_text(*args, **kwargs):
        pasted["called"] = True
        return True

    monkeypatch.setattr("src.gui.web_gui.paste_text", fake_paste_text)

    result = controller.confirm_text(
        {
            "scope": "raw",
            "recordId": "43",
            "rawText": "我想用 image 2.0",
            "finalText": "作图提示词：我想用EMG二点零",
            "baseRawText": "我想用EMG二点零",
        }
    )

    assert result["ok"] is True
    assert result["scope"] == "raw"
    assert result["pasted"] is False
    assert pasted["called"] is False
    assert controller.state.raw_text == "我想用 image 2.0"
    assert controller.state.final_text == "作图提示词：我想用EMG二点零"
    assert controller.state.status == "已保存识别修正"
    assert len(app.confirm_calls) == 1
    assert app.confirm_calls[0]["source_kind"] == "asr_text"
    assert app.confirm_calls[0]["before_text"] == "我想用EMG二点零"
    assert app.confirm_calls[0]["after_text"] == "我想用 image 2.0"


def test_web_gui_confirm_text_passes_last_debug_to_confirm_edit(monkeypatch):
    app = FakeApp()
    app.confirm_calls = []
    controller = WebGuiController(app)
    controller.state.phase = "done"
    controller.state.raw_text = "之前可以自动粘贴，现在没有这个功能了"
    controller.state.final_text = "请优化语音指令编译器。"
    controller.state.record_id = "45"
    controller._last_debug = {
        "raw_asr_text": "之前可以自动粘贴，现在没有这个功能了",
        "cleaned_text": "之前可以自动粘贴，现在没有这个功能了",
        "final_text": "请优化语音指令编译器。",
        "route": {"task_type": "bug_report"},
        "intent_frame": {"artifact_type": "software_feedback", "task_hint": "bug_report"},
        "quality_gate_attribution": {"stage": "software_feedback_guard"},
    }

    monkeypatch.setattr("src.gui.web_gui.paste_text", lambda *args, **kwargs: True)

    result = controller.confirm_text(
        {
            "scope": "final",
            "recordId": "45",
            "rawText": "之前可以自动粘贴，现在没有这个功能了",
            "finalText": "请修复自动粘贴到目标界面失败的问题。",
            "baseFinalText": "请优化语音指令编译器。",
        }
    )

    assert result["ok"] is True
    assert len(app.confirm_calls) == 1
    metadata = app.confirm_calls[0]["metadata"]
    assert metadata["source"] == "web_gui"
    assert metadata["debug"]["route"]["task_type"] == "bug_report"
    assert metadata["debug"]["intent_frame"]["artifact_type"] == "software_feedback"


def test_web_gui_process_audio_allows_auto_paste_and_marks_pasted():
    app = FakeApp()
    controller = WebGuiController(app)
    controller._browser_hwnd = 456
    restored = []

    def fake_show_window_no_activate(hwnd):
        restored.append(hwnd)
        return True

    from src.gui import web_gui as web_gui_module

    original_show = web_gui_module.show_window_no_activate
    web_gui_module.show_window_no_activate = fake_show_window_no_activate

    try:
        controller._process_audio(
            audio=b"fake",
            mode="cursor_prompt",
            use_fast=False,
            intelligent_output=True,
            target_hwnd=123,
            output_script="simplified",
        )
    finally:
        web_gui_module.show_window_no_activate = original_show

    assert app.last_process_audio_kwargs["allow_paste"] is True
    assert app.last_process_audio_kwargs["paste_hwnd"] == 123
    assert controller.state.status == "已粘贴"
    assert controller.state.pasted is True
    assert controller.state.final_text == "作图提示词：请生成电商主图"
    assert restored == [456]


def test_web_gui_rejects_system_shell_windows_as_paste_targets(monkeypatch):
    controller = WebGuiController(FakeApp())

    monkeypatch.setattr("src.gui.web_gui.is_window", lambda hwnd: True)
    monkeypatch.setattr("src.gui.web_gui.get_window_process_id", lambda hwnd: 10)
    monkeypatch.setattr("src.gui.web_gui.get_process_name", lambda pid: "explorer.exe")

    assert controller._is_valid_target(123) is False


def test_web_gui_confirm_text_rejects_stale_base_final():
    controller = WebGuiController(FakeApp())
    controller.state.phase = "done"
    controller.state.final_text = "新输出"

    result = controller.confirm_text({"finalText": "用户改动", "baseFinalText": "旧输出"})

    assert result["ok"] is False
    assert "输出已变化" in result["error"]


def test_web_gui_theme_color_validation():
    controller = WebGuiController(FakeApp())

    assert controller.apply_theme_color({"color": "#ffecec"}) == {"ok": True}
    assert controller.apply_theme_color({"color": "red"})["ok"] is False


def test_window_style_exposes_title_based_browser_lookup():
    assert window_style.is_hex_color("#e4f6f4")
    assert not window_style.is_hex_color("#bad")
    assert callable(window_style.find_window_by_title_and_process)
