from __future__ import annotations

import json
import os
import struct
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from conftest import GuiHarness


pytestmark = pytest.mark.e2e

BASELINE_DIR = Path(__file__).resolve().parent / "baselines"
SCREENSHOT_STYLE = """
  *, *::before, *::after {
    animation: none !important;
    transition: none !important;
    caret-color: transparent !important;
  }
  .audio-capsule-canvas { visibility: hidden !important; }
"""
CANVAS_PIXEL_SIGNATURE = """
(canvas) => {
  const context = canvas.getContext("2d", { alpha: true });
  const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
  let nonTransparent = 0;
  let nonZero = 0;
  let channelSum = 0;
  let hash = 2166136261;
  for (let index = 0; index < pixels.length; index += 4) {
    const red = pixels[index];
    const green = pixels[index + 1];
    const blue = pixels[index + 2];
    const alpha = pixels[index + 3];
    if (alpha !== 0) nonTransparent += 1;
    if (red !== 0 || green !== 0 || blue !== 0 || alpha !== 0) nonZero += 1;
    channelSum = (channelSum + red + green + blue + alpha) >>> 0;
    hash = Math.imul(hash ^ red, 16777619);
    hash = Math.imul(hash ^ green, 16777619);
    hash = Math.imul(hash ^ blue, 16777619);
    hash = Math.imul(hash ^ alpha, 16777619);
  }
  const encoded = canvas.toDataURL("image/png");
  let encodedHash = 2166136261;
  for (let index = 0; index < encoded.length; index += 1) {
    encodedHash = Math.imul(encodedHash ^ encoded.charCodeAt(index), 16777619);
  }
  return {
    width: canvas.width,
    height: canvas.height,
    nonTransparent,
    nonZero,
    channelSum,
    hash: hash >>> 0,
    encodedHash: encodedHash >>> 0,
  };
}
"""


def _png_dimensions(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n", f"Not a PNG: {path}"
    return struct.unpack(">II", header[16:24])


def _capture_screenshot_evidence(
    harness: GuiHarness,
    tmp_path: Path,
    name: str,
    *,
    viewport: tuple[int, int],
    baseline: bool,
) -> Path:
    page = harness.page
    page.add_style_tag(content=SCREENSHOT_STYLE)
    actual = tmp_path / name
    page.screenshot(path=str(actual), animations="disabled")
    assert actual.stat().st_size > 8_000
    assert _png_dimensions(actual) == viewport

    control_image = tmp_path / f"control-{name}"
    page.locator(".record-stage").screenshot(path=str(control_image), animations="disabled")
    assert control_image.stat().st_size > 1_000
    control_width, control_height = _png_dimensions(control_image)
    assert control_width > 100 and control_height > 40

    if baseline:
        baseline_path = BASELINE_DIR / name
        if os.environ.get("UPDATE_E2E_BASELINES") == "1":
            baseline_path.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(baseline_path), animations="disabled")
        assert baseline_path.is_file(), f"Missing baseline: {baseline_path}"
        assert baseline_path.stat().st_size > 8_000
        assert _png_dimensions(baseline_path) == viewport
    return actual


def _assert_page_health(harness: GuiHarness) -> None:
    page = harness.page
    expect(page).to_have_title("Yiyawei - 咿呀喂")
    expect(page.locator("main.app-shell")).to_be_visible()
    assert page.locator("body").inner_text().strip()
    assert page.locator(
        "nextjs-portal, vite-error-overlay, #webpack-dev-server-client-overlay"
    ).count() == 0
    assert harness.console_messages == []
    assert harness.page_errors == []
    assert harness.external_requests == []


def _state_poll_count(page: Page) -> int:
    return int(page.evaluate("() => window.__e2eStatePollCount || 0"))


def _wait_for_state_polls(page: Page, target: int) -> None:
    page.wait_for_function(
        "target => (window.__e2eStatePollCount || 0) >= target",
        arg=target,
        timeout=6_000,
    )


def _wait_until_ready(page: Page) -> None:
    expect(page.locator("#statusText")).to_have_text("就绪")
    expect(page.locator("#recordButton")).to_be_enabled()
    expect(page.locator("#recordButton")).to_have_attribute("aria-label", "开始录音")


