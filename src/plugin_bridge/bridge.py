"""Plugin bridge primitives for local editor/browser integrations."""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Any, Callable


@dataclass
class PluginBridgeConfig:
    enabled: bool = False
    host: str = "127.0.0.1"
    ipc_port: int = 17890
    max_body_bytes: int = 64 * 1024
    max_text_chars: int = 8000
    auth_token: str | None = None
    force_no_paste: bool = True


class BridgeBusyError(RuntimeError):
    """Raised when the bridge is already processing a request."""


class PluginBridge:
    """
    Side-effect-free bridge used by VS Code/Cursor/Chrome integrations.

    The bridge returns compiled text to the caller. It does not own editor
    insertion, clipboard writes, or Ctrl+V behavior.
    """

    def __init__(
        self,
        process_fn: Callable[..., Any] | None = None,
        config: PluginBridgeConfig | None = None,
    ):
        self.process_fn = process_fn
        self.config = config or PluginBridgeConfig()
        self._process_lock = threading.RLock()
        self._busy = False

    @property
    def busy(self) -> bool:
        return self._busy

    def process_text(
        self,
        raw_text: str,
        mode: str = "cursor_prompt",
        *,
        use_fast: bool = False,
        output_script: str | None = None,
    ) -> Any:
        if not self.process_fn:
            raise RuntimeError("PluginBridge: process_fn not configured")
        if not self._process_lock.acquire(blocking=False):
            raise BridgeBusyError("PluginBridge: busy")
        self._busy = True
        try:
            return self.process_fn(
                raw_text,
                mode,
                use_fast=use_fast,
                output_script=output_script,
            )
        finally:
            self._busy = False
            self._process_lock.release()

    def get_status(self) -> dict[str, Any]:
        return {
            "bridge": "plugin_bridge",
            "enabled": self.config.enabled,
            "host": self.config.host,
            "port": self.config.ipc_port,
            "busy": self.busy,
            "force_no_paste": self.config.force_no_paste,
            "auth_required": bool(self.config.auth_token),
            "max_body_bytes": self.config.max_body_bytes,
            "max_text_chars": self.config.max_text_chars,
        }


def serialize_bridge_outcome(outcome: Any, *, include_debug: bool = False) -> dict[str, Any]:
    """Convert an AuditResult or bridge outcome dict into a stable response."""
    record_id = None
    pasted = False
    debug: dict[str, Any] = {}
    meta: dict[str, Any] = {}

    if isinstance(outcome, dict) and "result" in outcome:
        result = outcome.get("result")
        record_id = outcome.get("record_id")
        pasted = bool(outcome.get("pasted", False))
        debug = dict(outcome.get("debug") or {})
        meta = dict(outcome.get("meta") or {})
    else:
        result = outcome

    if hasattr(result, "to_dict"):
        result_payload = result.to_dict()
    elif hasattr(result, "model_dump"):
        result_payload = result.model_dump(by_alias=True)
    elif isinstance(result, dict):
        result_payload = dict(result)
    else:
        result_payload = {"final_text": str(result or "")}

    response: dict[str, Any] = {
        "ok": True,
        "schema_version": 1,
        "bridge": "plugin_bridge",
        "final_text": str(result_payload.get("final_text") or ""),
        "result": result_payload,
        "meta": meta,
        "record_id": record_id,
        "pasted": pasted,
        "auto_paste_allowed": False,
    }
    if include_debug:
        response["debug"] = _compact_debug(debug)
    return response


def _compact_debug(debug: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in debug.items():
        if isinstance(value, str):
            compact[key] = value[:500]
        elif isinstance(value, (int, float, bool)) or value is None:
            compact[key] = value
        elif isinstance(value, list):
            compact[key] = value[:20]
        elif isinstance(value, dict):
            nested: dict[str, Any] = {}
            for nested_key, nested_value in list(value.items())[:20]:
                if isinstance(nested_value, str):
                    nested[str(nested_key)] = nested_value[:300]
                elif isinstance(nested_value, (int, float, bool)) or nested_value is None:
                    nested[str(nested_key)] = nested_value
            compact[key] = nested
    return compact
