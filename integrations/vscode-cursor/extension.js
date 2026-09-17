"use strict";

const http = require("http");
const vscode = require("vscode");

function activate(context) {
  context.subscriptions.push(
    vscode.commands.registerCommand("voicePromptCompiler.processSelection", processSelection),
    vscode.commands.registerCommand("voicePromptCompiler.processInput", processInput)
  );
}

function deactivate() {}

async function processInput() {
  const rawText = await vscode.window.showInputBox({
    prompt: "Yiyawei input",
    ignoreFocusOut: true
  });
  if (!rawText) {
    return;
  }
  const finalText = await processThroughBridge(rawText);
  if (finalText) {
    await insertText(finalText);
  }
}

async function processSelection() {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    vscode.window.showWarningMessage("Open an editor before processing text.");
    return;
  }
  const selection = editor.selection;
  const rawText = editor.document.getText(selection);
  if (!rawText.trim()) {
    vscode.window.showWarningMessage("Select text or use Process Input.");
    return;
  }
  const finalText = await processThroughBridge(rawText);
  if (!finalText) {
    return;
  }
  await editor.edit((editBuilder) => {
    editBuilder.replace(selection, finalText);
  });
}

async function processThroughBridge(rawText) {
  const config = vscode.workspace.getConfiguration("voicePromptCompiler");
  const bridgeUrl = config.get("bridgeUrl", "http://127.0.0.1:8765");
  const token = config.get("token", "");
  const mode = config.get("mode", "cursor_prompt");
  const url = new URL("/v1/process-text", bridgeUrl);
  assertLoopback(url);
  const response = await postJson(url, token, {
    raw_text: rawText,
    mode,
    use_fast: false,
    include_debug: false
  });
  const result = response.result || {};
  if (result.need_confirm || result.risk_level === "high") {
    const choice = await vscode.window.showWarningMessage(
      "Yiyawei marked this output as requiring review.",
      { modal: true },
      "Insert"
    );
    if (choice !== "Insert") {
      return "";
    }
  }
  return response.final_text || result.final_text || "";
}

function assertLoopback(url) {
  const host = url.hostname.toLowerCase();
  if (!["127.0.0.1", "localhost", "::1"].includes(host)) {
    throw new Error("Yiyawei bridge URL must be loopback.");
  }
}

function postJson(url, token, payload) {
  const body = JSON.stringify(payload);
  const headers = {
    "Content-Type": "application/json",
    "Content-Length": Buffer.byteLength(body)
  };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return new Promise((resolve, reject) => {
    const request = http.request(
      {
        method: "POST",
        hostname: url.hostname,
        port: url.port || 80,
        path: `${url.pathname}${url.search}`,
        headers,
        timeout: 30000
      },
      (response) => {
        const chunks = [];
        response.on("data", (chunk) => chunks.push(chunk));
        response.on("end", () => {
          const text = Buffer.concat(chunks).toString("utf8");
          if (response.statusCode < 200 || response.statusCode >= 300) {
            reject(new Error(`Bridge returned ${response.statusCode}: ${text}`));
            return;
          }
          try {
            resolve(JSON.parse(text));
          } catch (error) {
            reject(error);
          }
        });
      }
    );
    request.on("error", reject);
    request.on("timeout", () => {
      request.destroy(new Error("Bridge request timed out."));
    });
    request.write(body);
    request.end();
  });
}

async function insertText(text) {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    return;
  }
  await editor.edit((editBuilder) => {
    editBuilder.insert(editor.selection.active, text);
  });
}

module.exports = {
  activate,
  deactivate
};
