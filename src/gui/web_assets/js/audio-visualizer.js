const AUDIO_CAPSULE_SENSITIVITY = 90;
const AUDIO_CAPSULE_VISUAL_CEILING = 0.58;
const AUDIO_CAPSULE_SMOOTHING = {
  rise: 0.18,
  fall: 0.115,
  idle: 0.045,
};

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function parseRgbToken(value, fallback) {
  const text = String(value || "").trim();
  const hex = text.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
  if (hex) {
    const raw = hex[1].length === 3
      ? hex[1].split("").map((part) => part + part).join("")
      : hex[1];
    return [0, 2, 4].map((index) => parseInt(raw.slice(index, index + 2), 16));
  }
  const parts = text
    .replace(/[^\d.,\s-]/g, "")
    .split(/[\s,]+/)
    .map((part) => Number(part))
    .filter((part) => Number.isFinite(part));
  if (parts.length < 3) return fallback;
  return parts.slice(0, 3).map((part) => clamp(Math.round(part), 0, 255));
}

function cssRgb(name, fallback) {
  return parseRgbToken(getComputedStyle(document.documentElement).getPropertyValue(name), fallback);
}

function mixRgb(a, b, amount) {
  return [
    Math.round(a[0] + (b[0] - a[0]) * amount),
    Math.round(a[1] + (b[1] - a[1]) * amount),
    Math.round(a[2] + (b[2] - a[2]) * amount),
  ];
}

function rgba(color, alpha) {
  return `rgba(${color[0]}, ${color[1]}, ${color[2]}, ${alpha})`;
}

function mapVoiceLevel(rawLevel) {
  const raw = Math.max(0, Number(rawLevel) || 0);
  const gain = 8 + AUDIO_CAPSULE_SENSITIVITY * 0.14;
  const quietGain = 3 + AUDIO_CAPSULE_SENSITIVITY * 0.06;
  const primary = 1 - Math.exp(-Math.max(0, raw - 0.002) * gain);
  const quietLift = Math.pow(clamp(raw * quietGain, 0, 1), 0.72) * 0.18;
  const compressed = Math.pow(clamp(Math.max(primary, quietLift), 0, 1), 1.28);
  return clamp(compressed * AUDIO_CAPSULE_VISUAL_CEILING, 0, AUDIO_CAPSULE_VISUAL_CEILING);
}

function edgeProximity(rect, x, y) {
  const centerX = rect.width / 2;
  const centerY = rect.height / 2;
  const distanceX = Math.abs(x - centerX);
  const distanceY = Math.abs(y - centerY);
  const scaleX = centerX === 0 ? 0 : distanceX / centerX;
  const scaleY = centerY === 0 ? 0 : distanceY / centerY;
  return clamp(Math.max(scaleX, scaleY), 0, 1);
}

function cursorAngle(rect, x, y) {
  const dx = x - rect.width / 2;
  const dy = y - rect.height / 2;
  if (dx === 0 && dy === 0) return 45;
  const degrees = Math.atan2(dy, dx) * (180 / Math.PI) + 90;
  return degrees < 0 ? degrees + 360 : degrees;
}

function updateRecordGlow(card, event, getComputedStyleImpl = globalThis.getComputedStyle) {
  const rect = card.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  const edge = edgeProximity(rect, x, y) * 100;
  const edgeSensitivity = Number.parseFloat(
    getComputedStyleImpl(card).getPropertyValue("--edge-sensitivity"),
  ) || 22;
  const glowOpacity = clamp((edge - edgeSensitivity) / (100 - edgeSensitivity), 0, 1);

  card.style.setProperty("--edge-proximity", edge.toFixed(3));
  card.style.setProperty("--cursor-angle", `${cursorAngle(rect, x, y).toFixed(3)}deg`);
  card.style.setProperty("--edge-opacity", glowOpacity.toFixed(3));
}

function resetRecordGlow(card) {
  card.style.setProperty("--edge-opacity", "0");
}

function updateRecordSpotlight(card, event) {
  const rect = card.getBoundingClientRect();
  const x = clamp(event.clientX - rect.left, 0, rect.width);
  const y = clamp(event.clientY - rect.top, 0, rect.height);

  card.style.setProperty("--spotlight-x", `${x.toFixed(1)}px`);
  card.style.setProperty("--spotlight-y", `${y.toFixed(1)}px`);
  card.style.setProperty("--spotlight-opacity", "1");
}

function resetRecordSpotlight(card) {
  card.style.setProperty("--spotlight-opacity", "0");
}

