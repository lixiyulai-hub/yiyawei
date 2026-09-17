import { mapVoiceLevel } from "./audio-visualizer.js";

export function phaseClass(phase) {
  if (phase === "recording") return "recording";
  if (phase === "done") return "done";
  if (phase === "error") return "error";
  return "";
}

export function formatTimer(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return [hours, minutes, secs].map((part) => String(part).padStart(2, "0")).join(":");
}

export function createStateRenderer({
  elements,
  settingsController,
  editorController,
  audioCapsuleVisualizer,
}) {
  const {
    statusPill,
    statusText,
    recordStage,
    recordButton,
    recordTitle,
    recordSubtitle,
    targetText,
    asrMetric,
    llmMetric,
    timeMetric,
    recordMetric,
  } = elements;

  return function renderState(state) {
    settingsController.applyState(state);

    statusPill.className = `status-pill ${phaseClass(state.phase)}`;
    statusText.textContent = state.status || "就绪";
    const voiceLevel = mapVoiceLevel(state.level);
    recordStage.style.setProperty("--voice-level", voiceLevel.toFixed(3));
    recordStage.style.setProperty("--audio-capsule-level", voiceLevel.toFixed(3));
    audioCapsuleVisualizer.update({ level: voiceLevel, phase: state.phase });
    recordStage.classList.toggle("recording", state.phase === "recording");
    recordStage.classList.toggle("warming", state.phase === "warming");

    recordButton.disabled = state.phase === "processing" || state.phase === "warming";
    if (state.phase === "recording") {
      recordButton.setAttribute("aria-label", "停止录音");
      recordTitle.textContent = "录音中";
      recordSubtitle.textContent = formatTimer(state.elapsedSec);
    } else if (state.phase === "processing") {
      recordButton.setAttribute("aria-label", "处理中");
      recordTitle.textContent = "处理中";
      recordSubtitle.textContent = "00:00:00";
    } else if (state.phase === "warming") {
      recordButton.setAttribute("aria-label", "预热中");
      recordTitle.textContent = "加载中";
      recordSubtitle.textContent = "00:00:00";
    } else {
      recordButton.setAttribute("aria-label", "开始录音");
      recordTitle.textContent = state.phase === "done" ? "已完成" : "待机中";
      recordSubtitle.textContent = "00:00:00";
    }

    targetText.textContent = state.target || "先点目标输入框，再回到这里开始录音。";
    asrMetric.textContent = `${state.asrModel || "-"} / ${state.asrDevice || "-"}`;
    llmMetric.textContent = state.llmModel || "-";
    timeMetric.textContent = `ASR ${state.asrMs || "-"}ms · LLM ${state.llmMs || "-"}ms`;
    recordMetric.textContent = state.recordId && state.recordId !== "-" ? `#${state.recordId}` : "-";
    editorController.applyState(state);
  };
}