def _audio_canvas_signature(page: Page) -> dict[str, int]:
    return page.locator("#audioCapsuleCanvas").evaluate(CANVAS_PIXEL_SIGNATURE)


def _assert_audio_canvas_visible(page: Page) -> dict[str, Any]:
    canvas = page.locator("#audioCapsuleCanvas")
    record_stage = page.locator(".record-stage")
    expect(canvas).to_be_visible()
    expect(record_stage).to_be_visible()

    canvas_box = canvas.bounding_box()
    stage_box = record_stage.bounding_box()
    assert canvas_box is not None
    assert stage_box is not None
    assert canvas_box["width"] > 0
    assert canvas_box["height"] > 0
    assert stage_box["width"] > 0
    assert stage_box["height"] > 0

    style = canvas.evaluate(
        """
        element => {
          const computed = getComputedStyle(element);
          return {
            display: computed.display,
            visibility: computed.visibility,
            opacity: Number.parseFloat(computed.opacity),
            width: Number.parseFloat(computed.width),
            height: Number.parseFloat(computed.height),
          };
        }
        """
    )
    assert style["display"] != "none"
    assert style["visibility"] == "visible"
    assert style["opacity"] > 0
    assert style["width"] > 0
    assert style["height"] > 0
    assert abs(style["width"] - canvas_box["width"]) <= max(4.0, style["width"] * 0.02)
    assert abs(style["height"] - canvas_box["height"]) <= max(4.0, style["height"] * 0.02)

    tolerance = 1.0
    assert canvas_box["x"] >= stage_box["x"] - tolerance
    assert canvas_box["y"] >= stage_box["y"] - tolerance
    assert canvas_box["x"] + canvas_box["width"] <= (
        stage_box["x"] + stage_box["width"] + tolerance
    )
    assert canvas_box["y"] + canvas_box["height"] <= (
        stage_box["y"] + stage_box["height"] + tolerance
    )
    return {"canvas_box": canvas_box, "stage_box": stage_box, "style": style}


def _intersection_area(first: dict[str, float], second: dict[str, float]) -> float:
    width = max(
        0.0,
        min(first["x"] + first["width"], second["x"] + second["width"])
        - max(first["x"], second["x"]),
    )
    height = max(
        0.0,
        min(first["y"] + first["height"], second["y"] + second["height"])
        - max(first["y"], second["y"]),
    )
    return width * height


def _assert_fixed_viewport_layout(page: Page, viewport: tuple[int, int]) -> None:
    layout = page.evaluate(
        """
        () => ({
          innerWidth: window.innerWidth,
          innerHeight: window.innerHeight,
          documentWidth: document.documentElement.scrollWidth,
          bodyWidth: document.body.scrollWidth,
        })
        """
    )
    assert layout["innerWidth"] == viewport[0]
    assert layout["innerHeight"] == viewport[1]
    assert layout["documentWidth"] <= viewport[0]
    assert layout["bodyWidth"] <= viewport[0]

    named_selectors = {
        "shell": ".window-glass",
        "controls": ".control-strip",
        "record-stage": ".record-stage",
        "info": ".info-strip",
        "results": ".result-section",
        "status": "#statusPill",
        "title": ".title-stack",
        "intelligent-output-switch": "label[for='intelligentOutputSwitch']",
        "fast-switch": "label[for='fastSwitch']",
        "record-button": "#recordButton",
        "record-state": ".stage-state",
        "record-time": ".stage-time",
        "raw-pane": ".text-pane:first-child",
        "final-pane": ".text-pane.featured",
    }
    boxes: dict[str, dict[str, float]] = {}
    for name, selector in named_selectors.items():
        locator = page.locator(selector)
        expect(locator).to_be_visible()
        box = locator.bounding_box()
        assert box is not None
        assert box["x"] >= -1
        assert box["x"] + box["width"] <= viewport[0] + 1
        boxes[name] = box

    select_boxes: list[dict[str, float]] = []
    select_triggers = page.locator(".control-strip .select-trigger")
    assert select_triggers.count() == 3
    for index in range(select_triggers.count()):
        trigger = select_triggers.nth(index)
        expect(trigger).to_be_visible()
        box = trigger.bounding_box()
        assert box is not None
        assert box["x"] >= -1
        assert box["x"] + box["width"] <= viewport[0] + 1
        select_boxes.append(box)

    non_overlapping_groups = [
        [
            boxes["controls"],
            boxes["record-stage"],
            boxes["info"],
            boxes["results"],
        ],
        [
            boxes["status"],
            boxes["title"],
            boxes["intelligent-output-switch"],
            boxes["fast-switch"],
        ],
        [boxes["record-button"], boxes["record-state"], boxes["record-time"]],
        [boxes["raw-pane"], boxes["final-pane"]],
        select_boxes,
    ]
    for group in non_overlapping_groups:
        for index, first in enumerate(group):
            for second in group[index + 1 :]:
                assert _intersection_area(first, second) <= 1.0

    for trigger_box in select_boxes:
        assert _intersection_area(trigger_box, boxes["record-button"]) <= 1.0


