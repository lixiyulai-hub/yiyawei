export function createCustomSelectManager({ documentRef = globalThis.document } = {}) {
  const customSelects = new Map();
  let bound = false;

  function selectedOption(select) {
    return select.options[select.selectedIndex] || select.options[0] || null;
  }

  function renderSwatches(colors, className) {
    const group = documentRef.createElement("span");
    group.className = className;
    colors.forEach((color) => {
      const dot = documentRef.createElement("span");
      dot.style.background = color;
      group.append(dot);
    });
    return group;
  }

  function close(select) {
    const controls = customSelects.get(select);
    if (!controls) return;
    controls.shell.classList.remove("is-open");
    controls.trigger.setAttribute("aria-expanded", "false");
  }

  function closeAll(except = null) {
    customSelects.forEach((_, select) => {
      if (select !== except) close(select);
    });
  }

  function setOpen(select, open) {
    const controls = customSelects.get(select);
    if (!controls) return;
    if (open) closeAll(select);
    controls.shell.classList.toggle("is-open", open);
    controls.trigger.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) {
      const selected = controls.menu.querySelector('[aria-selected="true"]');
      if (selected) selected.scrollIntoView({ block: "nearest" });
    }
  }

  function sync(select) {
    const controls = customSelects.get(select);
    if (!controls) return;
    const current = selectedOption(select);
    const label = current ? current.textContent : "";
    controls.value.textContent = label;
    controls.trigger.title = label;
    controls.trigger.dataset.value = select.value;
    controls.side.replaceChildren();
    const colors = controls.getColors(select.value) || [];
    if (colors.length) controls.side.append(renderSwatches(colors, "select-mini-swatches"));
    controls.side.append(controls.caret);
    controls.menu.querySelectorAll(".select-option").forEach((item) => {
      item.setAttribute("aria-selected", item.dataset.value === select.value ? "true" : "false");
    });
  }

  function chooseOption(select, value) {
    if (select.value !== value) {
      select.value = value;
      sync(select);
      const EventConstructor = documentRef.defaultView?.Event || globalThis.Event;
      select.dispatchEvent(new EventConstructor("change", { bubbles: true }));
    } else {
      sync(select);
    }
    close(select);
  }

  function focusOption(controls, direction) {
    const items = Array.from(controls.menu.querySelectorAll(".select-option"));
    if (!items.length) return;
    const currentIndex = items.indexOf(documentRef.activeElement);
    const selectedIndex = items.findIndex((item) => item.getAttribute("aria-selected") === "true");
    const baseIndex = currentIndex >= 0 ? currentIndex : selectedIndex >= 0 ? selectedIndex : 0;
    const nextIndex = (baseIndex + direction + items.length) % items.length;
    items[nextIndex].focus();
  }

  function rebuild(select) {
    const controls = customSelects.get(select);
    if (!controls) return;
    controls.menu.replaceChildren(
      ...Array.from(select.options).map((item) => {
        const row = documentRef.createElement("div");
        row.className = "select-option";
        row.setAttribute("role", "option");
        row.tabIndex = -1;
        row.dataset.value = item.value;
        row.title = item.textContent;

        const label = documentRef.createElement("span");
        label.className = "select-option-label";
        label.textContent = item.textContent;
        row.append(label);

        const colors = controls.getColors(item.value) || [];
        if (colors.length) row.append(renderSwatches(colors, "select-option-swatches"));

        row.addEventListener("click", (event) => {
          event.preventDefault();
          chooseOption(select, item.value);
        });
        row.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            chooseOption(select, item.value);
          } else if (event.key === "ArrowDown") {
            event.preventDefault();
            focusOption(controls, 1);
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            focusOption(controls, -1);
          } else if (event.key === "Escape") {
            event.preventDefault();
            close(select);
            controls.trigger.focus();
          }
        });
        return row;
      }),
    );
    sync(select);
  }

  function ensure(select, { getColors } = {}) {
    const existing = customSelects.get(select);
    if (existing) {
      if (typeof getColors === "function") existing.getColors = getColors;
      rebuild(select);
      return existing;
    }

    select.classList.add("native-select");
    select.tabIndex = -1;
    select.setAttribute("aria-hidden", "true");
    select.closest(".field")?.classList.add("has-custom-select");

    const shell = documentRef.createElement("div");
    shell.className = "select-shell";
    const trigger = documentRef.createElement("div");
    trigger.className = "select-trigger";
    trigger.tabIndex = 0;
    trigger.setAttribute("role", "combobox");
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-expanded", "false");
    const value = documentRef.createElement("span");
    value.className = "select-value";
    const side = documentRef.createElement("span");
    side.className = "select-side";
    const caret = documentRef.createElement("span");
    caret.className = "select-caret";
    caret.setAttribute("aria-hidden", "true");
    const menu = documentRef.createElement("div");
    menu.className = "select-menu";
    menu.setAttribute("role", "listbox");

    side.append(caret);
    trigger.append(value, side);
    shell.append(trigger, menu);
    select.insertAdjacentElement("afterend", shell);

    const controls = {
      shell,
      trigger,
      value,
      side,
      caret,
      menu,
      getColors: typeof getColors === "function" ? getColors : () => [],
    };
    customSelects.set(select, controls);

    trigger.addEventListener("click", (event) => {
      event.preventDefault();
      setOpen(select, !shell.classList.contains("is-open"));
    });
    trigger.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        setOpen(select, !shell.classList.contains("is-open"));
      } else if (event.key === "ArrowDown") {
        event.preventDefault();
        setOpen(select, true);
        focusOption(controls, 1);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setOpen(select, true);
        focusOption(controls, -1);
      } else if (event.key === "Escape") {
        event.preventDefault();
        close(select);
      }
    });
    select.addEventListener("change", () => sync(select));
    rebuild(select);
    return controls;
  }

  function bind() {
    if (bound) return;
    bound = true;
    documentRef.addEventListener("pointerdown", (event) => {
      const target = event.target;
      customSelects.forEach((controls, select) => {
        if (!controls.shell.contains(target) && target !== select) close(select);
      });
    });
    documentRef.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeAll();
    });
  }

  return { bind, ensure, rebuild, sync, close, closeAll, setOpen };
}
