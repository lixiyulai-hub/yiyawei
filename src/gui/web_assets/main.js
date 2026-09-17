import { createApiClient } from "./js/api-client.js";
import { createAudioCapsuleVisualizer } from "./js/audio-visualizer.js";
import { createCustomSelectManager } from "./js/custom-select.js";
import { createEditorController } from "./js/editor-controller.js";
import { createRecordingController } from "./js/recording-controller.js";
import { createSettingsController } from "./js/settings-controller.js";
import { createStateMachine } from "./js/state-machine.js";
import { createStateRenderer } from "./js/state-renderer.js";
import { createThemeManager } from "./js/theme-manager.js";

const refs = {
  modeSelect: document.querySelector("#modeSelect"),
  scriptSelect: document.querySelector("#scriptSelect"),
  themeSelect: document.querySelector("#themeSelect"),
  themeSwatches: document.querySelector("#themeSwatches"),
  fastSwitch: document.querySelector("#fastSwitch"),
  fastModeLabel: document.querySelector("#fastModeLabel"),
  intelligentOutputSwitch: document.querySelector("#intelligentOutputSwitch"),
  intelligentOutputLabel: document.querySelector("#intelligentOutputLabel"),
  recordButton: document.querySelector("#recordButton"),
  recordTitle: document.querySelector("#recordTitle"),
  recordSubtitle: document.querySelector("#recordSubtitle"),
  recordStage: document.querySelector(".record-stage"),
  audioCapsuleCanvas: document.querySelector("#audioCapsuleCanvas"),
  statusPill: document.querySelector("#statusPill"),
  statusText: document.querySelector("#statusText"),
  targetText: document.querySelector("#targetText"),
  asrMetric: document.querySelector("#asrMetric"),
  llmMetric: document.querySelector("#llmMetric"),
  timeMetric: document.querySelector("#timeMetric"),
  recordMetric: document.querySelector("#recordMetric"),
  rawText: document.querySelector("#rawText"),
  finalText: document.querySelector("#finalText"),
  rawEditState: document.querySelector("#rawEditState"),
  finalEditState: document.querySelector("#finalEditState"),
  rawRestoreTextButton: document.querySelector("#rawRestoreTextButton"),
  rawConfirmTextButton: document.querySelector("#rawConfirmTextButton"),
  finalRestoreTextButton: document.querySelector("#finalRestoreTextButton"),
  finalConfirmTextButton: document.querySelector("#finalConfirmTextButton"),
  confirmDialog: document.querySelector("#confirmDialog"),
  confirmDialogTitle: document.querySelector("#confirmDialogTitle"),
  confirmDialogMessage: document.querySelector("#confirmDialogMessage"),
};

const api = createApiClient();
const customSelectManager = createCustomSelectManager({ documentRef: document });
let stateRenderer;
const stateMachine = createStateMachine({ renderer: (state) => stateRenderer(state) });
const applyState = (state) => stateMachine.applyState(state);
const audioCapsuleVisualizer = createAudioCapsuleVisualizer(
  refs.audioCapsuleCanvas,
  refs.recordStage,
);
const settingsController = createSettingsController({
  elements: refs,
  api,
  applyState,
  syncCustomSelect: customSelectManager.sync,
});
const editorController = createEditorController({
  elements: refs,
  api,
  applyState,
  getCurrentPhase: () => stateMachine.getCurrentPhase(),
});
stateRenderer = createStateRenderer({
  elements: refs,
  settingsController,
  editorController,
  audioCapsuleVisualizer,
});

function renderToggleError(error) {
  refs.statusText.textContent = "连接失败";
  refs.statusPill.className = "status-pill error";
  refs.finalText.value = `错误：${error.message}`;
}

function renderPollingError() {
  refs.statusText.textContent = "连接失败";
  refs.statusPill.className = "status-pill error";
}

const recordingController = createRecordingController({
  recordButton: refs.recordButton,
  api,
  getSettingsPayload: () => settingsController.getPayload(),
  applyState,
  getCurrentPhase: () => stateMachine.getCurrentPhase(),
  renderToggleError,
  renderPollingError,
  scheduler: (callback, delay) => window.setTimeout(callback, delay),
});
const themeManager = createThemeManager({
  elements: refs,
  api,
  audioCapsuleVisualizer,
  customSelectManager,
  documentRef: document,
  windowRef: window,
});

function option({ label, value }) {
  const element = document.createElement("option");
  element.textContent = label;
  element.value = value;
  return element;
}

function applyBootstrap(data) {
  refs.modeSelect.replaceChildren(...data.modes.map(option));
  refs.scriptSelect.replaceChildren(...data.scripts.map(option));
  customSelectManager.ensure(refs.modeSelect);
  customSelectManager.ensure(refs.scriptSelect);
  applyState(data.state);
}

customSelectManager.bind();
settingsController.bind();
editorController.bind();
recordingController.bind();
themeManager.init();
document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === ".") {
    event.preventDefault();
    recordingController.toggleRecording();
  }
});

api("/api/bootstrap")
  .then(applyBootstrap)
  .catch((error) => {
    refs.statusText.textContent = "启动失败";
    refs.statusPill.className = "status-pill error";
    refs.finalText.value = `错误：${error.message}`;
  })
  .finally(() => recordingController.startPolling());