def test_css_modules_load_in_order_and_preserve_computed_styles(
    gui_session: Any,
) -> None:
    harness = gui_session()
    page = harness.page
    _wait_until_ready(page)

    css_contract = page.evaluate(
        """
        () => {
          const entry = Array.from(document.styleSheets).find(
            (sheet) => sheet.href && new URL(sheet.href).pathname === "/styles.css"
          );
          const imports = entry
            ? Array.from(entry.cssRules)
                .filter((rule) => rule.type === CSSRule.IMPORT_RULE)
                .map((rule) => ({
                  path: new URL(rule.href, entry.href).pathname,
                  ruleCount: rule.styleSheet ? rule.styleSheet.cssRules.length : -1,
                }))
            : [];
          const rootStyle = getComputedStyle(document.documentElement);
          const micFill = getComputedStyle(document.querySelector(".mic-capsule")).fill;
          return {
            imports,
            rootRadius: rootStyle.getPropertyValue("--radius-xl").trim(),
            windowDisplay: getComputedStyle(document.querySelector(".window-glass")).display,
            windowRadius: getComputedStyle(document.querySelector(".window-glass")).borderRadius,
            selectDisplay: getComputedStyle(document.querySelector(".select-trigger")).display,
            recordDisplay: getComputedStyle(document.querySelector(".record-stage")).display,
            recordButtonWidth: getComputedStyle(document.querySelector(".record-orb")).width,
            infoRadius: getComputedStyle(document.querySelector(".info-strip")).borderRadius,
            micFill,
          };
        }
        """
    )

    assert [item["path"] for item in css_contract["imports"]] == [
        "/css/tokens.css",
        "/css/themes.css",
        "/css/base.css",
        "/css/layout.css",
        "/css/controls.css",
        "/css/recording.css",
        "/css/editor.css",
    ]
    assert all(item["ruleCount"] > 0 for item in css_contract["imports"])
    assert css_contract["rootRadius"] == "26px"
    assert css_contract["windowDisplay"] == "grid"
    assert css_contract["windowRadius"] == "24px"
    assert css_contract["selectDisplay"] == "flex"
    assert css_contract["recordDisplay"] == "grid"
    assert css_contract["recordButtonWidth"] == "74px"
    assert css_contract["infoRadius"] == "15px"
    assert "#micGradient" in css_contract["micFill"]
    _assert_page_health(harness)


def test_warming_transitions_to_ready_without_legacy_banner(
    gui_session: Any,
    tmp_path: Path,
) -> None:
    harness = gui_session(asr_ready=False)
    page = harness.page

    expect(page.locator("#recordButton")).to_be_visible()
    expect(page.locator("#recordButton")).to_be_disabled()
    expect(page.locator("#recordButton")).to_have_attribute("aria-label", "预热中")
    expect(page.locator("#recordTitle")).to_have_text("加载中")
    assert "warming" in (page.locator(".record-stage").get_attribute("class") or "").split()
    expect(page.locator(".control-strip")).to_be_visible()
    assert page.locator(".control-strip .select-trigger").count() == 3
    expect(page.locator(".switch-field").first).to_be_visible()
    assert page.locator(".loading-banner, .loading-wordmark").count() == 0
    assert page.get_by_text("Please wait a moment").count() == 0
    _capture_screenshot_evidence(
        harness,
        tmp_path,
        "warming-700x640.png",
        viewport=(700, 640),
        baseline=True,
    )

    harness.app.mark_asr_ready()
    expect(page.locator("#statusText")).to_have_text("就绪")
    expect(page.locator("#recordButton")).to_be_enabled()
    expect(page.locator("#recordButton")).to_have_attribute("aria-label", "开始录音")
    expect(page.locator("#recordTitle")).to_have_text("待机中")
    assert harness.controller.get_state()["phase"] == "ready"
    _assert_page_health(harness)


