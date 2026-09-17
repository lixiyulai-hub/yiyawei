"""HTTP server lifecycle and request handling for the local web GUI."""

from __future__ import annotations

import socket
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol


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

    def __init__(self, host: ServerHost):
        self.host = host

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
        server_host, port = host._server.server_address
        host._server_thread = thread_factory(target=host._server.serve_forever, daemon=True)
        host._server_thread.start()
        return f"http://{server_host}:{port}/"

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
                    self._send_json(host.bootstrap())
                    return
                if parsed.path == "/api/state":
                    self._send_json(host.get_state())
                    return
                self._serve_static(parsed.path)

            def do_POST(self) -> None:
                parsed = parse_url(self.path)
                payload = self._read_json()
                if parsed.path == "/api/start":
                    self._send_json(host.start_recording(payload))
                    return
                if parsed.path == "/api/stop":
                    self._send_json(host.stop_recording())
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
                self.send_error(not_found)

            def _read_json(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0:
                    return {}
                raw = self.rfile.read(length)
                try:
                    return json_loads(raw.decode("utf-8"))
                except json_decode_error:
                    return {}

            def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
                data = json_dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _serve_static(self, path: str) -> None:
                relative = "index.html" if path in {"", "/"} else path.lstrip("/")
                target = (assets_dir / relative).resolve()
                if assets_dir.resolve() not in target.parents and target != assets_dir.resolve():
                    self.send_error(forbidden)
                    return
                if not target.exists() or not target.is_file():
                    self.send_error(not_found)
                    return
                data = target.read_bytes()
                content_type = guess_type(str(target))[0] or "application/octet-stream"
                self.send_response(ok)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        return WebGuiHandler
