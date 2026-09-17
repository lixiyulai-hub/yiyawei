import {
  THEME_STORAGE_KEY,
  THEME_STORAGE_VERSION_KEY,
  CURRENT_THEME_STORAGE_VERSION,
  AUTO_THEME_ID,
  AUTO_THEME_INTERVAL_MS,
  autoThemeOption,
  themes,
  themeOptions,
} from "./theme-catalog.js";

export function createThemeManager({
  elements,
  api,
  audioCapsuleVisualizer,
  customSelectManager,
  documentRef = globalThis.document,
  windowRef = globalThis.window,
}) {
  const { themeSelect, themeSwatches } = elements;
  let autoThemeTimer = null;
  let lastAutoThemeId = "";
  let initialized = false;

  function option(label, value) {
    const element = documentRef.createElement("option");
    element.textContent = label;
    element.value = value;
    return element;
  }

  function themeById(id) {
    return themes.find((theme) => theme.id === id) || themes[0];
  }

  function themeOptionById(id) {
    return themeOptions.find((theme) => theme.id === id) || autoThemeOption;
  }

  function renderThemeSwatches(theme) {
    themeSwatches.replaceChildren(
      ...theme.swatches.map((color) => {
        const dot = documentRef.createElement("span");
        dot.style.background = color;
        return dot;
      }),
    );
  }

  function applyNativeChromeColor(theme) {
    let meta = documentRef.querySelector('meta[name="theme-color"]');
    if (!meta) {
      meta = documentRef.createElement("meta");
      meta.name = "theme-color";
      documentRef.head.appendChild(meta);
    }
    meta.content = theme.chrome;
    api("/api/theme", {
      method: "POST",
      body: JSON.stringify({ theme: theme.id, color: theme.chrome }),
    }).catch(() => {});
    windowRef.setTimeout(() => {
      api("/api/theme", {
        method: "POST",
        body: JSON.stringify({ theme: theme.id, color: theme.chrome }),
      }).catch(() => {});
    }, 600);
  }

  function persistThemePreference(themeId) {
    windowRef.localStorage.setItem(THEME_STORAGE_KEY, themeId);
    windowRef.localStorage.setItem(THEME_STORAGE_VERSION_KEY, CURRENT_THEME_STORAGE_VERSION);
  }

  function randomTheme(excludeId = "") {
    const pool = themes.filter((theme) => theme.id !== excludeId);
    const candidates = pool.length ? pool : themes;
    return candidates[Math.floor(Math.random() * candidates.length)] || themes[0];
  }

  function applyThemeVisual(theme, selectValue = theme.id) {
    documentRef.documentElement.dataset.theme = theme.id;
    documentRef.documentElement.dataset.contrast = theme.contrast || "light";
    themeSelect.value = selectValue;
    renderThemeSwatches(theme);
    customSelectManager.sync(themeSelect);
    applyNativeChromeColor(theme);
    audioCapsuleVisualizer.syncTheme();
  }

  function stopAutoTheme() {
    if (autoThemeTimer) {
      windowRef.clearInterval(autoThemeTimer);
      autoThemeTimer = null;
    }
    documentRef.documentElement.dataset.themeMode = "fixed";
  }

  function applyRandomTheme() {
    const theme = randomTheme(lastAutoThemeId);
    lastAutoThemeId = theme.id;
    applyThemeVisual(theme, AUTO_THEME_ID);
  }

  function startAutoTheme(persist = true) {
    stopAutoTheme();
    documentRef.documentElement.dataset.themeMode = "auto";
    applyRandomTheme();
    autoThemeTimer = windowRef.setInterval(applyRandomTheme, AUTO_THEME_INTERVAL_MS);
    if (persist) persistThemePreference(AUTO_THEME_ID);
  }

  function applyTheme(themeId, persist = true) {
    if (themeId === AUTO_THEME_ID) {
      startAutoTheme(persist);
      return;
    }
    stopAutoTheme();
    const theme = themeById(themeId);
    lastAutoThemeId = theme.id;
    applyThemeVisual(theme);
    if (persist) persistThemePreference(theme.id);
  }

  function init() {
    if (initialized) return;
    initialized = true;
    themeSelect.replaceChildren(...themeOptions.map((theme) => option(theme.label, theme.id)));
    customSelectManager.ensure(themeSelect, {
      getColors: (value) => themeOptionById(value).swatches,
    });
    const savedTheme = windowRef.localStorage.getItem(THEME_STORAGE_KEY);
    const savedVersion = windowRef.localStorage.getItem(THEME_STORAGE_VERSION_KEY);
    const hasCurrentThemePreference = savedVersion === CURRENT_THEME_STORAGE_VERSION;
    const initialTheme = hasCurrentThemePreference
      && savedTheme
      && (savedTheme === AUTO_THEME_ID || themes.some((theme) => theme.id === savedTheme))
      ? savedTheme
      : AUTO_THEME_ID;
    applyTheme(initialTheme, !hasCurrentThemePreference);
    themeSelect.addEventListener("change", () => applyTheme(themeSelect.value));
  }

  return {
    init,
    applyTheme,
    applyRandomTheme,
    startAutoTheme,
    stopAutoTheme,
  };
}
