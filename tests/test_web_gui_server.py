from __future__ import annotations

import http.client
import json
import mimetypes
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator
from urllib.parse import urlparse

import pytest

from src.gui import web_gui as web_gui_module
from src.gui.web import WebGuiServer, find_free_port
from src.gui.web import server as server_module
from src.gui.web_gui import ASSETS_DIR, WebGuiController


class FakeRecorder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def stop(self) -> None:
        self.calls.append("stop")

    def close(self) -> None:
        self.calls.append("close")


class FakeApp:
    default_mode = "cursor_prompt"
    output_cfg = {"script": "simplified"}
    config = {"hotkeys": {"gui_toggle": "ctrl+."}}

    def __init__(self) -> None:
        self.recorder = FakeRecorder()


@contextmanager
def _running(controller: WebGuiController) -> Iterator[int]:
    url = controller.start_server()
    port = urlparse(url).port
    assert port is not None
    try:
        yield port
    finally:
        server_thread = controller._server_thread
        controller.shutdown()
        if server_thread is not None:
            server_thread.join(timeout=2)


def _request(
    port: int,
    method: str,
    path: str,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    data = response.read()
    response_headers = {key.lower(): value for key, value in response.getheaders()}
    connection.close()
    return response.status, response_headers, data


def _assert_json_response(
    response: tuple[int, dict[str, str], bytes],
    expected: dict[str, Any],
) -> None:
    status, headers, data = response
    assert status == 200
    assert headers["content-type"] == "application/json; charset=utf-8"
    assert headers["cache-control"] == "no-store"
    assert headers["content-length"] == str(len(data))
    assert json.loads(data.decode("utf-8")) == expected


def test_server_is_exported_owned_and_does_not_import_controller():
    controller = WebGuiController(FakeApp())
    assert isinstance(controller._web_gui_server, WebGuiServer)
    assert WebGuiServer is server_module.WebGuiServer
    assert find_free_port is server_module.find_free_port
    source = Path(server_module.__file__).read_text(encoding="utf-8")
    assert "from src.gui.web_gui" not in source


def test_real_server_routes_call_current_controller_facades_with_exact_envelopes(monkeypatch):
    controller = WebGuiController(FakeApp())
    calls = []

    with _running(controller) as port:
        monkeypatch.setattr(controller, "bootstrap", lambda: {"route": "bootstrap", "文本": "你好"})
        monkeypatch.setattr(controller, "get_state", lambda: {"route": "state"})

        def route(name):
            def call(payload):
                calls.append((name, payload))
                return {"route": name, "payload": payload}

            return call

        monkeypatch.setattr(controller, "start_recording", route("start"))
        monkeypatch.setattr(controller, "toggle_recording", route("toggle"))
        monkeypatch.setattr(controller, "apply_theme_color", route("theme"))
        monkeypatch.setattr(controller, "update_settings", route("settings"))
        monkeypatch.setattr(controller, "confirm_text", route("confirm"))
        monkeypatch.setattr(controller, "stop_recording", lambda: {"route": "stop"})

        bootstrap = _request(port, "GET", "/api/bootstrap?fresh=1")
        _assert_json_response(bootstrap, {"route": "bootstrap", "文本": "你好"})
        assert "你好".encode("utf-8") in bootstrap[2]
        assert b"\\u4f60" not in bootstrap[2]
        _assert_json_response(_request(port, "GET", "/api/state"), {"route": "state"})

        payload = {"文本": "编辑", "value": 3}
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json", "Content-Length": str(len(encoded))}
        for path, name in (
            ("/api/start", "start"),
            ("/api/toggle", "toggle"),
            ("/api/theme", "theme"),
            ("/api/settings", "settings"),
            ("/api/confirm", "confirm"),
        ):
            _assert_json_response(
                _request(port, "POST", path, encoded, headers),
                {"route": name, "payload": payload},
            )
        _assert_json_response(
            _request(port, "POST", "/api/stop", encoded, headers),
            {"route": "stop"},
        )

        monkeypatch.setattr(
            controller,
            "confirm_text",
            lambda payload: {"ok": False, "error": "业务失败", "state": {"phase": "done"}},
        )
        failure = _request(port, "POST", "/api/confirm", encoded, headers)
        _assert_json_response(
            failure,
            {"ok": False, "error": "业务失败", "state": {"phase": "done"}},
        )

    assert calls == [
        (name, payload)
        for name in ("start", "toggle", "theme", "settings", "confirm")
    ]


def test_invalid_missing_json_and_unknown_post_preserve_read_order(monkeypatch):
    controller = WebGuiController(FakeApp())
    decoded = []
    original_loads = json.loads

    def tracking_loads(value):
        decoded.append(value)
        return original_loads(value)

    monkeypatch.setattr(
        web_gui_module,
        "json",
        SimpleNamespace(
            loads=tracking_loads,
            dumps=json.dumps,
            JSONDecodeError=json.JSONDecodeError,
        ),
    )
    settings_payloads = []
    toggle_payloads = []
    with _running(controller) as port:
        monkeypatch.setattr(
            controller,
            "update_settings",
            lambda payload: settings_payloads.append(payload) or {"payload": payload},
        )
        monkeypatch.setattr(
            controller,
            "toggle_recording",
            lambda payload: toggle_payloads.append(payload) or {"payload": payload},
        )
        invalid = b"{invalid"
        _assert_json_response(
            _request(
                port,
                "POST",
                "/api/settings",
                invalid,
                {"Content-Length": str(len(invalid))},
            ),
            {"payload": {}},
        )
        _assert_json_response(_request(port, "POST", "/api/toggle", b""), {"payload": {}})
        unknown = b'{"unknown": true}'
        response = _request(
            port,
            "POST",
            "/api/unknown",
            unknown,
            {"Content-Length": str(len(unknown))},
        )
        assert response[0] == 404

    assert settings_payloads == [{}]
    assert toggle_payloads == [{}]
    assert decoded == ["{invalid", '{"unknown": true}']


def test_handler_preserves_content_length_int_conversion():
    controller = WebGuiController(FakeApp())
    handler = controller._make_handler()
    request = SimpleNamespace(headers={"Content-Length": "not-an-int"})
    with pytest.raises(ValueError):
        handler._read_json(request)


def test_static_root_mime_headers_missing_and_traversal():
    controller = WebGuiController(FakeApp())
    index = (ASSETS_DIR / "index.html").read_bytes()
    script_path = ASSETS_DIR / "main.js"
    script = script_path.read_bytes()
    with _running(controller) as port:
        root = _request(port, "GET", "/")
        explicit_index = _request(port, "GET", "/index.html")
        for response in (root, explicit_index):
            status, headers, data = response
            assert status == 200
            assert data == index
            assert headers["content-type"] == mimetypes.guess_type(str(ASSETS_DIR / "index.html"))[0]
            assert headers["cache-control"] == "no-store"
            assert headers["content-length"] == str(len(index))

        status, headers, data = _request(port, "GET", "/main.js")
        assert status == 200
        assert data == script
        assert headers["content-type"] == mimetypes.guess_type(str(script_path))[0]
        assert headers["cache-control"] == "no-store"
        assert headers["content-length"] == str(len(script))
        assert _request(port, "GET", "/missing.asset")[0] == 404
        assert _request(port, "GET", "/../web_gui.py")[0] == 403
        assert _request(port, "GET", "/api/unknown")[0] == 404


def test_start_server_dynamically_passes_factory_thread_and_port(monkeypatch):
    controller = WebGuiController(FakeApp())
    captured = []
    server_factory = object()
    thread_factory = object()
    find_port = lambda: 6123

    def delegate(**kwargs):
        captured.append(kwargs)
        return "delegated"

    monkeypatch.setattr(controller._web_gui_server, "start_server", delegate)
    monkeypatch.setattr(web_gui_module, "ThreadingHTTPServer", server_factory)
    monkeypatch.setattr(web_gui_module.threading, "Thread", thread_factory)
    monkeypatch.setattr(web_gui_module, "_find_free_port", find_port)
    assert controller.start_server() == "delegated"
    assert captured == [
        {
            "server_factory": server_factory,
            "thread_factory": thread_factory,
            "find_port": find_port,
        }
    ]


def test_make_handler_dynamically_passes_current_module_dependencies(monkeypatch, tmp_path):
    controller = WebGuiController(FakeApp())
    captured = []
    handler_base = type("HandlerBase", (), {})
    parse_url = lambda value: value
    loads = lambda value: {}
    dumps = lambda value, **kwargs: "{}"
    decode_error = type("DecodeError", (ValueError,), {})
    guess_type = lambda value: ("test/type", None)
    statuses = SimpleNamespace(OK=201, NOT_FOUND=498, FORBIDDEN=499)

    def delegate(**kwargs):
        captured.append(kwargs)
        return "handler"

    monkeypatch.setattr(controller._web_gui_server, "_make_handler", delegate)
    monkeypatch.setattr(web_gui_module, "ASSETS_DIR", tmp_path)
    monkeypatch.setattr(web_gui_module, "BaseHTTPRequestHandler", handler_base)
    monkeypatch.setattr(web_gui_module, "urlparse", parse_url)
    monkeypatch.setattr(web_gui_module.json, "loads", loads)
    monkeypatch.setattr(web_gui_module.json, "dumps", dumps)
    monkeypatch.setattr(web_gui_module.json, "JSONDecodeError", decode_error)
    monkeypatch.setattr(web_gui_module.mimetypes, "guess_type", guess_type)
    monkeypatch.setattr(web_gui_module, "HTTPStatus", statuses)
    assert controller._make_handler() == "handler"
    assert captured == [
        {
            "handler_base": handler_base,
            "assets_dir": tmp_path,
            "parse_url": parse_url,
            "json_loads": loads,
            "json_dumps": dumps,
            "json_decode_error": decode_error,
            "guess_type": guess_type,
            "ok": 201,
            "not_found": 498,
            "forbidden": 499,
        }
    ]


def test_service_start_preserves_server_thread_identity_target_and_start(monkeypatch):
    controller = WebGuiController(FakeApp())
    handler = type("Handler", (), {})
    monkeypatch.setattr(controller, "_make_handler", lambda: handler)
    created = []

    class FakeServer:
        server_address = ("127.0.0.1", 7001)

        def __init__(self, address, passed_handler):
            self.address = address
            self.handler = passed_handler

        def serve_forever(self):
            return None

    class FakeThread:
        def __init__(self, *, target, daemon):
            self.target = target
            self.daemon = daemon
            self.started = False
            created.append(self)

        def start(self):
            self.started = True

    result = controller._web_gui_server.start_server(
        server_factory=FakeServer,
        thread_factory=FakeThread,
        find_port=lambda: 7000,
    )
    assert result == "http://127.0.0.1:7001/"
    assert isinstance(controller._server, FakeServer)
    assert controller._server.address == ("127.0.0.1", 7000)
    assert controller._server.handler is handler
    assert controller._server_thread is created[0]
    assert created[0].target == controller._server.serve_forever
    assert created[0].daemon is True
    assert created[0].started is True


def test_controller_shutdown_preserves_order_identity_none_timing_and_thread():
    controller = WebGuiController(FakeApp())
    events = []
    thread = object()

    class FakeServer:
        def shutdown(self):
            assert controller._server is self
            events.append("shutdown")

        def server_close(self):
            assert controller._server is self
            events.append("close")

    server = FakeServer()
    controller._server = server
    controller._server_thread = thread
    controller._recording = True
    controller.app.recorder.calls = events
    controller.shutdown()
    assert events == ["stop", "close", "shutdown", "close"]
    assert controller._server is None
    assert controller._server_thread is thread
    assert controller._stop_threads.is_set()


def test_find_free_port_wrapper_preserves_socket_algorithm(monkeypatch):
    calls = []

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            calls.append("exit")

        def bind(self, address):
            calls.append(("bind", address))

        def getsockname(self):
            return ("127.0.0.1", "6543")

    def socket_factory(family, kind):
        calls.append(("socket", family, kind))
        return FakeSocket()

    monkeypatch.setattr(web_gui_module.socket, "socket", socket_factory)
    assert web_gui_module._find_free_port() == 6543
    assert calls == [
        ("socket", server_module.socket.AF_INET, server_module.socket.SOCK_STREAM),
        ("bind", ("127.0.0.1", 0)),
        "exit",
    ]
