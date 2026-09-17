from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

from src.gui.web_gui import ASSETS_DIR


def _module_url(name: str) -> str:
    return (Path(ASSETS_DIR) / "js" / name).resolve().as_uri()


def _run_node(program: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", "--input-type=module", "--eval", textwrap.dedent(program)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


FAKE_DOM = r"""
class FakeEvent {
  constructor(type, init = {}) {
    this.type = type;
    this.bubbles = Boolean(init.bubbles);
    this.defaultPrevented = false;
    Object.assign(this, init);
  }
  preventDefault() { this.defaultPrevented = true; }
}

class FakeElement {
  constructor(tagName, ownerDocument) {
    this.tagName = tagName.toUpperCase();
    this.ownerDocument = ownerDocument;
    this.parentNode = null;
    this.children = [];
    this.attributes = new Map();
    this.dataset = {};
    this.listeners = new Map();
    this.textContent = "";
    this.title = "";
    this.tabIndex = 0;
    this.name = "";
    this.content = "";
    this._value = "";
    this._classes = new Set();
    this.style = {
      background: "",
      values: new Map(),
      setProperty(name, value) { this.values.set(name, value); },
      getPropertyValue(name) { return this.values.get(name) || ""; },
    };
    this.classList = {
      add: (...names) => { names.forEach((name) => this._classes.add(name)); },
      remove: (...names) => { names.forEach((name) => this._classes.delete(name)); },
      contains: (name) => this._classes.has(name),
      toggle: (name, force) => {
        const enabled = force === undefined ? !this._classes.has(name) : Boolean(force);
        if (enabled) this._classes.add(name);
        else this._classes.delete(name);
        return enabled;
      },
    };
  }
  set className(value) {
    this._classes = new Set(String(value).split(/\s+/).filter(Boolean));
  }
  get className() { return [...this._classes].join(" "); }
  set value(value) { this._value = String(value); }
  get value() {
    if (this.tagName !== "SELECT") return this._value;
    const options = this.options;
    if (options.some((option) => option.value === this._value)) return this._value;
    return options[0]?.value || "";
  }
  get options() { return this.children.filter((child) => child.tagName === "OPTION"); }
  get selectedIndex() { return this.options.findIndex((option) => option.value === this.value); }
  append(...nodes) {
    for (const node of nodes) {
      if (node.parentNode) {
        node.parentNode.children = node.parentNode.children.filter((child) => child !== node);
      }
      node.parentNode = this;
      this.children.push(node);
    }
  }
  appendChild(node) { this.append(node); return node; }
  replaceChildren(...nodes) {
    this.children.forEach((child) => { child.parentNode = null; });
    this.children = [];
    this.append(...nodes);
    if (this.tagName === "SELECT" && this.options.length && !this.options.some(
      (option) => option.value === this._value
    )) this._value = this.options[0].value;
  }
  insertAdjacentElement(position, node) {
    if (position !== "afterend" || !this.parentNode) throw new Error("unsupported insert");
    const index = this.parentNode.children.indexOf(this);
    node.parentNode = this.parentNode;
    this.parentNode.children.splice(index + 1, 0, node);
    return node;
  }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }
  listenerCount(type) { return (this.listeners.get(type) || []).length; }
  dispatchEvent(event) {
    if (!event.target) event.target = this;
    for (const listener of this.listeners.get(event.type) || []) listener(event);
    return !event.defaultPrevented;
  }
  emit(type, init = {}) {
    const event = new FakeEvent(type, init);
    this.dispatchEvent(event);
    return event;
  }
  matches(selector) {
    if (selector.startsWith(".")) return this.classList.contains(selector.slice(1));
    const match = selector.match(/^\[([^=]+)="([^"]+)"\]$/);
    return match ? this.getAttribute(match[1]) === match[2] : false;
  }
  closest(selector) {
    let current = this;
    while (current) {
      if (current.matches(selector)) return current;
      current = current.parentNode;
    }
    return null;
  }
  querySelectorAll(selector) {
    const matches = [];
    const visit = (node) => {
      for (const child of node.children) {
        if (child.matches(selector)) matches.push(child);
        visit(child);
      }
    };
    visit(this);
    return matches;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  contains(node) {
    if (node === this) return true;
    return this.children.some((child) => child.contains(node));
  }
  focus() { this.ownerDocument.activeElement = this; }
  scrollIntoView(options) { this.scrollOptions = options; }
}

class FakeDocument {
  constructor() {
    this.listeners = new Map();
    this.activeElement = null;
    this.defaultView = { Event: FakeEvent };
    this.documentElement = new FakeElement("html", this);
    this.head = new FakeElement("head", this);
  }
  createElement(tagName) { return new FakeElement(tagName, this); }
  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }
  listenerCount(type) { return (this.listeners.get(type) || []).length; }
  emit(type, init = {}) {
    const event = new FakeEvent(type, init);
    for (const listener of this.listeners.get(type) || []) listener(event);
    return event;
  }
  querySelector(selector) {
    if (selector === 'meta[name="theme-color"]') {
      return this.head.children.find(
        (child) => child.tagName === "META" && child.name === "theme-color"
      ) || null;
    }
    return null;
  }
}

function option(documentRef, label, value) {
  const item = documentRef.createElement("option");
  item.textContent = label;
  item.value = value;
  return item;
}
"""


def test_composition_modules_import_without_a_dom_in_node() -> None:
    urls = [
        _module_url("custom-select.js"),
        _module_url("theme-manager.js"),
        _module_url("audio-visualizer.js"),
    ]
    result = _run_node(
        f"""
        import assert from "node:assert/strict";
        assert.equal(typeof globalThis.document, "undefined");
        const [custom, theme, visualizer] = await Promise.all(
          {json.dumps(urls)}.map((url) => import(url)),
        );
        assert.equal(typeof custom.createCustomSelectManager, "function");
        assert.equal(typeof theme.createThemeManager, "function");
        assert.equal(typeof visualizer.updateRecordGlow, "function");
        """
    )

    assert result.stdout == ""
    assert result.stderr == ""


def test_custom_select_manager_preserves_mouse_keyboard_aria_and_swatches() -> None:
    module_url = _module_url("custom-select.js")
    result = _run_node(
        FAKE_DOM
        + f"""
        import assert from "node:assert/strict";
        const {{ createCustomSelectManager }} = await import({json.dumps(module_url)});
        const documentRef = new FakeDocument();
        const manager = createCustomSelectManager({{ documentRef }});
        manager.bind();
        manager.bind();
        assert.equal(documentRef.listenerCount("pointerdown"), 1);
        assert.equal(documentRef.listenerCount("keydown"), 1);

        const field = documentRef.createElement("label");
        field.className = "field";
        const select = documentRef.createElement("select");
        select.replaceChildren(
          option(documentRef, "First", "first"),
          option(documentRef, "Second", "second"),
        );
        field.append(select);
        let changes = 0;
        let lastChange;
        select.addEventListener("change", (event) => {{ changes += 1; lastChange = event; }});

        const controls = manager.ensure(select, {{
          getColors: (value) => value === "first" ? ["#111", "#222"] : ["#333"],
        }});
        const sameControls = manager.ensure(select);
        assert.equal(sameControls, controls);
        assert.equal(field.querySelectorAll(".select-shell").length, 1);
        assert.equal(select.listenerCount("change"), 2);
        assert.equal(select.classList.contains("native-select"), true);
        assert.equal(field.classList.contains("has-custom-select"), true);
        assert.equal(select.tabIndex, -1);
        assert.equal(select.getAttribute("aria-hidden"), "true");
        assert.equal(controls.trigger.getAttribute("role"), "combobox");
        assert.equal(controls.trigger.getAttribute("aria-haspopup"), "listbox");
        assert.equal(controls.trigger.getAttribute("aria-expanded"), "false");
        assert.equal(controls.menu.getAttribute("role"), "listbox");
        assert.equal(controls.value.textContent, "First");
        assert.equal(controls.trigger.title, "First");
        assert.equal(controls.trigger.dataset.value, "first");
        assert.equal(controls.side.querySelector(".select-mini-swatches").children.length, 2);
        assert.equal(controls.menu.querySelectorAll(".select-option").length, 2);
        assert.equal(
          controls.menu.querySelectorAll(".select-option")[0].getAttribute("aria-selected"),
          "true",
        );
        assert.equal(
          controls.menu.querySelectorAll(".select-option")[1]
            .querySelector(".select-option-swatches").children.length,
          1,
        );

        controls.trigger.emit("click");
        assert.equal(controls.shell.classList.contains("is-open"), true);
        assert.equal(controls.trigger.getAttribute("aria-expanded"), "true");
        assert.deepEqual(
          controls.menu.querySelector('[aria-selected="true"]').scrollOptions,
          {{ block: "nearest" }},
        );
        controls.menu.querySelectorAll(".select-option")[1].emit("click");
        assert.equal(select.value, "second");
        assert.equal(changes, 1);
        assert.equal(lastChange.bubbles, true);
        assert.equal(controls.value.textContent, "Second");
        assert.equal(controls.trigger.dataset.value, "second");
        assert.equal(controls.trigger.getAttribute("aria-expanded"), "false");

        select.value = "first";
        select.emit("change");
        controls.trigger.emit("keydown", {{ key: "ArrowDown" }});
        const rows = controls.menu.querySelectorAll(".select-option");
        assert.equal(documentRef.activeElement, rows[1]);
        rows[1].emit("keydown", {{ key: "Enter" }});
        assert.equal(select.value, "second");
        assert.equal(changes, 3);

        controls.trigger.emit("click");
        documentRef.emit("keydown", {{ key: "Escape" }});
        assert.equal(controls.trigger.getAttribute("aria-expanded"), "false");
        controls.trigger.emit("click");
        documentRef.emit("pointerdown", {{ target: documentRef.createElement("div") }});
        assert.equal(controls.trigger.getAttribute("aria-expanded"), "false");

        const plainField = documentRef.createElement("label");
        plainField.className = "field";
        const plainSelect = documentRef.createElement("select");
        plainSelect.replaceChildren(option(documentRef, "Plain", "plain"));
        plainField.append(plainSelect);
        const plain = manager.ensure(plainSelect);
        assert.equal(plain.side.querySelector(".select-mini-swatches"), null);
        assert.equal(plain.menu.querySelector(".select-option-swatches"), null);
        """
    )

    assert result.stdout == ""
    assert result.stderr == ""


def test_theme_manager_preserves_init_persistence_random_timer_and_api_contract() -> None:
    module_url = _module_url("theme-manager.js")
    result = _run_node(
        FAKE_DOM
        + f"""
        import assert from "node:assert/strict";
        const {{ createThemeManager }} = await import({json.dumps(module_url)});

        const documentRef = new FakeDocument();
        const themeSelect = documentRef.createElement("select");
        const themeSwatches = documentRef.createElement("span");
        const storage = new Map([
          ["voice-prompt-compiler-theme", "pearl-rose"],
          ["voice-prompt-compiler-theme-version", "3"],
        ]);
        const writes = [];
        const timeouts = [];
        const intervals = [];
        const clearedIntervals = [];
        const windowRef = {{
          localStorage: {{
            getItem: (key) => storage.get(key) ?? null,
            setItem(key, value) {{ storage.set(key, value); writes.push([key, value]); }},
          }},
          setTimeout(callback, delay) {{ timeouts.push({{ callback, delay }}); return timeouts.length; }},
          setInterval(callback, delay) {{
            const timer = {{ id: intervals.length + 1, callback, delay }};
            intervals.push(timer);
            return timer.id;
          }},
          clearInterval(id) {{ clearedIntervals.push(id); }},
        }};
        const apiCalls = [];
        const api = async (path, options) => {{ apiCalls.push({{ path, options }}); return {{ ok: true }}; }};
        const ensured = [];
        const synced = [];
        const customSelectManager = {{
          ensure(select, options) {{ ensured.push({{ select, options }}); }},
          sync(select) {{ synced.push(select); }},
        }};
        let visualizerSyncs = 0;
        const manager = createThemeManager({{
          elements: {{ themeSelect, themeSwatches }},
          api,
          audioCapsuleVisualizer: {{ syncTheme() {{ visualizerSyncs += 1; }} }},
          customSelectManager,
          documentRef,
          windowRef,
        }});

        manager.init();
        assert.equal(themeSelect.options.length, 51);
        assert.equal(themeSelect.options[0].value, "auto-random");
        assert.equal(ensured.length, 1);
        assert.deepEqual(ensured[0].options.getColors("aurora-blue"), ["#f7fbff", "#b5d8fc", "#4f91d9"]);
        assert.equal(themeSelect.listenerCount("change"), 1);
        assert.equal(documentRef.documentElement.dataset.theme, "pearl-rose");
        assert.equal(documentRef.documentElement.dataset.contrast, "light");
        assert.equal(documentRef.documentElement.dataset.themeMode, "fixed");
        assert.equal(themeSelect.value, "pearl-rose");
        assert.deepEqual(themeSwatches.children.map((item) => item.style.background), [
          "#fffafa", "#ffd5dd", "#d8788c",
        ]);
        assert.equal(visualizerSyncs, 1);
        assert.equal(synced.length, 1);
        assert.equal(writes.length, 0);
        assert.equal(apiCalls.length, 1);
        assert.equal(apiCalls[0].path, "/api/theme");
        assert.equal(apiCalls[0].options.method, "POST");
        assert.deepEqual(JSON.parse(apiCalls[0].options.body), {{
          theme: "pearl-rose", color: "#fff0f2",
        }});
        assert.equal(timeouts[0].delay, 600);
        timeouts.shift().callback();
        assert.equal(apiCalls.length, 2);
        assert.deepEqual(JSON.parse(apiCalls[1].options.body), {{
          theme: "pearl-rose", color: "#fff0f2",
        }});
        assert.equal(documentRef.querySelector('meta[name="theme-color"]').content, "#fff0f2");

        manager.init();
        assert.equal(ensured.length, 1);
        assert.equal(themeSelect.listenerCount("change"), 1);
        assert.equal(apiCalls.length, 2);

        themeSelect.value = "sage-mist";
        themeSelect.emit("change");
        assert.equal(documentRef.documentElement.dataset.theme, "sage-mist");
        assert.equal(storage.get("voice-prompt-compiler-theme"), "sage-mist");
        assert.equal(storage.get("voice-prompt-compiler-theme-version"), "3");
        assert.deepEqual(JSON.parse(apiCalls.at(-1).options.body), {{
          theme: "sage-mist", color: "#edf6ee",
        }});

        const originalRandom = Math.random;
        Math.random = () => 0;
        try {{
          manager.applyTheme("auto-random");
          assert.equal(documentRef.documentElement.dataset.themeMode, "auto");
          assert.equal(documentRef.documentElement.dataset.theme, "silver-frost");
          assert.equal(themeSelect.value, "auto-random");
          assert.equal(intervals.at(-1).delay, 30000);
          assert.equal(storage.get("voice-prompt-compiler-theme"), "auto-random");
          intervals.at(-1).callback();
          assert.equal(documentRef.documentElement.dataset.theme, "aurora-blue");
          assert.notEqual(documentRef.documentElement.dataset.theme, "silver-frost");
        }} finally {{
          Math.random = originalRandom;
        }}
        manager.stopAutoTheme();
        assert.equal(clearedIntervals.at(-1), intervals.at(-1).id);
        assert.equal(documentRef.documentElement.dataset.themeMode, "fixed");
        assert.ok(visualizerSyncs >= 4);
        assert.equal(synced.length, visualizerSyncs);

        const freshDocument = new FakeDocument();
        const freshSelect = freshDocument.createElement("select");
        const freshStorage = new Map();
        const freshWindow = {{
          localStorage: {{
            getItem: (key) => freshStorage.get(key) ?? null,
            setItem: (key, value) => freshStorage.set(key, value),
          }},
          setTimeout() {{ return 1; }},
          setInterval() {{ return 2; }},
          clearInterval() {{}},
        }};
        createThemeManager({{
          elements: {{
            themeSelect: freshSelect,
            themeSwatches: freshDocument.createElement("span"),
          }},
          api: async () => ({{ ok: true }}),
          audioCapsuleVisualizer: {{ syncTheme() {{}} }},
          customSelectManager: {{ ensure() {{}}, sync() {{}} }},
          documentRef: freshDocument,
          windowRef: freshWindow,
        }}).init();
        assert.equal(freshStorage.get("voice-prompt-compiler-theme"), "auto-random");
        assert.equal(freshStorage.get("voice-prompt-compiler-theme-version"), "3");
        assert.equal(freshDocument.documentElement.dataset.themeMode, "auto");
        """
    )

    assert result.stdout == ""
    assert result.stderr == ""


def test_visual_effect_helpers_preserve_math_and_css_properties() -> None:
    module_url = _module_url("audio-visualizer.js")
    result = _run_node(
        f"""
        import assert from "node:assert/strict";
        const {{
          edgeProximity,
          cursorAngle,
          updateRecordGlow,
          resetRecordGlow,
          updateRecordSpotlight,
          resetRecordSpotlight,
        }} = await import({json.dumps(module_url)});
        const rect = {{ left: 10, top: 20, width: 100, height: 80 }};
        assert.equal(edgeProximity(rect, 50, 40), 0);
        assert.equal(edgeProximity(rect, 0, 40), 1);
        assert.equal(cursorAngle(rect, 50, 40), 45);
        assert.equal(cursorAngle(rect, 50, 0), 0);
        assert.equal(cursorAngle(rect, 100, 40), 90);

        const properties = new Map();
        const card = {{
          getBoundingClientRect: () => rect,
          style: {{ setProperty: (name, value) => properties.set(name, value) }},
        }};
        let computedFor;
        updateRecordGlow(card, {{ clientX: 10, clientY: 60 }}, (element) => {{
          computedFor = element;
          return {{ getPropertyValue: (name) => name === "--edge-sensitivity" ? "25" : "" }};
        }});
        assert.equal(computedFor, card);
        assert.equal(properties.get("--edge-proximity"), "100.000");
        assert.equal(properties.get("--cursor-angle"), "270.000deg");
        assert.equal(properties.get("--edge-opacity"), "1.000");
        resetRecordGlow(card);
        assert.equal(properties.get("--edge-opacity"), "0");

        updateRecordSpotlight(card, {{ clientX: -40, clientY: 200 }});
        assert.equal(properties.get("--spotlight-x"), "0.0px");
        assert.equal(properties.get("--spotlight-y"), "80.0px");
        assert.equal(properties.get("--spotlight-opacity"), "1");
        resetRecordSpotlight(card);
        assert.equal(properties.get("--spotlight-opacity"), "0");
        """
    )

    assert result.stdout == ""
    assert result.stderr == ""