def test_click_flow_recording_processing_and_done(
    gui_session: Any,
    tmp_path: Path,
) -> None:
    harness = gui_session(block_processing=True)
    page = harness.page
    record_button = page.locator("#recordButton")
    _wait_until_ready(page)

    record_button.click()
    expect(record_button).to_have_attribute("aria-label", "停止录音")
    expect(page.locator("#statusText")).to_have_text("录音中")
    expect(page.locator("#recordTitle")).to_have_text("录音中")
    assert "recording" in (page.locator(".record-stage").get_attribute("class") or "").split()
    expect(page.locator("#recordSubtitle")).to_have_text("00:00:01")
    assert harness.app.recorder.start_count == 1
    _capture_screenshot_evidence(
        harness,
        tmp_path,
        "recording-700x640.png",
        viewport=(700, 640),
        baseline=True,
    )

    record_button.click()
    expect(record_button).to_be_disabled()
    expect(record_button).to_have_attribute("aria-label", "处理中")
    expect(page.locator("#recordTitle")).to_have_text("处理中")
    expect(page.locator("#finalText")).to_have_value("正在处理语音，请稍等...")
    assert harness.app.processing_started.wait(timeout=1.0)

    harness.app.processing_release.set()
    expect(page.locator("#recordTitle")).to_have_text("已完成")
    expect(page.locator("#statusText")).to_have_text("待确认")
    expect(page.locator("#rawText")).to_have_value(
        "turn the selected note into a concise task"
    )
    expect(page.locator("#finalText")).to_have_value(
        "Summarize the selected note as a concise implementation task."
    )
    expect(page.locator("#recordMetric")).to_have_text("#e2e-001")
    expect(record_button).to_be_enabled()
    assert harness.app.recorder.stop_count == 1
    assert harness.app.process_count == 1
    assert harness.app.process_kwargs[0]["allow_paste"] is True
    assert harness.app.process_kwargs[0]["use_fast"] is True
    assert harness.app.process_kwargs[0]["intelligent_output"] is True
    _assert_page_health(harness)


