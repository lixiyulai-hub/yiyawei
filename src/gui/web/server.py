"""HTTP server lifecycle and request handling for the local web GUI."""

from __future__ import annotations

import socket
from collections.abc import Callable
from http.cookies import SimpleCookie
import hmac
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, urlencode


DEFAULT_MAX_BODY_BYTES = 64 * 1024
SESSION_COOKIE_NAME = "vpc_web_session"


class ServerHost(Protocol):
    _server: Any
    _server_thread: Any

    def _make_handler(self) -> type: ...

    def bootstrap(self) -> dict[str, Any]: ...

    def get_state(self) -> dict[str, Any]: ...

    def start_recording(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def stop_recording(self) -> dict[str, Any]: ...

    def toggle_recording(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def apply_theme_color(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def confirm_text(self, payload: dict[str, Any]) -> dict[str, Any]: ...


def find_free_port(
    socket_factory: Callable[..., Any] | None = None,
) -> int:
    """Reserve an ephemeral loopback port using the legacy lookup algorithm."""

    create_socket = socket_factory or socket.socket
    with create_socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class WebGuiServer:
    """Own the web GUI HTTP server while preserving controller facades."""

    def __init__(
        self,
        host: ServerHost,
        *,
        session_token: str,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    ):
        self.host = host
        self.session_token = session_token
        self.max_body_bytes = max(1024, int(max_body_bytes))

    def start_server(
        self,
        *,
        server_factory: Callable[..., Any],
        thread_factory: Callable[..., Any],
        find_port: Callable[[], int],
    ) -> str:
        host = self.host
        handler = host._make_handler()
        host._server = server_factory(("127.0.0.1", find_port()), handler)
        host._server.web_gui_session_token = self.session_token
        host._server.web_gui_max_body_bytes = self.max_body_bytes
        server_host, port = host._server.server_address
        host._server_thread = thread_factory(target=host._server.serve_forever, daemon=True)
        host._server_thread.start()
        return f"http://{server_host}:{port}/?{urlencode({'session': self.session_token})}"

    def shutdown(self) -> None:
        host = self.host
        if host._server is not None:
            host._server.shutdown()
            host._server.server_close()
            host._server = None

    def _make_handler(
        self,
        *,
        handler_base: type,
        assets_dir: Path,
        parse_url: Callable[[str], Any],
        json_loads: Callable[[str], Any],
        json_dumps: Callable[..., str],
        json_decode_error: type[ValueError],
        guess_type: Callable[[str], tuple[str | None, str | None]],
        ok: Any,
        not_found: Any,
        forbidden: Any,
    ) -> type:
        host = self.host

        class WebGuiHandler(handler_base):
            def log_message(self, format: str, *args: Any) -> None:
                return

            def do_GET(self) -> None:
                parsed = parse_url(self.path)
                if parsed.path == "/api/bootstrap":
                    if not self._authorized(parsed):
                        self._send_error_json(401, "unauthorized")
                        return
                    self._send_json(host.bootstrap())
                    return
                if parsed.path == "/api/state":
                    if not self._authorized(parsed):
                        self._send_error_json(401, "unauthorized")
                        return
                    self._send_json(host.get_state())
                    return
                # Static UI assets contain no session data. Keeping them
                # unauthenticated lets CSS imports and ES modules load
                # reliably in Chromium app mode; API routes remain protected.
                self._serve_static(parsed.path)

            def do_POST(self) -> None:
                parsed = parse_url(self.path)
                if not self._authorized(parsed):
                    self._send_error_json(401, "unauthorized")
                    return
                if parsed.path == "/api/stop":
                    self._send_json(host.stop_recording())
                    return
                payload = self._read_json()
                if payload is None:
                    return
                if parsed.path == "/api/start":
                    self._send_json(host.start_recording(payload))
                    return
                if parsed.path == "/api/toggle":
                    self._send_json(host.toggle_recording(payload))
                    return
                if parsed.path == "/api/theme":
                    self._send_json(host.apply_theme_color(payload))
                    return
                if parsed.path == "/api/settings":
                    self._send_json(host.update_settings(payload))
                    return
                if parsed.path == "/api/confirm":
                    self._send_json(host.confirm_text(payload))
                    return
                self._send_error_json(not_found, "not_found")

            def _authorized(self, parsed: Any) -> bool:
                query_token = (parse_qs(parsed.query).get("session") or [""])[0]
                cookie = SimpleCookie()
                cookie.load(self.headers.get("Cookie", ""))
                cookie_token = cookie.get(SESSION_COOKIE_NAME)
                cookie_value = cookie_token.value if cookie_token else ""
                return bool(
                    hmac.compare_digest(query_token, self.server_session_token)
                    or hmac.compare_digest(cookie_value, self.server_session_token)
                )

            def _read_json(self) -> dict[str, Any] | None:
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    self._send_error_json(400, "invalid_content_length")
                    return None
                if length <= 0:
                    self._send_error_json(400, "empty_body")
                    return None
                if length > self.max_body_bytes:
                    self._drain_request_body(length)
                    self._send_error_json(413, "body_too_large")
                    return None
                content_type = self.headers.get("Content-Type", "")
                if content_type and "application/json" not in content_type:
                    self._send_error_json(415, "json_required")
                    return None
                raw = self.rfile.read(length)
                try:
                    payload = json_loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json_decode_error):
                    self._send_error_json(400, "invalid_json")
                    return None
                if not isinstance(payload, dict):
                    self._send_error_json(400, "json_object_required")
                    return None
                return payload

            def _drain_request_body(self, length: int) -> None:
                remaining = min(length, 1024 * 1024)
                while remaining > 0:
                    chunk = self.rfile.read(min(8192, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)

            def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
                data = json_dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _send_error_json(self, status: int, error: str) -> None:
                self._send_json(
                    {"ok": False, "schema_version": 1, "error": error},
                    status,
                )

            def _serve_static(self, path: str) -> None:
                relative = "index.html" if path in {"", "/"} else path.lstrip("/")
                target = (assets_dir / relative).resolve()
                if assets_dir.resolve() not in target.parents and target != assets_dir.resolve():
                    self._send_error_json(forbidden, "forbidden")
                    return
                if not target.exists() or not target.is_file():
                    self._send_error_json(not_found, "not_found")
                    return
                data = target.read_bytes()
                content_type = guess_type(str(target))[0] or "application/octet-stream"
                self.send_response(ok)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                self.send_header(
                    "Set-Cookie",
                    f"{SESSION_COOKIE_NAME}={self.server_session_token}; "
                    "Path=/; HttpOnly; SameSite=Strict",
                )
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            @property
            def server_session_token(self) -> str:
                return self.server.web_gui_session_token

            @property
            def max_body_bytes(self) -> int:
                return self.server.web_gui_max_body_bytes

        return WebGuiHandler