function createAudioCapsuleVisualizer(canvas, host) {
  if (!canvas || !host) {
    return {
      update() {},
      syncTheme() {},
    };
  }

  const ctx = canvas.getContext("2d", { alpha: true });
  const particles = Array.from({ length: 148 }, (_, index) => ({
    seed: index * 19.17 + Math.random() * 12,
    x: Math.random(),
    lane: Math.random() * 2 - 1,
    depth: 0.45 + Math.random() * 0.9,
    drift: 0.16 + Math.random() * 0.55,
    size: 0.55 + Math.random() * 1.7,
    shift: Math.random(),
  }));
  const state = {
    target: 0,
    smooth: 0,
    phase: "idle",
    width: 1,
    height: 1,
    dpr: 1,
    lastNow: performance.now(),
    themeReadAt: 0,
    palette: [],
  };

  function syncTheme() {
    const accent = cssRgb("--accent-rgb", [255, 113, 95]);
    const focus = cssRgb("--focus-rgb", [90, 140, 255]);
    const green = cssRgb("--green", [63, 184, 127]);
    const softAccent = mixRgb(accent, [255, 255, 255], 0.44);
    state.palette = [
      focus,
      [255, 255, 255],
      accent,
      green,
      softAccent,
      mixRgb(focus, accent, 0.38),
    ];
  }

  function resize() {
    const rect = canvas.getBoundingClientRect();
    state.dpr = Math.min(window.devicePixelRatio || 1, 2);
    state.width = Math.max(1, rect.width);
    state.height = Math.max(1, rect.height);
    const nextWidth = Math.round(state.width * state.dpr);
    const nextHeight = Math.round(state.height * state.dpr);
    if (canvas.width !== nextWidth || canvas.height !== nextHeight) {
      canvas.width = nextWidth;
      canvas.height = nextHeight;
      ctx.setTransform(state.dpr, 0, 0, state.dpr, 0, 0);
    }
  }

  function capsulePath(x, y, w, h) {
    const r = h / 2;
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.arcTo(x + w, y, x + w, y + r, r);
    ctx.arcTo(x + w, y + h, x + w - r, y + h, r);
    ctx.lineTo(x + r, y + h);
    ctx.arcTo(x, y + h, x, y + r, r);
    ctx.arcTo(x, y, x + r, y, r);
    ctx.closePath();
  }

  function colorAt(p, t, offset = 0) {
    if (!state.palette.length) syncTheme();
    const q = ((p + t * 0.055 + offset) % 1 + 1) % 1;
    return state.palette[Math.floor(q * state.palette.length) % state.palette.length];
  }

  function addFlowStops(gradient, t, alpha, offset = 0) {
    [0, 0.16, 0.32, 0.48, 0.64, 0.82, 1].forEach((stop) => {
      gradient.addColorStop(stop, rgba(colorAt(stop, t, offset), alpha));
    });
  }

  function spectral(p, t) {
    const pulse = Math.sin(p * Math.PI * 4.6 + t * 2.2) * 0.18;
    const flutter = Math.sin(p * Math.PI * 11.4 - t * 3.1) * 0.12;
    return clamp(state.smooth * 0.46 + pulse + flutter + 0.14, 0, 0.72);
  }

  function drawRibbon(t) {
    const { width, height } = state;
    const cy = height / 2;
    const amp = height * (0.1 + state.smooth * 0.44);
    const gradient = ctx.createLinearGradient(0, 0, width, 0);
    addFlowStops(gradient, t, 0.14 + state.smooth * 0.16, state.smooth * 0.1);

    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    ctx.filter = `blur(${3 + state.smooth * 4}px)`;
    ctx.fillStyle = gradient;
    ctx.beginPath();
    const steps = 64;
    for (let i = 0; i <= steps; i += 1) {
      const p = i / steps;
      const env = Math.sin(Math.PI * p) ** 0.55;
      const x = p * width;
      const y = cy - env * amp * (0.34 + spectral(p, t) * 0.86) + Math.sin(p * 18 + t * 2.4) * 3;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    for (let i = steps; i >= 0; i -= 1) {
      const p = i / steps;
      const env = Math.sin(Math.PI * p) ** 0.55;
      const x = p * width;
      const y = cy + env * amp * (0.28 + spectral(p + 0.13, t) * 0.7) + Math.cos(p * 14 - t * 2.1) * 3;
      ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }

  function drawSplashes(t) {
    const { width, height } = state;
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    for (let i = 0; i < 5; i += 1) {
      const travel = ((0.13 + i * 0.21 + t * (0.022 + i * 0.002)) % 1 + 1) % 1;
      const x = width * travel;
      const y = height * (0.48 + Math.sin(t * 1.1 + i * 1.8) * 0.12);
      const radius = height * (0.28 + state.smooth * 0.48 + spectral(travel, t) * 0.24);
      const color = colorAt(travel, t, i * 0.08);
      const glow = ctx.createRadialGradient(x, y, 0, x, y, radius);
      glow.addColorStop(0, rgba(mixRgb(color, [255, 255, 255], 0.25), 0.055 + state.smooth * 0.06));
      glow.addColorStop(0.46, rgba(color, 0.03 + state.smooth * 0.04));
      glow.addColorStop(1, "transparent");
      ctx.filter = `blur(${5 + state.smooth * 6}px)`;
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.ellipse(x, y, radius * 1.55, radius * 0.46, Math.sin(t + i) * 0.14, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  }

  function drawParticles(t, dt) {
    const { width, height } = state;
    const cy = height / 2;
    const amp = height * (0.14 + state.smooth * 0.48);
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    particles.forEach((particle, index) => {
      particle.x = (particle.x + dt * 0.000014 * particle.drift * (1 + state.smooth * 1.8)) % 1;
      const env = Math.sin(Math.PI * particle.x) ** 0.55;
      const wave = Math.sin(particle.x * Math.PI * 6 + t * (0.9 + particle.depth) + particle.seed);
      const flicker = spectral(particle.x + particle.shift, t);
      const x = particle.x * width;
      const y = cy + particle.lane * env * amp * (0.22 + flicker * 0.62) + wave * (1.4 + state.smooth * 4.8);
      const size = particle.size * (0.68 + flicker * 1.15 + state.smooth * 0.64);
      const color = colorAt(particle.x, t, particle.shift + particle.seed * 0.0003);
      const alpha = clamp(0.12 + flicker * 0.2 + state.smooth * 0.18, 0.08, 0.48);
      ctx.fillStyle = rgba(color, alpha);
      ctx.shadowColor = rgba(color, alpha);
      ctx.shadowBlur = 3 + state.smooth * 8 + flicker * 4;
      ctx.beginPath();
      ctx.arc(x, y, size, 0, Math.PI * 2);
      ctx.fill();

      if ((index + Math.floor(t * 10)) % 37 === 0 && state.smooth + flicker > 0.86) {
        ctx.strokeStyle = rgba(mixRgb(color, [255, 255, 255], 0.22), 0.1 + state.smooth * 0.1);
        ctx.lineWidth = 0.7;
        ctx.beginPath();
        ctx.moveTo(x, y - size);
        ctx.lineTo(x + Math.sin(particle.seed) * 6, y - size - height * (0.16 + state.smooth * 0.34));
        ctx.stroke();
      }
    });
    ctx.restore();
  }

  function drawFrame(t, dt) {
    resize();
    if (performance.now() - state.themeReadAt > 500) {
      state.themeReadAt = performance.now();
      syncTheme();
    }

    const { width, height } = state;
    ctx.clearRect(0, 0, width, height);
    capsulePath(0, 0, width, height);
    ctx.save();
    ctx.clip();

    const bg = ctx.createLinearGradient(0, 0, width, height);
    bg.addColorStop(0, "rgba(255, 255, 255, 0.02)");
    bg.addColorStop(0.48, "rgba(255, 255, 255, 0.09)");
    bg.addColorStop(1, "rgba(255, 255, 255, 0.03)");
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, width, height);

    drawSplashes(t);
    drawRibbon(t);
    drawParticles(t, dt);

    ctx.restore();

    const edge = ctx.createLinearGradient(0, 0, width, 0);
    addFlowStops(edge, t, 0.22 + state.smooth * 0.16, 0.12);
    ctx.strokeStyle = edge;
    ctx.lineWidth = 0.9 + state.smooth * 0.42;
    capsulePath(1.2, 1.2, width - 2.4, height - 2.4);
    ctx.stroke();
  }

  function animate(now) {
    const activeBase = state.phase === "warming" ? 0.16 : 0.055;
    const target = Math.max(state.target, activeBase);
    const easing = target > state.smooth ? AUDIO_CAPSULE_SMOOTHING.rise : AUDIO_CAPSULE_SMOOTHING.fall;
    state.smooth += (target - state.smooth) * easing;
    if (state.phase !== "recording" && state.phase !== "warming") {
      const idleLevel = 0.075 + Math.sin(now * 0.0016) * 0.022;
      state.smooth += (idleLevel - state.smooth) * AUDIO_CAPSULE_SMOOTHING.idle;
    }
    const dt = Math.min(48, now - state.lastNow);
    state.lastNow = now;
    drawFrame(now / 1000, dt);
    requestAnimationFrame(animate);
  }

  window.addEventListener("resize", resize);
  syncTheme();
  resize();
  requestAnimationFrame(animate);

  return {
    update(next) {
      state.target = clamp(Number(next.level) || 0, 0, 1);
      state.phase = next.phase || "idle";
      host.style.setProperty("--audio-capsule-level", state.target.toFixed(3));
    },
    syncTheme,
  };
}

export {
  clamp,
  mapVoiceLevel,
  edgeProximity,
  cursorAngle,
  updateRecordGlow,
  resetRecordGlow,
  updateRecordSpotlight,
  resetRecordSpotlight,
  createAudioCapsuleVisualizer,
};
