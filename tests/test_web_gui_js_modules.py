from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

from src.gui.web_gui import ASSETS_DIR


def _module_url(name: str) -> str:
    return (Path(ASSETS_DIR) / "js" / name).resolve().as_uri()


def _run_node(program: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", "--input-type=module", "--eval", textwrap.dedent(program)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_extracted_state_modules_import_without_a_dom_in_node():
    module_urls = [
        _module_url("state-machine.js"),
        _module_url("state-renderer.js"),
        _module_url("recording-controller.js"),
    ]
    program = f"""
        if (typeof globalThis.document !== "undefined") process.exit(2);
        const modules = await Promise.all(
          {json.dumps(module_urls)}.map((url) => import(url)),
        );
        if (typeof modules[0].createStateMachine !== "function") process.exit(3);
        if (typeof modules[1].createStateRenderer !== "function") process.exit(4);
        if (typeof modules[2].createRecordingController !== "function") process.exit(5);
        process.stdout.write("ok");
    """

    result = _run_node(program)

    assert result.stdout == "ok"
    assert result.stderr == ""


def test_state_machine_transitions_and_snapshot_ordering_contract():
    module_url = _module_url("state-machine.js")
    program = f"""
        import assert from "node:assert/strict";
        const {{
          Phase,
          Event,
          SnapshotOrder,
          InvalidTransitionError,
          ContractValidationError,
          StaleRevisionError,
          RevisionConflictError,
          transition,
          classifySnapshotOrder,
          createStateMachine,
        }} = await import({json.dumps(module_url)});

        const legal = [
          [Phase.WARMING, Event.WARMUP_SUCCEEDED, Phase.READY],
          [Phase.WARMING, Event.WARMUP_FAILED, Phase.ERROR],
          [Phase.READY, Event.START_REQUESTED, Phase.RECORDING],
          [Phase.DONE, Event.START_REQUESTED, Phase.RECORDING],
          [Phase.ERROR, Event.START_REQUESTED, Phase.RECORDING],
          [Phase.RECORDING, Event.STOP_REQUESTED, Phase.PROCESSING],
          [Phase.RECORDING, Event.RECORDING_FAILED, Phase.ERROR],
          [Phase.PROCESSING, Event.PROCESS_SUCCEEDED, Phase.DONE],
          [Phase.PROCESSING, Event.PROCESS_FAILED, Phase.ERROR],
          [Phase.ERROR, Event.RETRY_REQUESTED, Phase.READY],
          [Phase.READY, Event.STATE_REFRESHED, Phase.READY],
          [Phase.RECORDING, Event.SETTINGS_UPDATED, Phase.RECORDING],
          [Phase.DONE, Event.EDIT_STARTED, Phase.DONE],
          [Phase.DONE, Event.EDIT_RESTORED, Phase.DONE],
          [Phase.DONE, Event.CONFIRM_SUCCEEDED, Phase.DONE],
          [Phase.DONE, Event.CONFIRM_FAILED, Phase.DONE],
          [Phase.DONE, Event.PASTE_SUCCEEDED, Phase.DONE],
          [Phase.DONE, Event.PASTE_FAILED, Phase.DONE],
        ];
        for (const [phase, event, expected] of legal) {{
          assert.equal(transition(phase, event), expected);
        }}
        assert.throws(
          () => transition(Phase.READY, Event.STOP_REQUESTED),
          InvalidTransitionError,
        );
        assert.throws(() => transition("unknown", Event.STATE_REFRESHED), InvalidTransitionError);
        assert.throws(() => transition(Phase.READY, "UNKNOWN"), InvalidTransitionError);

        const validV1 = (overrides = {{}}) => ({{
          schemaVersion: 1,
          operationId: "op-1",
          revision: 5,
          phase: Phase.READY,
          status: "就绪",
          target: "目标窗口",
          rawText: "raw",
          finalText: "final",
          mode: "cursor_prompt",
          outputScript: "simplified",
          useFast: false,
          asrModel: "whisper",
          asrDevice: "cpu",
          llmModel: "qwen",
          asrMs: "12",
          llmMs: "34",
          recordId: "42",
          riskLevel: "low",
          elapsedSec: 1.5,
          level: 0.25,
          pasted: false,
          lastError: "",
          updatedAt: 500,
          ...overrides,
        }});
        const current = validV1();
        assert.equal(
          classifySnapshotOrder(current, {{ ...current, revision: 6, updatedAt: 1 }}),
          SnapshotOrder.NEWER,
        );
        assert.equal(
          classifySnapshotOrder(current, {{ ...current, updatedAt: 999 }}),
          SnapshotOrder.IDEMPOTENT,
        );
        assert.throws(
          () => classifySnapshotOrder(current, {{ ...current, revision: 4, updatedAt: 1000 }}),
          StaleRevisionError,
        );
        assert.throws(
          () => classifySnapshotOrder(current, {{ ...current, operationId: "op-2" }}),
          RevisionConflictError,
        );

        const rendered = [];
        let machine;
        machine = createStateMachine({{
          renderer(state) {{
            assert.equal(machine.getCurrentPhase(), state.phase);
            rendered.push(state);
          }},
        }});
        assert.equal(machine.getCurrentPhase(), Phase.WARMING);

        const legacyNewestTimestamp = {{ phase: Phase.READY, updatedAt: 5000 }};
        const legacyOldTimestamp = {{ phase: Phase.DONE, updatedAt: 1 }};
        assert.equal(machine.applyState(legacyNewestTimestamp).accepted, true);
        assert.equal(machine.applyState(legacyOldTimestamp).accepted, true);
        assert.deepEqual(rendered, [legacyNewestTimestamp, legacyOldTimestamp]);

        const malformedMachineRenders = [];
        const malformedMachine = createStateMachine({{
          renderer: (state) => malformedMachineRenders.push(state),
        }});
        const without = (field) => {{
          const snapshot = validV1();
          delete snapshot[field];
          return snapshot;
        }};
        const malformedFirstSnapshots = [
          validV1({{ schemaVersion: true }}),
          validV1({{ schemaVersion: 2 }}),
          without("status"),
          validV1({{ operationId: "" }}),
          validV1({{ revision: -1 }}),
          without("revision"),
          validV1({{ phase: "unknown" }}),
          validV1({{ rawText: 42 }}),
          validV1({{ useFast: "false" }}),
          validV1({{ updatedAt: Number.POSITIVE_INFINITY }}),
          validV1({{ elapsedSec: Number.NaN }}),
        ];
        for (const malformed of malformedFirstSnapshots) {{
          assert.throws(
            () => malformedMachine.applyState(malformed),
            ContractValidationError,
          );
          assert.equal(malformedMachine.getCurrentPhase(), Phase.WARMING);
          assert.equal(malformedMachineRenders.length, 0);
        }}
        const firstValid = validV1({{
          operationId: "first-valid",
          revision: 0,
          phase: Phase.RECORDING,
          updatedAt: 1,
          extraField: "allowed",
        }});
        assert.deepEqual(malformedMachine.applyState(firstValid), {{
          accepted: true,
          order: SnapshotOrder.NEWER,
          error: null,
        }});
        assert.equal(malformedMachine.getCurrentPhase(), Phase.RECORDING);
        assert.deepEqual(malformedMachineRenders, [firstValid]);

        const v1 = validV1({{ updatedAt: 100 }});
        assert.deepEqual(machine.applyState(v1), {{
          accepted: true,
          order: SnapshotOrder.NEWER,
          error: null,
        }});
        const idempotent = {{ ...v1, phase: Phase.RECORDING, updatedAt: 0 }};
        assert.equal(machine.applyState(idempotent).order, SnapshotOrder.IDEMPOTENT);
        assert.equal(machine.getCurrentPhase(), Phase.RECORDING);

        const renderCount = rendered.length;
        const stale = machine.applyState({{ ...v1, revision: 4, phase: Phase.ERROR, updatedAt: 9999 }});
        assert.equal(stale.accepted, false);
        assert.ok(stale.error instanceof StaleRevisionError);
        assert.equal(rendered.length, renderCount);
        assert.equal(machine.getCurrentPhase(), Phase.RECORDING);

        const conflict = machine.applyState({{ ...v1, operationId: "op-2", phase: Phase.ERROR }});
        assert.equal(conflict.accepted, false);
        assert.ok(conflict.error instanceof RevisionConflictError);
        assert.equal(rendered.length, renderCount);
        assert.equal(machine.getCurrentPhase(), Phase.RECORDING);

        const newer = {{ ...v1, operationId: "op-2", revision: 6, phase: Phase.DONE, updatedAt: 1 }};
        assert.equal(machine.applyState(newer).order, SnapshotOrder.NEWER);
        assert.equal(machine.getCurrentPhase(), Phase.DONE);

        const legacyAfterV1 = {{ phase: Phase.ERROR, updatedAt: -100 }};
        assert.equal(machine.applyState(legacyAfterV1).accepted, true);
        assert.equal(machine.getCurrentPhase(), Phase.ERROR);
        assert.equal(rendered.at(-1), legacyAfterV1);

        const staleAfterLegacy = machine.applyState({{ ...v1, revision: 5, phase: Phase.READY }});
        assert.equal(staleAfterLegacy.accepted, false);
        assert.ok(staleAfterLegacy.error instanceof StaleRevisionError);
        assert.equal(machine.getCurrentPhase(), Phase.ERROR);
    """

    result = _run_node(program)

    assert result.stdout == ""
    assert result.stderr == ""


def test_state_renderer_preserves_all_phase_dom_and_controller_mappings():
    renderer_url = _module_url("state-renderer.js")
    visualizer_url = _module_url("audio-visualizer.js")
    program = f"""
        import assert from "node:assert/strict";
        const {{ createStateRenderer, formatTimer, phaseClass }} = await import(
          {json.dumps(renderer_url)}
        );
        const {{ mapVoiceLevel }} = await import({json.dumps(visualizer_url)});

        function fakeElement() {{
          const attributes = new Map();
          const classes = new Map();
          const properties = new Map();
          return {{
            textContent: "",
            className: "",
            disabled: false,
            style: {{
              setProperty(name, value) {{ properties.set(name, value); }},
              getPropertyValue(name) {{ return properties.get(name); }},
            }},
            classList: {{
              toggle(name, enabled) {{ classes.set(name, enabled); }},
              contains(name) {{ return classes.get(name) === true; }},
            }},
            setAttribute(name, value) {{ attributes.set(name, value); }},
            getAttribute(name) {{ return attributes.get(name); }},
          }};
        }}

        const elements = {{
          statusPill: fakeElement(),
          statusText: fakeElement(),
          recordStage: fakeElement(),
          recordButton: fakeElement(),
          recordTitle: fakeElement(),
          recordSubtitle: fakeElement(),
          targetText: fakeElement(),
          asrMetric: fakeElement(),
          llmMetric: fakeElement(),
          timeMetric: fakeElement(),
          recordMetric: fakeElement(),
        }};
        const order = [];
        const settingsStates = [];
        const editorStates = [];
        const visualizerUpdates = [];
        const renderState = createStateRenderer({{
          elements,
          settingsController: {{
            applyState(state) {{ order.push("settings"); settingsStates.push(state); }},
          }},
          editorController: {{
            applyState(state) {{ order.push("editor"); editorStates.push(state); }},
          }},
          audioCapsuleVisualizer: {{
            update(value) {{ order.push("visualizer"); visualizerUpdates.push(value); }},
          }},
        }});

        assert.equal(formatTimer(3661.9), "01:01:01");
        assert.equal(formatTimer(-10), "00:00:00");
        assert.equal(formatTimer("bad"), "00:00:00");
        assert.equal(phaseClass("recording"), "recording");
        assert.equal(phaseClass("done"), "done");
        assert.equal(phaseClass("error"), "error");
        assert.equal(phaseClass("ready"), "");

        const base = {{
          phase: "ready",
          status: "状态",
          level: 0.25,
          elapsedSec: 3661.9,
          target: "目标窗口",
          asrModel: "whisper",
          asrDevice: "cuda",
          llmModel: "qwen",
          asrMs: "12",
          llmMs: "34",
          recordId: "42",
          mode: "cursor_prompt",
          outputScript: "simplified",
          useFast: true,
        }};
        const expected = {{
          warming: [true, "预热中", "加载中", "00:00:00", "status-pill ", false, true],
          ready: [false, "开始录音", "待机中", "00:00:00", "status-pill ", false, false],
          recording: [false, "停止录音", "录音中", "01:01:01", "status-pill recording", true, false],
          processing: [true, "处理中", "处理中", "00:00:00", "status-pill ", false, false],
          done: [false, "开始录音", "已完成", "00:00:00", "status-pill done", false, false],
          error: [false, "开始录音", "待机中", "00:00:00", "status-pill error", false, false],
        }};

        for (const phase of Object.keys(expected)) {{
          order.length = 0;
          const state = {{ ...base, phase }};
          renderState(state);
          assert.deepEqual(order, ["settings", "visualizer", "editor"]);
          assert.equal(settingsStates.at(-1), state);
          assert.equal(editorStates.at(-1), state);
          assert.deepEqual([
            elements.recordButton.disabled,
            elements.recordButton.getAttribute("aria-label"),
            elements.recordTitle.textContent,
            elements.recordSubtitle.textContent,
            elements.statusPill.className,
            elements.recordStage.classList.contains("recording"),
            elements.recordStage.classList.contains("warming"),
          ], expected[phase]);
        }}

        const voiceLevel = mapVoiceLevel(base.level);
        assert.equal(elements.recordStage.style.getPropertyValue("--voice-level"), voiceLevel.toFixed(3));
        assert.equal(
          elements.recordStage.style.getPropertyValue("--audio-capsule-level"),
          voiceLevel.toFixed(3),
        );
        assert.deepEqual(visualizerUpdates.at(-1), {{ level: voiceLevel, phase: "error" }});
        assert.equal(elements.statusText.textContent, "状态");
        assert.equal(elements.targetText.textContent, "目标窗口");
        assert.equal(elements.asrMetric.textContent, "whisper / cuda");
        assert.equal(elements.llmMetric.textContent, "qwen");
        assert.equal(elements.timeMetric.textContent, "ASR 12ms · LLM 34ms");
        assert.equal(elements.recordMetric.textContent, "#42");

        renderState({{
          ...base,
          phase: "ready",
          status: "",
          target: "",
          asrModel: "",
          asrDevice: "",
          llmModel: "",
          asrMs: "",
          llmMs: "",
          recordId: "-",
        }});
        assert.equal(elements.statusText.textContent, "就绪");
        assert.equal(elements.targetText.textContent, "先点目标输入框，再回到这里开始录音。");
        assert.equal(elements.asrMetric.textContent, "- / -");
        assert.equal(elements.llmMetric.textContent, "-");
        assert.equal(elements.timeMetric.textContent, "ASR -ms · LLM -ms");
        assert.equal(elements.recordMetric.textContent, "-");
    """

    result = _run_node(program)

    assert result.stdout == ""
    assert result.stderr == ""


def test_recording_controller_preserves_toggle_errors_polling_and_binding():
    module_url = _module_url("recording-controller.js")
    program = f"""
        import assert from "node:assert/strict";
        const {{ createRecordingController }} = await import({json.dumps(module_url)});

        const listeners = new Map();
        const recordButton = {{
          addEventListener(type, listener) {{
            const registered = listeners.get(type) || [];
            registered.push(listener);
            listeners.set(type, registered);
          }},
        }};
        const calls = [];
        const responses = [];
        const api = async (path, options) => {{
          calls.push({{ path, options }});
          const response = responses.shift();
          if (response instanceof Error) throw response;
          return response;
        }};
        const applied = [];
        const toggleErrors = [];
        const pollingErrors = [];
        const scheduled = [];
        let currentPhase = "ready";
        const controller = createRecordingController({{
          recordButton,
          api,
          getSettingsPayload: () => ({{
            mode: "cursor_prompt",
            outputScript: "simplified",
            useFast: false,
          }}),
          applyState(state) {{ applied.push(state); currentPhase = state.phase; }},
          getCurrentPhase: () => currentPhase,
          renderToggleError: (error) => toggleErrors.push(error),
          renderPollingError: (error) => pollingErrors.push(error),
          scheduler: (callback, delay) => scheduled.push({{ callback, delay }}),
        }});

        controller.bind();
        controller.bind();
        assert.equal((listeners.get("click") || []).length, 1);
        assert.equal(listeners.get("click")[0], controller.toggleRecording);

        const recordingState = {{ phase: "recording" }};
        responses.push({{ state: recordingState }});
        await controller.toggleRecording();
        assert.equal(calls[0].path, "/api/toggle");
        assert.equal(calls[0].options.method, "POST");
        assert.deepEqual(JSON.parse(calls[0].options.body), {{
          mode: "cursor_prompt",
          outputScript: "simplified",
          useFast: false,
        }});
        assert.equal("schemaVersion" in JSON.parse(calls[0].options.body), false);
        assert.equal(applied.at(-1), recordingState);

        const toggleFailure = new Error("toggle offline");
        responses.push(toggleFailure);
        await controller.toggleRecording();
        assert.equal(toggleErrors.at(-1), toggleFailure);

        responses.push({{ phase: "recording" }});
        await controller.pollState();
        assert.equal(calls.at(-1).path, "/api/state");
        assert.equal(calls.at(-1).options, undefined);
        assert.equal(scheduled.at(-1).delay, 450);

        responses.push({{ phase: "ready" }});
        await scheduled.at(-1).callback();
        assert.equal(scheduled.at(-1).delay, 1100);

        currentPhase = "processing";
        const pollFailure = new Error("poll offline");
        responses.push(pollFailure);
        await controller.pollState();
        assert.equal(pollingErrors.at(-1), pollFailure);
        assert.equal(scheduled.at(-1).delay, 450);

        const callCount = calls.length;
        responses.push({{ phase: "done" }});
        controller.startPolling();
        await new Promise((resolve) => setImmediate(resolve));
        assert.equal(calls.length, callCount + 1);
        assert.equal(scheduled.at(-1).delay, 1100);
        controller.startPolling();
        await new Promise((resolve) => setImmediate(resolve));
        assert.equal(calls.length, callCount + 1);
    """

    result = _run_node(program)

    assert result.stdout == ""
    assert result.stderr == ""


def test_main_only_assembles_extracted_modules():
    script_path = Path(ASSETS_DIR / "main.js")
    script = script_path.read_text(encoding="utf-8")
    custom_select = Path(ASSETS_DIR / "js" / "custom-select.js").read_text(
        encoding="utf-8"
    )
    state_machine = Path(ASSETS_DIR / "js" / "state-machine.js").read_text(encoding="utf-8")
    renderer = Path(ASSETS_DIR / "js" / "state-renderer.js").read_text(encoding="utf-8")
    recording = Path(ASSETS_DIR / "js" / "recording-controller.js").read_text(
        encoding="utf-8"
    )
    theme_manager = Path(ASSETS_DIR / "js" / "theme-manager.js").read_text(
        encoding="utf-8"
    )

    assert not (ASSETS_DIR / "app.js").exists()
    assert len(script.splitlines()) <= 150
    assert 'import { createCustomSelectManager } from "./js/custom-select.js";' in script
    assert 'import { createStateMachine } from "./js/state-machine.js";' in script
    assert 'import { createStateRenderer } from "./js/state-renderer.js";' in script
    assert (
        'import { createRecordingController } from "./js/recording-controller.js";'
        in script
    )
    assert 'import { createThemeManager } from "./js/theme-manager.js";' in script
    assert "const stateMachine = createStateMachine" in script
    assert script.index("const stateMachine = createStateMachine") < script.index(
        "createAudioCapsuleVisualizer("
    )
    assert script.index("const stateMachine = createStateMachine") < script.index(
        "customSelectManager.bind();"
    )
    assert script.index("const stateMachine = createStateMachine") < script.index(
        'api("/api/bootstrap")'
    )
    assert "customSelectManager.bind();" in script
    assert "recordingController.bind();" in script
    assert "recordingController.toggleRecording();" in script
    assert ".finally(() => recordingController.startPolling());" in script
    assert script.index('api("/api/bootstrap")') < script.index(
        ".finally(() => recordingController.startPolling());"
    )

    for residue in (
        "let currentPhase",
        "function phaseClass",
        "function formatTimer",
        "async function toggleRecording",
        "async function pollState",
        'refs.recordButton.addEventListener("click"',
        'api("/api/toggle"',
        'api("/api/state"',
        'classList.toggle("warming", state.phase === "warming")',
        "const voiceLevel = mapVoiceLevel(state.level);",
        "editorController.applyState(state);",
        "function selectedOption",
        "function rebuildCustomSelectOptions",
        "function themeById",
        "function applyTheme",
        "function updateRecordGlow",
        "function updateRecordSpotlight",
        "THEME_STORAGE_KEY",
        'api("/api/theme"',
        'addEventListener("pointermove"',
        'addEventListener("pointerdown"',
        'event.key === "Escape"',
    ):
        assert residue not in script

    assert 'documentRef.addEventListener("pointerdown"' in custom_select
    assert 'event.key === "Escape"' in custom_select
    assert "function themeById" in theme_manager
    assert "function applyTheme" in theme_manager
    assert "currentPhase = state.phase;" in state_machine
    assert state_machine.index("currentPhase = state.phase;") < state_machine.index(
        "renderer(state);"
    )
    assert 'classList.toggle("warming", state.phase === "warming")' in renderer
    assert "const voiceLevel = mapVoiceLevel(state.level);" in renderer
    assert "editorController.applyState(state);" in renderer
    assert 'api("/api/toggle"' in recording
    assert 'api("/api/state"' in recording
    assert "fastPoll ? 450 : 1100" in recording
    assert "if (bound) return;" in recording
