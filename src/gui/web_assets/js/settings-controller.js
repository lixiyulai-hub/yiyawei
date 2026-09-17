export function createSettingsController({
  elements,
  api,
  applyState: renderState,
  syncCustomSelect,
}) {
  const {
    modeSelect,
    scriptSelect,
    fastSwitch,
    fastModeLabel,
    intelligentOutputSwitch,
    intelligentOutputLabel,
    statusText,
    statusPill,
  } = elements;
  let bound = false;

  function applyFastModeLabel(useFast) {
    fastModeLabel.textContent = useFast ? "快速模式" : "稳定模式";
    fastModeLabel.title = useFast ? "使用 fast_llm 快速整理" : "使用主力 llm 稳定整理";
  }

  function applyIntelligentOutputLabel(enabled) {
    intelligentOutputLabel.textContent = enabled ? "智能输出" : "关闭智能";
  }

  function getPayload() {
    return {
      mode: modeSelect.value,
      outputScript: scriptSelect.value,
      useFast: fastSwitch.checked,
      intelligentOutput: intelligentOutputSwitch.checked,
    };
  }

  function applySettingsState(state) {
    modeSelect.value = state.mode;
    scriptSelect.value = state.outputScript;
    syncCustomSelect(modeSelect);
    syncCustomSelect(scriptSelect);
    fastSwitch.checked = state.useFast;
    intelligentOutputSwitch.checked = state.intelligentOutput;
    applyFastModeLabel(state.useFast);
    applyIntelligentOutputLabel(state.intelligentOutput);
  }

  async function syncSettings() {
    try {
      const result = await api("/api/settings", {
        method: "POST",
        body: JSON.stringify(getPayload()),
      });
      if (result.state) renderState(result.state);
    } catch (error) {
      statusText.textContent = "设置未同步";
      statusPill.className = "status-pill error";
    }
  }

  function bind() {
    if (bound) return;
    bound = true;
    modeSelect.addEventListener("change", syncSettings);
    scriptSelect.addEventListener("change", syncSettings);
    fastSwitch.addEventListener("change", () => {
      applyFastModeLabel(fastSwitch.checked);
      syncSettings();
    });
    intelligentOutputSwitch.addEventListener("change", () => {
      applyIntelligentOutputLabel(intelligentOutputSwitch.checked);
      syncSettings();
    });
  }

  return {
    getPayload,
    applyState: applySettingsState,
    bind,
  };
}
