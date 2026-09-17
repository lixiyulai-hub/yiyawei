export function createEditorController({
  elements,
  api,
  applyState: renderState,
  getCurrentPhase,
}) {
  const {
    rawText,
    finalText,
    rawEditState,
    finalEditState,
    rawRestoreTextButton,
    rawConfirmTextButton,
    finalRestoreTextButton,
    finalConfirmTextButton,
    confirmDialog,
    confirmDialogTitle,
    confirmDialogMessage,
    statusText,
    statusPill,
  } = elements;
  let textSnapshot = { rawText: "", finalText: "", recordId: "-", updatedAt: 0 };
  let rawTextDirty = false;
  let finalTextDirty = false;
  let rawEditFeedback = "";
  let finalEditFeedback = "";
  let confirmingScope = null;
  let pendingConfirmScope = "final";
  let bound = false;

  function refreshEditControls() {
    rawRestoreTextButton.disabled = !rawTextDirty;
    rawConfirmTextButton.disabled =
      confirmingScope === "raw" || !rawTextDirty || !rawText.value.trim();
    rawConfirmTextButton.classList.toggle("is-dirty", rawTextDirty);
    rawEditState.textContent =
      confirmingScope === "raw" ? "确认中" : rawEditFeedback || (rawTextDirty ? "已修改" : "ASR");

    finalRestoreTextButton.disabled = !finalTextDirty;
    finalConfirmTextButton.disabled = confirmingScope === "final" || !finalText.value.trim();
    finalConfirmTextButton.classList.toggle("is-dirty", finalTextDirty);
    finalEditState.textContent =
      confirmingScope === "final"
        ? "确认中"
        : finalEditFeedback || (finalTextDirty ? "已修改" : getCurrentPhase() === "done" ? "Ready" : "");
  }

  function setRawEditDirty(dirty) {
    rawTextDirty = dirty;
    rawEditFeedback = "";
    refreshEditControls();
  }

  function setFinalEditDirty(dirty) {
    finalTextDirty = dirty;
    finalEditFeedback = "";
    refreshEditControls();
  }

  function applyTextState(state) {
    const incoming = {
      rawText: state.rawText || "",
      finalText: state.finalText || "",
      recordId: state.recordId || "-",
      updatedAt: state.updatedAt || 0,
    };
    const newRecord = incoming.recordId !== textSnapshot.recordId;
    if (newRecord) {
      textSnapshot = incoming;
      rawText.value = incoming.rawText;
      finalText.value = incoming.finalText;
      rawTextDirty = false;
      finalTextDirty = false;
      rawEditFeedback = "";
      finalEditFeedback = "";
      refreshEditControls();
      return;
    }

    if (!rawTextDirty) {
      textSnapshot.rawText = incoming.rawText;
      rawText.value = incoming.rawText;
    }
    if (!finalTextDirty) {
      textSnapshot.finalText = incoming.finalText;
      finalText.value = incoming.finalText;
    }
    textSnapshot.recordId = incoming.recordId;
    textSnapshot.updatedAt = incoming.updatedAt;
    refreshEditControls();
  }

  function markRawTextDirty() {
    setRawEditDirty(rawText.value !== textSnapshot.rawText);
  }

  function markFinalTextDirty() {
    setFinalEditDirty(finalText.value !== textSnapshot.finalText);
  }

  function restoreRawTextSnapshot() {
    rawText.value = textSnapshot.rawText;
    setRawEditDirty(false);
  }

  function restoreFinalTextSnapshot() {
    finalText.value = textSnapshot.finalText;
    setFinalEditDirty(false);
  }

  function openConfirmDialog(scope = "final") {
    pendingConfirmScope = scope;
    if (scope === "raw" && !rawText.value.trim()) return;
    if (scope === "final" && !finalText.value.trim()) return;
    if (scope === "raw") {
      confirmDialogTitle.textContent = "确认识别原文修改？";
      confirmDialogMessage.textContent = "确认后会保存这次 ASR 识别修正，用于记住类似识别偏差。";
    } else {
      confirmDialogTitle.textContent = "确认使用当前修改？";
      confirmDialogMessage.textContent = "确认后会保存这次手动改动，并把当前最终输出粘贴到目标窗口。";
    }
    if (confirmDialog && typeof confirmDialog.showModal === "function") {
      confirmDialog.showModal();
    } else if (window.confirm(confirmDialogMessage.textContent)) {
      confirmEditedText(scope);
    }
  }

  async function confirmEditedText(scope = pendingConfirmScope) {
    const isRawScope = scope === "raw";
    confirmingScope = scope;
    if (isRawScope) rawEditFeedback = "";
    else finalEditFeedback = "";
    refreshEditControls();
    try {
      const result = await api("/api/confirm", {
        method: "POST",
        body: JSON.stringify({
          scope,
          recordId: textSnapshot.recordId,
          rawText: rawText.value,
          finalText: finalText.value,
          baseRawText: textSnapshot.rawText,
          baseFinalText: textSnapshot.finalText,
        }),
      });
      if (!result.ok) {
        throw new Error(result.error || "确认失败");
      }
      if (result.state) {
        textSnapshot = {
          rawText: result.state.rawText || "",
          finalText: result.state.finalText || "",
          recordId: result.state.recordId || "-",
          updatedAt: result.state.updatedAt || 0,
        };
        if (isRawScope) {
          rawTextDirty = false;
        } else {
          rawTextDirty = false;
          finalTextDirty = false;
        }
        renderState(result.state);
      }
      confirmingScope = null;
      if (isRawScope) rawEditFeedback = result.pasted ? "已确认" : "已保存";
      else finalEditFeedback = result.pasted ? "已确认" : "已保存";
      refreshEditControls();
    } catch (error) {
      confirmingScope = null;
      if (isRawScope) rawEditFeedback = "确认失败";
      else finalEditFeedback = "确认失败";
      statusText.textContent = "确认失败";
      statusPill.className = "status-pill error";
      refreshEditControls();
    }
  }

  function bind() {
    if (bound) return;
    bound = true;
    rawText.addEventListener("input", markRawTextDirty);
    finalText.addEventListener("input", markFinalTextDirty);
    rawRestoreTextButton.addEventListener("click", restoreRawTextSnapshot);
    rawConfirmTextButton.addEventListener("click", () => openConfirmDialog("raw"));
    finalRestoreTextButton.addEventListener("click", restoreFinalTextSnapshot);
    finalConfirmTextButton.addEventListener("click", () => openConfirmDialog("final"));
    confirmDialog.addEventListener("close", () => {
      if (confirmDialog.returnValue === "yes") confirmEditedText(pendingConfirmScope);
    });
  }

  return {
    applyState: applyTextState,
    bind,
  };
}