def test_recording_audio_canvas_draws_and_changes_on_animation_frame(
    gui_session: Any,
) -> None:
    harness = gui_session()
    page = harness.page
    record_button = page.locator("#recordButton")
    _wait_until_ready(page)

    record_button.click()
    page.wait_for_function(
        "() => document.querySelector('.record-stage')?.classList.contains('recording')",
        polling="raf",
        timeout=6_000,
    )
    assert harness.app.recorder.start_count == 1
    canvas_layout = _assert_audio_canvas_visible(page)
    page.wait_for_function(
        """
        () => new Promise((resolve) => requestAnimationFrame(() => {
          const canvas = document.querySelector("#audioCapsuleCanvas");
          resolve(Boolean(canvas && canvas.width > 0 && canvas.height > 0));
        }))
        """,
        polling="raf",
        timeout=6_000,
    )

    initial = _audio_canvas_signature(page)
    assert initial["width"] > 0
    assert initial["height"] > 0
    assert initial["width"] >= canvas_layout["style"]["width"] - 1
    assert initial["height"] >= canvas_layout["style"]["height"] - 1
    minimum_pixels = max(256, initial["width"] * initial["height"] // 20)
    assert initial["nonTransparent"] >= minimum_pixels
    assert initial["nonZero"] >= minimum_pixels

    page.wait_for_function(
        """
        previous => new Promise((resolve) => {
          requestAnimationFrame(() => {
            const canvas = document.querySelector("#audioCapsuleCanvas");
            const encoded = canvas.toDataURL("image/png");
            let encodedHash = 2166136261;
            for (let index = 0; index < encoded.length; index += 1) {
              encodedHash = Math.imul(encodedHash ^ encoded.charCodeAt(index), 16777619);
            }
            resolve((encodedHash >>> 0) !== previous.encodedHash);
          });
        })
        """,
        arg=initial,
        polling="raf",
        timeout=6_000,
    )
    _assert_page_health(harness)


def test_auto_stop_stops_and_processes_exactly_once(gui_session: Any) -> None:
    harness = gui_session(auto_stop=True, block_processing=True)
    page = harness.page
    record_button = page.locator("#recordButton")
    _wait_until_ready(page)

    record_button.click()
    expect(record_button).to_have_attribute("aria-label", "停止录音")
    harness.app.recorder.auto_stop_armed.set()
    expect(page.locator("#statusText")).to_have_text("自动停止，处理中")
    expect(record_button).to_be_disabled()
    assert harness.app.processing_started.wait(timeout=1.0)
    assert harness.app.recorder.stop_count == 1
    assert harness.app.process_count == 1

    harness.app.processing_release.set()
    expect(page.locator("#recordTitle")).to_have_text("已完成")
    poll_target = _state_poll_count(page) + 2
    _wait_for_state_polls(page, poll_target)
    expect(page.locator("#recordTitle")).to_have_text("已完成")
    assert harness.app.recorder.start_count == 1
    assert harness.app.recorder.stop_count == 1
    assert harness.app.process_count == 1
    _assert_page_health(harness)


def test_dirty_final_text_survives_poll_and_restore_uses_snapshot(
    gui_session: Any,
) -> None:
    initial_final = "Initial server snapshot"
    dirty_final = "User edit that must survive polling"
    server_refresh = "New server value for the same operation"
    harness = gui_session(
        initial_state={
            "phase": "done",
            "status": "待确认",
            "raw_text": "Initial raw transcript",
            "final_text": initial_final,
            "record_id": "operation-7",
        }
    )
    page = harness.page
    final_text = page.locator("#finalText")
    expect(final_text).to_have_value(initial_final)

    final_text.fill(dirty_final)
    expect(page.locator("#finalEditState")).to_have_text("已修改")
    expect(page.locator("#finalRestoreTextButton")).to_be_enabled()
    poll_target = _state_poll_count(page) + 1
    with harness.controller._lock:
        harness.controller.state.final_text = server_refresh
        harness.controller.state.updated_at += 10
    _wait_for_state_polls(page, poll_target)

    expect(final_text).to_have_value(dirty_final)
    expect(page.locator("#finalEditState")).to_have_text("已修改")
    page.locator("#finalRestoreTextButton").click()
    assert final_text.input_value() == initial_final
    expect(page.locator("#finalRestoreTextButton")).to_be_disabled()
    expect(page.locator("#finalEditState")).to_have_text("Ready")
    assert harness.controller.get_state()["finalText"] == server_refresh
    _assert_page_health(harness)


def test_raw_confirm_saves_once_without_paste_and_clears_dirty_state(
    gui_session: Any,
) -> None:
    initial_raw = "Initial ASR transcript"
    edited_raw = "Corrected ASR transcript"
    initial_final = "Initial compiled output"
    harness = gui_session(
        initial_state={
            "phase": "done",
            "status": "待确认",
            "raw_text": initial_raw,
            "final_text": initial_final,
            "record_id": "77",
        }
    )
    page = harness.page
    raw_text = page.locator("#rawText")
    raw_confirm = page.locator("#rawConfirmTextButton")
    raw_restore = page.locator("#rawRestoreTextButton")

    expect(raw_text).to_have_value(initial_raw)
    raw_text.fill(edited_raw)
    expect(page.locator("#rawEditState")).to_have_text("已修改")
    expect(raw_confirm).to_be_enabled()
    expect(raw_restore).to_be_enabled()

    raw_confirm.click()
    expect(page.locator("#confirmDialog")).to_be_visible()
    expect(page.locator("#confirmDialogTitle")).to_have_text("确认识别原文修改？")
    assert harness.app.confirm_calls == []
    page.locator("#confirmYesButton").click()
    expect(page.locator("#confirmDialog")).to_be_hidden()
    expect(page.locator("#rawEditState")).to_have_text("已保存")
    expect(page.locator("#statusText")).to_have_text("已保存识别修正")
    expect(raw_text).to_have_value(edited_raw)
    expect(raw_confirm).to_be_disabled()
    expect(raw_restore).to_be_disabled()
    assert "is-dirty" not in (raw_confirm.get_attribute("class") or "").split()
    expect(page.locator("#finalText")).to_have_value(initial_final)
    assert len(harness.app.confirm_calls) == 1
    assert harness.app.confirm_calls[0]["source_kind"] == "asr_text"
    assert harness.app.confirm_calls[0]["before_text"] == initial_raw
    assert harness.app.confirm_calls[0]["after_text"] == edited_raw

    poll_target = _state_poll_count(page) + 1
    _wait_for_state_polls(page, poll_target)
    assert len(harness.app.confirm_calls) == 1
    expect(page.locator("#rawEditState")).to_have_text("已保存")
    expect(raw_confirm).to_be_disabled()
    expect(raw_restore).to_be_disabled()
    _assert_page_health(harness)


def test_final_confirm_rejects_stale_base_before_learning_or_paste(
    gui_session: Any,
) -> None:
    initial_final = "Initial authoritative output"
    edited_final = "User edit based on the initial output"
    authoritative_final = "New authoritative output"
    harness = gui_session(
        initial_state={
            "phase": "done",
            "status": "待确认",
            "raw_text": "Initial raw transcript",
            "final_text": initial_final,
            "record_id": "88",
        }
    )
    page = harness.page
    final_text = page.locator("#finalText")
    final_confirm = page.locator("#finalConfirmTextButton")

    expect(final_text).to_have_value(initial_final)
    final_text.fill(edited_final)
    expect(page.locator("#finalEditState")).to_have_text("已修改")
    final_confirm.click()
    expect(page.locator("#confirmDialog")).to_be_visible()
    expect(page.locator("#confirmDialogTitle")).to_have_text("确认使用当前修改？")

    with harness.controller._lock:
        harness.controller.state.final_text = authoritative_final
        harness.controller.state.updated_at += 10
    assert harness.controller.get_state()["finalText"] == authoritative_final

    page.locator("#confirmYesButton").click()
    expect(page.locator("#confirmDialog")).to_be_hidden()
    expect(page.locator("#finalEditState")).to_have_text("确认失败")
    expect(page.locator("#statusText")).to_have_text("确认失败")
    expect(page.locator("#statusPill")).to_have_attribute("class", "status-pill error")
    expect(final_text).to_have_value(edited_final)
    expect(final_confirm).to_be_enabled()
    expect(page.locator("#finalRestoreTextButton")).to_be_enabled()
    assert harness.app.confirm_calls == []
    _assert_page_health(harness)


def test_fast_mode_post_persists_across_later_polls(gui_session: Any) -> None:
    harness = gui_session()
    page = harness.page
    fast_switch = page.locator("#fastSwitch")
    settings_payloads: list[dict[str, Any]] = []

    def capture_settings(request: Any) -> None:
        if request.url.endswith("/api/settings") and request.method == "POST":
            settings_payloads.append(json.loads(request.post_data or "{}"))

    page.on("request", capture_settings)
    _wait_until_ready(page)
    expect(fast_switch).to_be_checked()
    expect(page.locator("#fastModeLabel")).to_have_text("快速模式")
    initial_poll_count = _state_poll_count(page)

    fast_switch.uncheck(force=True)
    expect(page.locator("#fastModeLabel")).to_have_text("稳定模式")
    page.wait_for_function(
        "async () => (await fetch('/api/state')).useFast === false",
        timeout=4_000,
    )
    _wait_for_state_polls(page, initial_poll_count + 2)

    expect(fast_switch).not_to_be_checked()
    expect(page.locator("#fastModeLabel")).to_have_text("稳定模式")
    assert harness.controller.get_state()["useFast"] is False
    assert settings_payloads
    assert settings_payloads[-1]["useFast"] is False
    _assert_page_health(harness)


def test_intelligent_output_switch_posts_and_persists_across_later_polls(gui_session: Any) -> None:
    harness = gui_session()
    page = harness.page
    intelligent_switch = page.locator("#intelligentOutputSwitch")
    settings_payloads: list[dict[str, Any]] = []

    def capture_settings(request: Any) -> None:
        if request.url.endswith("/api/settings") and request.method == "POST":
            settings_payloads.append(json.loads(request.post_data or "{}"))

    page.on("request", capture_settings)
    _wait_until_ready(page)
    expect(intelligent_switch).to_be_checked()
    expect(page.locator("#intelligentOutputLabel")).to_have_text("智能输出")
    initial_poll_count = _state_poll_count(page)

    intelligent_switch.uncheck(force=True)
    page.wait_for_function(
        "async () => (await fetch('/api/state')).intelligentOutput === false",
        timeout=4_000,
    )
    _wait_for_state_polls(page, initial_poll_count + 2)

    expect(intelligent_switch).not_to_be_checked()
    expect(page.locator("#intelligentOutputLabel")).to_have_text("关闭智能")
    assert harness.controller.get_state()["intelligentOutput"] is False
    assert settings_payloads[-1]["intelligentOutput"] is False
    _assert_page_health(harness)


def test_custom_mode_and_theme_selects_persist_and_escape_closes(
    gui_session: Any,
) -> None:
    harness = gui_session()
    page = harness.page
    settings_payloads: list[dict[str, Any]] = []
    theme_payloads: list[dict[str, Any]] = []

    def capture_requests(request: Any) -> None:
        if request.method != "POST":
            return
        payload = json.loads(request.post_data or "{}")
        if request.url.endswith("/api/settings"):
            settings_payloads.append(payload)
        elif request.url.endswith("/api/theme") and payload.get("theme") == "aurora-blue":
            theme_payloads.append(payload)

    page.on("request", capture_requests)
    _wait_until_ready(page)

    mode_shell = page.locator("#modeSelect + .select-shell")
    mode_trigger = mode_shell.locator(".select-trigger")
    expect(mode_trigger).to_have_attribute("aria-expanded", "false")
    mode_trigger.click()
    expect(mode_trigger).to_have_attribute("aria-expanded", "true")
    mode_shell.locator('.select-option[data-value="normal_dictation"]').click()
    expect(page.locator("#modeSelect")).to_have_value("normal_dictation")
    expect(mode_trigger).to_have_attribute("aria-expanded", "false")
    page.wait_for_function(
        "async () => (await fetch('/api/state')).mode === 'normal_dictation'",
        timeout=4_000,
    )
    assert settings_payloads
    assert settings_payloads[-1]["mode"] == "normal_dictation"

    theme_shell = page.locator("#themeSelect + .select-shell")
    theme_trigger = theme_shell.locator(".select-trigger")
    theme_trigger.click()
    expect(theme_trigger).to_have_attribute("aria-expanded", "true")
    theme_shell.locator('.select-option[data-value="aurora-blue"]').click()
    expect(page.locator("#themeSelect")).to_have_value("aurora-blue")
    expect(theme_trigger).to_have_attribute("aria-expanded", "false")
    page.wait_for_function(
        """
        () => document.documentElement.dataset.theme === "aurora-blue"
          && localStorage.getItem("voice-prompt-compiler-theme") === "aurora-blue"
          && localStorage.getItem("voice-prompt-compiler-theme-version") === "3"
        """
    )
    assert page.locator("#themeSwatches > span").count() == 3
    page.wait_for_timeout(900)
    assert len(theme_payloads) == 2
    assert theme_payloads == [
        {"theme": "aurora-blue", "color": "#e7f4ff"},
        {"theme": "aurora-blue", "color": "#e7f4ff"},
    ]

    mode_trigger.click()
    expect(mode_trigger).to_have_attribute("aria-expanded", "true")
    page.keyboard.press("Escape")
    expect(mode_trigger).to_have_attribute("aria-expanded", "false")
    assert page.locator("html").get_attribute("data-theme") == "aurora-blue"
    _assert_page_health(harness)


@pytest.mark.parametrize("viewport", [(700, 640), (390, 720)])
def test_fixed_viewports_have_no_horizontal_overflow_or_control_overlap(
    gui_session: Any,
    tmp_path: Path,
    viewport: tuple[int, int],
) -> None:
    harness = gui_session(viewport=viewport)
    page = harness.page
    _wait_until_ready(page)
    _assert_fixed_viewport_layout(page, viewport)

    name = f"ready-{viewport[0]}x{viewport[1]}.png"
    _capture_screenshot_evidence(
        harness,
        tmp_path,
        name,
        viewport=viewport,
        baseline=viewport == (390, 720),
    )
    _assert_page_health(harness)
