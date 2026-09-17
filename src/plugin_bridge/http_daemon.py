"""Local HTTP daemon for editor/browser plugin integrations."""

from __future__ import annotations

import json
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from src.plugin_bridge.bridge import (
    BridgeBusyError,
    PluginBridge,
    PluginBridgeConfig,
    serialize_bridge_outcome,
)


ALLOWED_MODES = {
    "ai_chat",
    "cursor_prompt",
    "normal_dictation",
    "terminal_command",
    "git_message",
}
ALLOWED_SCRIPTS = {"simplified", "traditional", "auto"}


class PluginBridgeServer:
    """Small lifecycle wrapper around ThreadingHTTPServer."""

    def __init__(self, bridge: PluginBridge, server: ThreadingHTTPServer):
        self.bridge = bridge
        self.server = server
        self._thread: threading.Thread | None = None

    @property
    def server_address(self) -> tuple[str, int]:
        host, port = self.server.server_address[:2]
        return str(host), int(port)

    @property
    def url(self) -> str:
        host, port = self.server_address
        return f"http://{host}:{port}"

    def start(self) -> "PluginBridgeServer":
        if self._thread is None:
            self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self._thread.start()
        return self

    def shutdown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None


def create_server(bridge: PluginBridge, host: str | None = None, port: int | None = None) -> PluginBridgeServer:
    config = bridge.config
    bind_host = host or config.host
    if bind_host not in {"127.0.0.1", "localhost"}:
        raise ValueError("Plugin bridge daemon only supports local loopback bind by default")
    bind_port = config.ipc_port if port is None else port
    handler = make_handler(bridge)
    server = ThreadingHTTPServer((bind_host, bind_port), handler)
    config.host = str(server.server_address[0])
    config.ipc_port = int(server.server_address[1])
    config.enabled = True
    return PluginBridgeServer(bridge, server)


def make_handler(bridge: PluginBridge):
    class PluginBridgeHandler(BaseHTTPRequestHandler):
        server_version = "YiyaweiPluginBridge/0.1"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self._send_json(
                    {
                        "ok": True,
                        "service": "voice-prompt-compiler-bridge",
                        "schema_version": 1,
                    }
                )
                return
            if parsed.path == "/status":
                if not self._authorized():
                    self._send_error_json(HTTPStatus.UNAUTHORIZED, "unauthorized")
                    return
                self._send_json({"ok": True, "status": bridge.get_status()})
                return
            self._send_error_json(HTTPStatus.NOT_FOUND, "not_found")

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path not in {"/v1/process-text", "/process-text"}:
                self._send_error_json(HTTPStatus.NOT_FOUND, "not_found")
                return
            if not self._authorized():
                self._send_error_json(HTTPStatus.UNAUTHORIZED, "unauthorized")
                return

            payload = self._read_json_body()
            if not isinstance(payload, dict):
                return

            request, error = _validate_process_payload(payload, bridge.config)
            if error:
                self._send_error_json(HTTPStatus.BAD_REQUEST, error)
                return

            started = time.perf_counter()
            try:
                outcome = bridge.process_text(
                    request["raw_text"],
                    request["mode"],
                    use_fast=request["use_fast"],
                    output_script=request["output_script"],
                )
            except BridgeBusyError:
                self._send_error_json(HTTPStatus.TOO_MANY_REQUESTS, "bridge_busy")
                return
            except Exception as exc:
                self._send_error_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    "processing_failed",
                    detail=str(exc)[:300] or exc.__class__.__name__,
                )
                return

            response = serialize_bridge_outcome(outcome, include_debug=request["include_debug"])
            response.setdefault("meta", {})
            response["meta"].update(
                {
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    "used_fast": request["use_fast"],
                    "mode": request["mode"],
                    "output_script": request["output_script"],
                    "auto_paste_allowed": False,
                }
            )
            self._send_json(response)

        def _authorized(self) -> bool:
            token = bridge.config.auth_token
            if not token:
                return True
            expected = f"Bearer {token}"
            return self.headers.get("Authorization", "") == expected

        def _read_json_body(self) -> dict[str, Any] | None:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_content_length")
                return None
            if length <= 0:
                self._send_error_json(HTTPStatus.BAD_REQUEST, "empty_body")
                return None
            if length > bridge.config.max_body_bytes:
                self._drain_request_body(length)
                self._send_error_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "body_too_large")
                return None
            content_type = self.headers.get("Content-Type", "")
            if content_type and "application/json" not in content_type:
                self._send_error_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "json_required")
                return None
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_json")
                return None
            if not isinstance(payload, dict):
                self._send_error_json(HTTPStatus.BAD_REQUEST, "json_object_required")
                return None
            return payload

        def _drain_request_body(self, length: int) -> None:
            remaining = min(length, 1024 * 1024)
            while remaining > 0:
                chunk = self.rfile.read(min(8192, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)

        def _send_json(self, payload: dict[str, Any], status: int = HTTPStatus.OK) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(int(status))
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_error_json(
            self,
            status: HTTPStatus,
            error: str,
            *,
            detail: str | None = None,
        ) -> None:
            payload: dict[str, Any] = {
                "ok": False,
                "schema_version": 1,
                "error": error,
            }
            if detail:
                payload["detail"] = detail
            self._send_json(payload, int(status))

    return PluginBridgeHandler


def _validate_process_payload(
    payload: dict[str, Any],
    config: PluginBridgeConfig,
) -> tuple[dict[str, Any], str | None]:
    raw_text = payload.get("raw_text", payload.get("text"))
    if not isinstance(raw_text, str) or not raw_text.strip():
        return {}, "raw_text_required"
    raw_text = raw_text.strip()
    if len(raw_text) > config.max_text_chars:
        return {}, "raw_text_too_large"

    mode = payload.get("mode") or "cursor_prompt"
    if mode not in ALLOWED_MODES:
        return {}, "invalid_mode"

    output_script = payload.get("output_script") or "simplified"
    if output_script not in ALLOWED_SCRIPTS:
        return {}, "invalid_output_script"

    return (
        {
            "raw_text": raw_text,
            "mode": str(mode),
            "use_fast": bool(payload.get("use_fast", False)),
            "output_script": str(output_script),
            "include_debug": bool(payload.get("include_debug", False)),
        },
        None,
    )
