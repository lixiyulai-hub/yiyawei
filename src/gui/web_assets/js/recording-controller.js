export function createRecordingController({
  recordButton,
  api,
  getSettingsPayload,
  applyState,
  getCurrentPhase,
  renderToggleError,
  renderPollingError,
  scheduler = (callback, delay) => globalThis.setTimeout(callback, delay),
}) {
  let bound = false;
  let pollingStarted = false;

  async function toggleRecording() {
    try {
      const result = await api("/api/toggle", {
        method: "POST",
        body: JSON.stringify(getSettingsPayload()),
      });
      if (result.state) applyState(result.state);
    } catch (error) {
      renderToggleError(error);
    }
  }

  async function pollState() {
    try {
      const state = await api("/api/state");
      applyState(state);
    } catch (error) {
      renderPollingError(error);
    } finally {
      const currentPhase = getCurrentPhase();
      const fastPoll = currentPhase === "recording" || currentPhase === "processing";
      scheduler(pollState, fastPoll ? 450 : 1100);
    }
  }

  function startPolling() {
    if (pollingStarted) return;
    pollingStarted = true;
    pollState();
  }

  function bind() {
    if (bound) return;
    bound = true;
    recordButton.addEventListener("click", toggleRecording);
  }

  return {
    bind,
    pollState,
    startPolling,
    toggleRecording,
  };
}
