from __future__ import annotations

import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from src.auditor.schema import AuditResult
from src.plugin_bridge.bridge import PluginBridge, PluginBridgeConfig
from src.plugin_bridge.http_daemon import create_server


def _read_json(url: str, *, data: dict | bytes | None = None, token: str | None = None) -> tuple[int, dict]:
    headers = {}
    body = None
    if data is not None:
        headers["Content-Type"] = "application/json"
        body = data if isinstance(data, bytes) else json.dumps(data).encode("utf-8")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=body, headers=headers)
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


@pytest.fixture
def bridge_server():
    calls: list[dict] = []

    def fake_process(raw_text: str, mode: str, *, use_fast: bool = False, output_script: str | None = None):
        calls.append(
            {
                "raw_text": raw_text,
                "mode": mode,
                "use_fast": use_fast,
                "output_script": output_script,
            }
        )
        return {
            "result": AuditResult(
                final_text=f"compiled:{raw_text}",
                mode=mode,  # type: ignore[arg-type]
                intent_summary="bridge test",
                risk_level="low",
                need_confirm=False,
            ),
            "debug": {"raw_asr_text": raw_text, "llm_raw_response": "x" * 600},
            "meta": {"llm_model": "fake"},
        }

    bridge = PluginBridge(
        fake_process,
        PluginBridgeConfig(enabled=True, host="127.0.0.1", ipc_port=0, max_body_bytes=256),
    )
    server = create_server(bridge, port=0).start()
    try:
        yield server, calls
    finally:
        server.shutdown()


def test_health_and_status_endpoints(bridge_server):
    server, _calls = bridge_server

    status, payload = _read_json(f"{server.url}/health")
    assert status == 200
    assert payload["ok"] is True
    assert payload["service"] == "voice-prompt-compiler-bridge"

    status, payload = _read_json(f"{server.url}/status")
    assert status == 200
    assert payload["ok"] is True
    assert payload["status"]["host"] == "127.0.0.1"
    assert payload["status"]["force_no_paste"] is True


def test_process_text_success_uses_injected_bridge(bridge_server):
    server, calls = bridge_server

    status, payload = _read_json(
        f"{server.url}/v1/process-text",
        data={
            "raw_text": "  帮我整理一下这个需求  ",
            "mode": "cursor_prompt",
            "use_fast": True,
            "output_script": "simplified",
            "include_debug": True,
        },
    )

    assert status == 200
    assert payload["ok"] is True
    assert payload["final_text"] == "compiled:帮我整理一下这个需求"
    assert payload["result"]["mode"] == "cursor_prompt"
    assert payload["result"]["risk_level"] == "low"
    assert payload["pasted"] is False
    assert payload["auto_paste_allowed"] is False
    assert payload["meta"]["used_fast"] is True
    assert payload["debug"]["llm_raw_response"] == "x" * 500
    assert calls == [
        {
            "raw_text": "帮我整理一下这个需求",
            "mode": "cursor_prompt",
            "use_fast": True,
            "output_script": "simplified",
        }
    ]


def test_process_text_defaults_mode_and_script(bridge_server):
    server, calls = bridge_server

    status, payload = _read_json(f"{server.url}/process-text", data={"text": "普通短句"})

    assert status == 200
    assert payload["result"]["mode"] == "cursor_prompt"
    assert calls[-1]["mode"] == "cursor_prompt"
    assert calls[-1]["output_script"] == "simplified"


def test_invalid_json_is_rejected_without_processing(bridge_server):
    server, calls = bridge_server

    status, payload = _read_json(f"{server.url}/v1/process-text", data=b'{"raw_text":')

    assert status == 400
    assert payload["ok"] is False
    assert payload["error"] == "invalid_json"
    assert calls == []


def test_oversize_body_is_rejected_without_processing(bridge_server):
    server, calls = bridge_server
    too_large = {"raw_text": "x" * 400}

    status, payload = _read_json(f"{server.url}/v1/process-text", data=too_large)

    assert status == 413
    assert payload["ok"] is False
    assert payload["error"] == "body_too_large"
    assert calls == []


def test_auth_token_protects_status_and_processing():
    calls: list[str] = []

    def fake_process(raw_text: str, mode: str, *, use_fast: bool = False, output_script: str | None = None):
        calls.append(raw_text)
        return AuditResult(final_text="ok", mode=mode)  # type: ignore[arg-type]

    bridge = PluginBridge(
        fake_process,
        PluginBridgeConfig(
            enabled=True,
            host="127.0.0.1",
            ipc_port=0,
            auth_token="secret",
        ),
    )
    server = create_server(bridge, port=0).start()
    try:
        status, payload = _read_json(f"{server.url}/health")
        assert status == 200
        assert payload["ok"] is True

        status, payload = _read_json(f"{server.url}/status")
        assert status == 401
        assert payload["error"] == "unauthorized"

        status, payload = _read_json(f"{server.url}/v1/process-text", data={"raw_text": "hi"})
        assert status == 401
        assert payload["error"] == "unauthorized"
        assert calls == []

        status, payload = _read_json(
            f"{server.url}/v1/process-text",
            data={"raw_text": "hi"},
            token="secret",
        )
        assert status == 200
        assert payload["final_text"] == "ok"
        assert calls == ["hi"]
    finally:
        server.shutdown()
