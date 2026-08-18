"use strict";

const TYPES = {label: 1, button: 2, slider: 3, toggle: 4, gauge: 5};
const TYPE_NAMES = Object.fromEntries(Object.entries(TYPES).map(([name, value]) => [value, name]));
const ACTIONS = {
  none: 0,
  navigate: 1,
  rgb_color: 0x10,
  rgb_effect: 0x11,
  brightness: 0x12,
  profile: 0x20,
  actuation: 0x21,
  rapid_trigger: 0x22,
  hid_key: 0x30,
  media_key: 0x31,
  host_event: 0x40,
};
const ACTION_NAMES = Object.fromEntries(Object.entries(ACTIONS).map(([name, value]) => [value, name]));

const key = (id, label, units = 1, extra = {}) => ({id, label, units, ...extra});
const spacer = units => ({spacer: true, units});
/*
 * Physical North-American KB7 layout: a 15u ANSI main block, a portrait
 * display where a TKL navigation cluster normally sits, and an isolated
 * inverted-T cursor cluster below it. The four cursor keys are rendered in
 * their own bay, so they deliberately do not appear in these main rows.
 */
const MAIN_KEY_ROWS = [
  [
    key("ESC", "Esc", 1, {function: true}), spacer(.8),
    key("F1", "F1", 1, {function: true}), key("F2", "F2", 1, {function: true}),
    key("F3", "F3", 1, {function: true}), key("F4", "F4", 1, {function: true}), spacer(.2),
    key("F5", "F5", 1, {function: true}), key("F6", "F6", 1, {function: true}),
    key("F7", "F7", 1, {function: true}), key("F8", "F8", 1, {function: true}), spacer(.2),
    key("F9", "F9", 1, {function: true}), key("F10", "F10", 1, {function: true}),
    key("F11", "F11", 1, {function: true}), key("F12", "F12", 1, {function: true}),
  ],
  [
    key("GRAVE", "`"), key("1", "1"), key("2", "2"), key("3", "3"), key("4", "4"),
    key("5", "5"), key("6", "6"), key("7", "7"), key("8", "8"), key("9", "9"),
    key("0", "0"), key("MINUS", "−"), key("EQUAL", "="), key("BACKSPACE", "Backspace", 2),
  ],
  [
    key("TAB", "Tab", 1.5), key("Q", "Q"), key("W", "W"), key("E", "E"), key("R", "R"),
    key("T", "T"), key("Y", "Y"), key("U", "U"), key("I", "I"), key("O", "O"),
    key("P", "P"), key("LEFTBRACE", "["), key("RIGHTBRACE", "]"), key("BACKSLASH", "\\", 1.5),
  ],
  [
    key("CAPSLOCK", "Caps", 1.75), key("A", "A"), key("S", "S"), key("D", "D"), key("F", "F"),
    key("G", "G"), key("H", "H"), key("J", "J"), key("K", "K"), key("L", "L"),
    key("SEMICOLON", ";"), key("APOSTROPHE", "'"), key("ENTER", "Enter", 2.25),
  ],
  [
    key("LEFTSHIFT", "Shift", 2.25), key("Z", "Z"), key("X", "X"), key("C", "C"), key("V", "V"),
    key("B", "B"), key("N", "N"), key("M", "M"), key("COMMA", ","), key("DOT", "."),
    key("SLASH", "/"), key("RIGHTSHIFT", "Shift", 2.75),
  ],
  [
    key("LEFTCTRL", "Ctrl", 1.25), key("LEFTMETA", "Win", 1.25), key("LEFTALT", "Alt", 1.25),
    key("SPACE", "Space", 6.25), key("RIGHTALT", "Alt", 1.25), key("FN", "Fn", 1.25),
    key("COMPOSE", "Menu", 1.25), key("RIGHTCTRL", "Ctrl", 1.25),
  ],
];
const ARROW_KEYS = [key("UP", "↑"), key("LEFT", "←"), key("DOWN", "↓"), key("RIGHT", "→")];
const KEY_DEFINITIONS = [...MAIN_KEY_ROWS.flat().filter(item => !item.spacer), ...ARROW_KEYS];
const KEY_IDS = KEY_DEFINITIONS.map(item => item.id);
const KEY_BY_ID = Object.fromEntries(KEY_DEFINITIONS.map(item => [item.id, item]));
const ALPHAS = KEY_IDS.filter(id => /^[A-Z]$/.test(id));
const ZONES = {
  all: KEY_IDS,
  alphas: ALPHAS,
  wasd: ["W", "A", "S", "D"],
  arrows: ["LEFT", "UP", "DOWN", "RIGHT"],
};

const DEFAULT_DOC = {
  format: "kb7-screen-v1",
  boot_screen: 1,
  screens: [
    {
      id: 1,
      name: "Overview",
      background: "#07101e",
      widgets: [
        {id: 10, type: "label", x: 28, y: 30, width: 424, height: 66, text: "SYSTEM OVERVIEW", foreground: "#f4f7ff", background: "#111f35", minimum: 0, maximum: 100, value: 0, action: {type: "none"}},
        {id: 11, type: "gauge", x: 28, y: 122, width: 424, height: 128, text: "ACTUATION", foreground: "#65e6ff", background: "#10263a", minimum: 0, maximum: 255, value: 128, action: {type: "actuation"}},
        {id: 12, type: "slider", x: 28, y: 278, width: 424, height: 92, text: "BRIGHTNESS", foreground: "#9d7cff", background: "#1a1838", minimum: 0, maximum: 100, value: 68, action: {type: "brightness"}},
        {id: 13, type: "button", x: 28, y: 398, width: 202, height: 106, text: "COLOR", foreground: "#dffcff", background: "#13364a", minimum: 0, maximum: 100, value: 0, action: {type: "rgb_color", arg1: 4385535}},
        {id: 14, type: "button", x: 250, y: 398, width: 202, height: 106, text: "MEDIA", foreground: "#fff3df", background: "#3b253b", minimum: 0, maximum: 100, value: 0, action: {type: "navigate", target_screen: 2}},
        {id: 15, type: "toggle", x: 28, y: 536, width: 424, height: 96, text: "RAPID TRIGGER", foreground: "#b5ffcb", background: "#123229", minimum: 0, maximum: 1, value: 1, action: {type: "rapid_trigger", arg0: 12, arg1: 12}},
        {id: 16, type: "label", x: 28, y: 672, width: 424, height: 72, text: "OFFLINE READY", foreground: "#7e91aa", background: "#0b1628", minimum: 0, maximum: 100, value: 0, action: {type: "none"}},
      ],
    },
    {
      id: 2,
      name: "Media",
      background: "#100c1c",
      widgets: [
        {id: 20, type: "label", x: 28, y: 30, width: 424, height: 74, text: "MEDIA DECK", foreground: "#fff5fd", background: "#271630", minimum: 0, maximum: 100, value: 0, action: {type: "none"}},
        {id: 21, type: "button", x: 28, y: 138, width: 424, height: 124, text: "PLAY PAUSE", foreground: "#ffffff", background: "#713c82", minimum: 0, maximum: 100, value: 0, action: {type: "media_key", arg0: 205}},
        {id: 22, type: "button", x: 28, y: 290, width: 202, height: 112, text: "VOLUME DOWN", foreground: "#f5f7ff", background: "#263553", minimum: 0, maximum: 100, value: 0, action: {type: "media_key", arg0: 234}},
        {id: 23, type: "button", x: 250, y: 290, width: 202, height: 112, text: "VOLUME UP", foreground: "#f5f7ff", background: "#263553", minimum: 0, maximum: 100, value: 0, action: {type: "media_key", arg0: 233}},
        {id: 24, type: "button", x: 28, y: 674, width: 424, height: 74, text: "BACK", foreground: "#b9ddff", background: "#10253e", minimum: 0, maximum: 100, value: 0, action: {type: "navigate", target_screen: 1}},
      ],
    },
  ],
};

const DEFAULT_KEYBOARD = {
  lighting: {
    enabled: true,
    effect: "aurora",
    brightness: 68,
    speed: 42,
    direction: "east",
    primary: "#42efff",
    secondary: "#9d5cff",
    reactive: "#b5ffcb",
    per_key: {A: "#42efff", D: "#9d5cff", S: "#65e6ff", W: "#b5ffcb"},
  },
  switches: {
    travel_mm: 3.2,
    actuation_mm: 1.6,
    rapid_trigger: true,
    rapid_press_delta_mm: .15,
    rapid_release_delta_mm: .15,
    per_key: {
      A: {actuation_mm: 1.0, rapid_trigger: true},
      D: {actuation_mm: 1.0, rapid_trigger: true},
      S: {actuation_mm: 1.0, rapid_trigger: true},
      W: {actuation_mm: 1.0, rapid_trigger: true},
    },
  },
  analog: {
    enabled: true,
    output: "gamepad_left_stick",
    curve: "linear",
    deadzone_mm: .12,
    saturation_mm: 3.2,
    smoothing: 2,
    invert_x: false,
    invert_y: false,
    digital_passthrough: true,
    bindings: {x_negative: "LEFT", x_positive: "RIGHT", y_negative: "UP", y_positive: "DOWN"},
  },
};

const clone = value => JSON.parse(JSON.stringify(value));
const clamp = (value, minimum, maximum) => Math.max(minimum, Math.min(maximum, value));
const esc = value => String(value).replace(/[&<>"']/g, character => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[character]));
const title = value => String(value).replaceAll("_", " ").replace(/\b\w/g, character => character.toUpperCase());
const mm = value => `${Number(value).toFixed(value < 1 ? 2 : 1)} mm`;

let doc = clone(DEFAULT_DOC);
let keyboard = clone(DEFAULT_KEYBOARD);
let activeScreen = 1;
let selected = null;
let mode = "design";
let nextId = 100;
let dragState = null;
let activeWorkspace = "display";
let lightingPlaying = true;
let lightingSelection = new Set(KEY_IDS);
let switchSelection = new Set(ZONES.wasd);
let analogExerciseTimer = null;
const touchTrace = {
  active: false,
  pointerId: null,
  pointerType: "—",
  originMode: "touch",
  origin: {x: TouchTraceMath.WIDTH / 2, y: TouchTraceMath.HEIGHT / 2},
  current: null,
  pressure: 0,
  deadzone: .08,
  gesture: 0,
  samples: [],
  strokes: [],
  recentTimes: [],
  intervals: [],
  deliveryLags: [],
  latestInterval: null,
  gestureStartedAt: null,
  frame: null,
};

const STORAGE_KEY = "offline-control-studio-profile-v2";
const LEGACY_STORAGE_KEY = "kb7-studio-profile-v1";

const display = document.querySelector("#display");
const inspector = document.querySelector("#inspectorBody");
const screen = () => doc.screens.find(item => item.id === activeScreen) || doc.screens[0];
const touchMoveEvent = "onpointerrawupdate" in window ? "pointerrawupdate" : "pointermove";

function toast(message) {
  const element = document.querySelector("#toast");
  element.textContent = message;
  element.classList.add("show");
  clearTimeout(element.timer);
  element.timer = setTimeout(() => element.classList.remove("show"), 2400);
}

function profileDocument() {
  return {
    format: "kb7-profile-v1",
    name: document.querySelector("#projectName").value.trim() || "Untitled profile",
    screen_document: doc,
    lighting: keyboard.lighting,
    switches: keyboard.switches,
    analog: keyboard.analog,
    capabilities: {
      hall_keymap: "implemented-hardware-unverified",
      rgb_position_mapping: "pending_hardware",
      analog_hid_output: "implemented-hardware-unverified",
      device_io: false,
    },
  };
}

function saveLocal() {
  const state = document.querySelector("#saveState");
  state.textContent = "Saving locally…";
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(profileDocument()));
    clearTimeout(saveLocal.timer);
    saveLocal.timer = setTimeout(() => { state.textContent = "Saved locally"; }, 350);
  } catch (_error) {
    state.textContent = "Edited · offline";
  }
}

function loadLocal() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY) || localStorage.getItem(LEGACY_STORAGE_KEY);
    if (!stored) return;
    const profile = JSON.parse(stored);
    if (profile.format !== "kb7-profile-v1") return;
    /* Preserve user edits while removing labels shipped by the old branded demo. */
    if (profile.name === "Neon Control") profile.name = "Offline Profile";
    for (const page of profile.screen_document?.screens || []) {
      if (page.name === "Command Center") page.name = "Overview";
      for (const widget of page.widgets || []) {
        if (widget.text === "COMMAND CENTER") widget.text = "SYSTEM OVERVIEW";
        if (widget.text === "AURORA") widget.text = "COLOR";
      }
    }
    loadProfile(profile, false);
  } catch (_error) {
    // A malformed or unavailable local store must never stop the offline app.
  }
}

function markDirty(renderer) {
  saveLocal();
  if (renderer) renderer();
}

function setWorkspace(name) {
  activeWorkspace = name;
  document.querySelectorAll("#workspaceNav button").forEach(button => button.classList.toggle("active", button.dataset.workspace === name));
  document.querySelectorAll(".workspace-view").forEach(view => {
    const active = view.dataset.view === name;
    view.classList.toggle("active", active);
    view.hidden = !active;
  });
  if (name === "display") renderDisplayWorkspace();
  if (name === "lighting") renderLighting();
  if (name === "switches") renderSwitches();
  if (name === "analog") renderAnalog();
}

/* Display workspace */
function renderDisplayWorkspace() {
  renderScreens();
  renderDisplay();
  renderInspector();
  const tracing = mode === "trace";
  document.querySelector("#objectCount").textContent = tracing ? `${touchTrace.samples.length} samples` : `${screen().widgets.length} widgets`;
  document.querySelector("#formatHealthCard").hidden = tracing;
  document.querySelector("#displayTip").innerHTML = tracing
    ? "Press and drag anywhere on the preview · sampling describes browser pointer delivery, not physical panel latency"
    : mode === "preview"
      ? "Click controls to exercise navigation and actions · no device is accessed"
      : "<kbd>Shift</kbd> while dragging to snap softly · click controls in Preview to exercise navigation";
}

function renderScreens() {
  const list = document.querySelector("#screenList");
  list.innerHTML = "";
  doc.screens.forEach(item => {
    const button = document.createElement("button");
    button.className = `screen-item${item.id === activeScreen ? " active" : ""}`;
    button.innerHTML = `<i class="screen-thumb" style="background:${esc(item.background)}"></i><span>${esc(item.name)}<small>${item.widgets.length} widgets</small></span>${doc.boot_screen === item.id ? "<em>BOOT</em>" : ""}`;
    button.onclick = () => {
      activeScreen = item.id;
      selected = null;
      renderDisplayWorkspace();
    };
    list.appendChild(button);
  });
}

function renderDisplay() {
  const current = screen();
  display.style.background = current.background;
  display.classList.toggle("preview", mode === "preview");
  display.classList.toggle("trace", mode === "trace");
  display.querySelectorAll(".canvas-widget, .touch-trace-overlay").forEach(element => element.remove());
  current.widgets.forEach(widget => {
    const element = document.createElement("div");
    element.className = `canvas-widget ${widget.type}${selected === widget.id ? " selected" : ""}`;
    Object.assign(element.style, {
      left: `${widget.x / 480 * 100}%`,
      top: `${widget.y / 800 * 100}%`,
      width: `${widget.width / 480 * 100}%`,
      height: `${widget.height / 800 * 100}%`,
      background: widget.background,
      color: widget.foreground,
      fontSize: `${Math.max(8, Math.min(16, widget.height / 5))}px`,
    });
    element.dataset.id = widget.id;
    element.innerHTML = `<span>${esc(widget.text || widget.type.toUpperCase())}</span>`;
    if (["slider", "gauge"].includes(widget.type)) {
      const percentage = (widget.value - widget.minimum) / Math.max(1, widget.maximum - widget.minimum) * 100;
      element.insertAdjacentHTML("beforeend", `<i class="track"><i class="fill" style="display:block;width:${percentage}%;background:${esc(widget.foreground)}"></i></i>`);
    }
    element.onpointerdown = event => widgetPointerDown(event, widget);
    element.onclick = event => {
      event.stopPropagation();
      if (mode === "preview") simulate(widget);
      else if (mode === "design") {
        selected = widget.id;
        renderDisplayWorkspace();
      }
    };
    display.appendChild(element);
  });
  display.onclick = () => {
    if (mode === "design") {
      selected = null;
      renderDisplayWorkspace();
    }
  };
  if (mode === "trace") {
    const overlay = document.createElement("div");
    overlay.className = "touch-trace-overlay";
    overlay.setAttribute("aria-hidden", "true");
    overlay.innerHTML = `<svg viewBox="0 0 ${TouchTraceMath.WIDTH} ${TouchTraceMath.HEIGHT}" preserveAspectRatio="none"></svg><div class="trace-screen-readout"></div>`;
    display.appendChild(overlay);
    updateTouchTraceOverlay();
  }
}

function widgetPointerDown(event, widget) {
  if (mode !== "design") return;
  event.preventDefault();
  event.stopPropagation();
  selected = widget.id;
  const rectangle = display.getBoundingClientRect();
  dragState = {widget, startX: event.clientX, startY: event.clientY, x: widget.x, y: widget.y, rectangle};
  event.currentTarget.setPointerCapture(event.pointerId);
  event.currentTarget.onpointermove = widgetPointerMove;
  event.currentTarget.onpointerup = () => {
    dragState = null;
    event.currentTarget.onpointermove = null;
    markDirty(renderDisplayWorkspace);
  };
  renderInspector();
}

function widgetPointerMove(event) {
  if (!dragState) return;
  let x = dragState.x + (event.clientX - dragState.startX) * 480 / dragState.rectangle.width;
  let y = dragState.y + (event.clientY - dragState.startY) * 800 / dragState.rectangle.height;
  if (event.shiftKey) {
    x = Math.round(x / 8) * 8;
    y = Math.round(y / 8) * 8;
  }
  dragState.widget.x = clamp(Math.round(x), 0, 480 - dragState.widget.width);
  dragState.widget.y = clamp(Math.round(y), 0, 800 - dragState.widget.height);
  renderDisplay();
}

function touchTraceVector(position = touchTrace.current) {
  if (!position) return {x: 0, y: 0, magnitude: 0, rawX: 0, rawY: 0, rawMagnitude: 0};
  return TouchTraceMath.vector(position.x, position.y, touchTrace.origin.x, touchTrace.origin.y, touchTrace.deadzone);
}

function touchTraceMetrics() {
  const lastTime = touchTrace.recentTimes.at(-1);
  const windowTimes = lastTime === undefined ? [] : touchTrace.recentTimes.filter(value => value >= lastTime - 1000);
  const span = windowTimes.length > 1 ? windowTimes.at(-1) - windowTimes[0] : 0;
  const rate = span > 0 ? (windowTimes.length - 1) * 1000 / span : 0;
  const intervals = touchTrace.intervals.slice(-120).sort((a, b) => a - b);
  const mean = intervals.length ? intervals.reduce((sum, value) => sum + value, 0) / intervals.length : 0;
  const worst = intervals.length ? intervals.at(-1) : 0;
  const deliveryLags = touchTrace.deliveryLags.slice(-120).sort((a, b) => a - b);
  const meanDelivery = deliveryLags.length ? deliveryLags.reduce((sum, value) => sum + value, 0) / deliveryLags.length : 0;
  const worstDelivery = deliveryLags.length ? deliveryLags.at(-1) : 0;
  return {rate, mean, worst, meanDelivery, worstDelivery, count: touchTrace.samples.length};
}

function updateTouchTraceOverlay() {
  const overlay = display.querySelector(".touch-trace-overlay");
  if (!overlay) return;
  const svg = overlay.querySelector("svg");
  const current = touchTrace.current;
  const origin = touchTrace.origin;
  const vector = touchTraceVector();
  const leftRadius = Math.max(4, origin.x * touchTrace.deadzone);
  const rightRadius = Math.max(4, (TouchTraceMath.WIDTH - 1 - origin.x) * touchTrace.deadzone);
  const topRadius = Math.max(4, origin.y * touchTrace.deadzone);
  const bottomRadius = Math.max(4, (TouchTraceMath.HEIGHT - 1 - origin.y) * touchTrace.deadzone);
  const curve = .5522848;
  const deadzonePath = [
    `M ${origin.x} ${origin.y - topRadius}`,
    `C ${origin.x + curve * rightRadius} ${origin.y - topRadius}, ${origin.x + rightRadius} ${origin.y - curve * topRadius}, ${origin.x + rightRadius} ${origin.y}`,
    `C ${origin.x + rightRadius} ${origin.y + curve * bottomRadius}, ${origin.x + curve * rightRadius} ${origin.y + bottomRadius}, ${origin.x} ${origin.y + bottomRadius}`,
    `C ${origin.x - curve * leftRadius} ${origin.y + bottomRadius}, ${origin.x - leftRadius} ${origin.y + curve * bottomRadius}, ${origin.x - leftRadius} ${origin.y}`,
    `C ${origin.x - leftRadius} ${origin.y - curve * topRadius}, ${origin.x - curve * leftRadius} ${origin.y - topRadius}, ${origin.x} ${origin.y - topRadius} Z`,
  ].join(" ");
  const strokeMarkup = touchTrace.strokes.map((stroke, index) => {
    const points = stroke.points.map(point => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
    const recent = index === touchTrace.strokes.length - 1 ? " current" : "";
    return points ? `<polyline class="trace-stroke${recent}" points="${points}"></polyline>` : "";
  }).join("");
  const pointerMarkup = current ? `
    <line class="trace-vector${touchTrace.active ? " active" : ""}" x1="${origin.x}" y1="${origin.y}" x2="${current.x}" y2="${current.y}"></line>
    <circle class="trace-pointer${touchTrace.active ? " active" : ""}" cx="${current.x}" cy="${current.y}" r="11"></circle>` : "";
  svg.innerHTML = `
    <line class="trace-axis" x1="0" y1="${origin.y}" x2="${TouchTraceMath.WIDTH}" y2="${origin.y}"></line>
    <line class="trace-axis" x1="${origin.x}" y1="0" x2="${origin.x}" y2="${TouchTraceMath.HEIGHT}"></line>
    <path class="trace-deadzone" d="${deadzonePath}"></path>
    ${strokeMarkup}
    ${pointerMarkup}
    <circle class="trace-origin" cx="${origin.x}" cy="${origin.y}" r="7"></circle>`;

  const readout = overlay.querySelector(".trace-screen-readout");
  if (!current) {
    readout.innerHTML = `<strong>TOUCH TRACE</strong><span>Press and drag to begin</span>`;
  } else if (touchTrace.active) {
    readout.innerHTML = `<strong>X ${Math.round(current.x)} · Y ${Math.round(current.y)}</strong><span>AX ${vector.x.toFixed(3)} · AY ${vector.y.toFixed(3)}</span>`;
  } else {
    readout.innerHTML = `<strong>RELEASED</strong><span>Last X ${Math.round(current.x)} · Y ${Math.round(current.y)}</span>`;
  }
}

function updateTouchTraceInspector() {
  if (mode !== "trace") return;
  const current = touchTrace.current;
  const vector = touchTrace.active ? touchTraceVector() : {x: 0, y: 0, magnitude: 0};
  const metrics = touchTraceMetrics();
  const setText = (id, value) => {
    const element = document.querySelector(`#${id}`);
    if (element) element.textContent = value;
  };
  setText("traceState", touchTrace.active ? "Tracking" : current ? "Released" : "Ready");
  setText("traceCoordinates", current ? `X ${Math.round(current.x)} · Y ${Math.round(current.y)}` : "X — · Y —");
  setText("traceXOutput", vector.x.toFixed(3));
  setText("traceYOutput", vector.y.toFixed(3));
  setText("traceMagnitude", vector.magnitude.toFixed(3));
  setText("traceRate", metrics.rate ? `${metrics.rate.toFixed(1)} Hz` : "—");
  setText("traceInterval", metrics.mean ? `${metrics.mean.toFixed(2)} ms` : "—");
  setText("traceWorstGap", metrics.worst ? `${metrics.worst.toFixed(2)} ms` : "—");
  setText("traceDeliveryLag", metrics.meanDelivery ? `${metrics.meanDelivery.toFixed(2)} ms` : "—");
  setText("traceWorstDelivery", metrics.worstDelivery ? `${metrics.worstDelivery.toFixed(2)} ms` : "—");
  setText("traceSamples", String(metrics.count));
  setText("tracePointerType", touchTrace.pointerType === "—" ? "—" : `${touchTrace.pointerType} · ${touchMoveEvent === "pointerrawupdate" ? "raw" : "move"}`);
  setText("tracePressure", current ? touchTrace.pressure.toFixed(2) : "—");
  setText("traceDeadzoneValue", `${Math.round(touchTrace.deadzone * 100)}%`);

  const stateCard = document.querySelector(".trace-live-card");
  if (stateCard) stateCard.classList.toggle("active", touchTrace.active);
  const stickDot = document.querySelector("#traceStickDot");
  if (stickDot) {
    stickDot.style.left = `${50 + vector.x * 42}%`;
    stickDot.style.top = `${50 + vector.y * 42}%`;
  }
  const exportButton = document.querySelector("#exportTouchTrace");
  if (exportButton) exportButton.disabled = touchTrace.samples.length === 0;
  document.querySelector("#objectCount").textContent = `${touchTrace.samples.length} samples`;
}

function scheduleTouchTraceUpdate() {
  if (touchTrace.frame !== null) return;
  touchTrace.frame = requestAnimationFrame(() => {
    touchTrace.frame = null;
    updateTouchTraceOverlay();
    updateTouchTraceInspector();
  });
}

function appendTouchTraceSample(event) {
  const position = TouchTraceMath.coordinate(event.clientX, event.clientY, display.getBoundingClientRect());
  const timestamp = Number(event.timeStamp);
  const measuredLag = performance.now() - timestamp;
  const deliveryLag = measuredLag >= 0 && measuredLag < 60000 ? measuredLag : 0;
  touchTrace.deliveryLags.push(deliveryLag);
  if (touchTrace.deliveryLags.length > 1000) touchTrace.deliveryLags.shift();
  const previousTime = touchTrace.recentTimes.at(-1);
  if (previousTime === undefined || timestamp > previousTime) {
    if (previousTime !== undefined) {
      touchTrace.latestInterval = timestamp - previousTime;
      touchTrace.intervals.push(touchTrace.latestInterval);
      if (touchTrace.intervals.length > 1000) touchTrace.intervals.shift();
    }
    touchTrace.recentTimes.push(timestamp);
    if (touchTrace.recentTimes.length > 1000) touchTrace.recentTimes.shift();
  }
  touchTrace.current = position;
  touchTrace.pressure = Number.isFinite(event.pressure) ? event.pressure : 0;
  const vector = touchTraceVector(position);
  const sample = {
    gesture: touchTrace.gesture,
    event_time_ms: Number(timestamp.toFixed(3)),
    elapsed_ms: Number((timestamp - touchTrace.gestureStartedAt).toFixed(3)),
    pointer_type: touchTrace.pointerType,
    x: Number(position.x.toFixed(3)),
    y: Number(position.y.toFixed(3)),
    origin_x: Number(touchTrace.origin.x.toFixed(3)),
    origin_y: Number(touchTrace.origin.y.toFixed(3)),
    deadzone: touchTrace.deadzone,
    delivery_lag_ms: Number(deliveryLag.toFixed(3)),
    pressure: Number(touchTrace.pressure.toFixed(3)),
    output_x: Number(vector.x.toFixed(6)),
    output_y: Number(vector.y.toFixed(6)),
    magnitude: Number(vector.magnitude.toFixed(6)),
  };
  touchTrace.samples.push(sample);
  if (touchTrace.samples.length > 8192) touchTrace.samples.shift();
  const stroke = touchTrace.strokes.at(-1);
  stroke.points.push(position);
  if (stroke.points.length > 360) stroke.points.shift();
}

function appendTouchTraceEvent(event) {
  const coalesced = typeof event.getCoalescedEvents === "function" ? event.getCoalescedEvents() : [];
  const events = coalesced.length ? coalesced : [event];
  events.forEach(appendTouchTraceSample);
}

function beginTouchTrace(event) {
  if (mode !== "trace" || touchTrace.active || (event.pointerType === "mouse" && event.button !== 0)) return;
  event.preventDefault();
  touchTrace.active = true;
  touchTrace.pointerId = event.pointerId;
  touchTrace.pointerType = event.pointerType || "pointer";
  touchTrace.gesture += 1;
  touchTrace.gestureStartedAt = Number(event.timeStamp);
  touchTrace.recentTimes = [];
  touchTrace.intervals = [];
  touchTrace.deliveryLags = [];
  touchTrace.latestInterval = null;
  const initial = TouchTraceMath.coordinate(event.clientX, event.clientY, display.getBoundingClientRect());
  touchTrace.origin = touchTrace.originMode === "center"
    ? {x: TouchTraceMath.WIDTH / 2, y: TouchTraceMath.HEIGHT / 2}
    : initial;
  touchTrace.strokes.push({gesture: touchTrace.gesture, points: []});
  if (touchTrace.strokes.length > 12) touchTrace.strokes.shift();
  display.setPointerCapture?.(event.pointerId);
  appendTouchTraceEvent(event);
  scheduleTouchTraceUpdate();
}

function moveTouchTrace(event) {
  if (mode !== "trace" || !touchTrace.active || event.pointerId !== touchTrace.pointerId) return;
  event.preventDefault();
  appendTouchTraceEvent(event);
  scheduleTouchTraceUpdate();
}

function endTouchTrace(event) {
  if (!touchTrace.active || event.pointerId !== touchTrace.pointerId) return;
  event.preventDefault();
  touchTrace.active = false;
  touchTrace.pointerId = null;
  touchTrace.pressure = 0;
  if (display.hasPointerCapture?.(event.pointerId)) display.releasePointerCapture(event.pointerId);
  scheduleTouchTraceUpdate();
}

function clearTouchTrace() {
  const capturedPointer = touchTrace.pointerId;
  touchTrace.active = false;
  touchTrace.pointerId = null;
  touchTrace.pointerType = "—";
  touchTrace.current = null;
  touchTrace.pressure = 0;
  touchTrace.gesture = 0;
  touchTrace.samples = [];
  touchTrace.strokes = [];
  touchTrace.recentTimes = [];
  touchTrace.intervals = [];
  touchTrace.deliveryLags = [];
  touchTrace.latestInterval = null;
  touchTrace.gestureStartedAt = null;
  touchTrace.origin = {x: TouchTraceMath.WIDTH / 2, y: TouchTraceMath.HEIGHT / 2};
  if (capturedPointer !== null && display.hasPointerCapture?.(capturedPointer)) display.releasePointerCapture(capturedPointer);
  scheduleTouchTraceUpdate();
}

function exportTouchTrace() {
  if (!touchTrace.samples.length) return;
  const metrics = touchTraceMetrics();
  const artifact = {
    format: "touch-trace-v1",
    created_utc: new Date().toISOString(),
    scope: "browser-pointer-events-only",
    time_origin_ms: performance.timeOrigin,
    native_size: {width: TouchTraceMath.WIDTH, height: TouchTraceMath.HEIGHT},
    settings: {origin_mode: touchTrace.originMode, deadzone: touchTrace.deadzone, y_positive: "down", pointer_event: touchMoveEvent},
    summary: {
      gestures: touchTrace.gesture,
      samples: touchTrace.samples.length,
      recent_sample_rate_hz: Number(metrics.rate.toFixed(3)),
      mean_interval_ms: Number(metrics.mean.toFixed(3)),
      worst_recent_gap_ms: Number(metrics.worst.toFixed(3)),
      mean_delivery_lag_ms: Number(metrics.meanDelivery.toFixed(3)),
      worst_delivery_lag_ms: Number(metrics.worstDelivery.toFixed(3)),
    },
    limitation: "This trace measures browser PointerEvent delivery, not physical touchscreen scan rate, firmware latency, or USB transport.",
    samples: touchTrace.samples,
  };
  download(`${fileStem()}-touch-trace.json`, `${JSON.stringify(artifact, null, 2)}\n`, "application/json");
  toast(`${touchTrace.samples.length} touch samples exported`);
}

function renderTouchTraceInspector() {
  document.querySelector("#inspectorTitle").textContent = "Touch monitor";
  document.querySelector("#selectionLabel").textContent = "Browser input";
  inspector.innerHTML = `
    <div class="trace-live-card">
      <div class="trace-state-row"><span><i></i><b id="traceState">Ready</b></span><small id="tracePointerType">—</small></div>
      <strong id="traceCoordinates">X — · Y —</strong>
      <small>Native 480 × 800 coordinates</small>
    </div>
    <div class="trace-output-grid">
      <div><span>X output</span><strong id="traceXOutput">0.000</strong></div>
      <div><span>Y output</span><strong id="traceYOutput">0.000</strong></div>
      <div><span>Magnitude</span><strong id="traceMagnitude">0.000</strong></div>
      <div><span>Pressure</span><strong id="tracePressure">—</strong></div>
    </div>
    <div class="trace-stick-preview"><span class="trace-stick-x"></span><span class="trace-stick-y"></span><i id="traceStickDot"></i></div>
    <div class="inspector-group trace-sampling">
      <h3>Pointer sampling</h3>
      <dl><div><dt>Sample rate</dt><dd id="traceRate">—</dd></div><div><dt>Mean interval</dt><dd id="traceInterval">—</dd></div><div><dt>Worst gap</dt><dd id="traceWorstGap">—</dd></div><div><dt>Delivery lag</dt><dd id="traceDeliveryLag">—</dd></div><div><dt>Worst delivery</dt><dd id="traceWorstDelivery">—</dd></div><div><dt>Recorded</dt><dd id="traceSamples">0</dd></div></dl>
    </div>
    <div class="inspector-group">
      <h3>Joystick model</h3>
      <div class="select-field"><label for="traceOriginMode">Origin</label><select id="traceOriginMode"><option value="touch">First contact (floating)</option><option value="center">Display centre</option></select></div>
      <label class="range-field"><span>Radial deadzone <output id="traceDeadzoneValue">8%</output></span><input id="traceDeadzone" type="range" min="0" max="30" value="8"></label>
      <small class="trace-axis-note">X+ is right · Y+ is down · output springs to zero on release</small>
    </div>
    <div class="trace-actions"><button class="button primary" id="exportTouchTrace">Export trace</button><button class="button ghost" id="clearTouchTrace">Clear</button></div>
    <section class="trace-limitation"><strong>Simulation boundary</strong><p>This measures pointer events delivered by this browser. It cannot measure the physical panel scan rate, controller latency, firmware path, or USB transport.</p></section>`;

  const origin = document.querySelector("#traceOriginMode");
  origin.value = touchTrace.originMode;
  origin.onchange = event => {
    touchTrace.originMode = event.target.value;
    if (touchTrace.originMode === "center") touchTrace.origin = {x: TouchTraceMath.WIDTH / 2, y: TouchTraceMath.HEIGHT / 2};
    scheduleTouchTraceUpdate();
  };
  const deadzone = document.querySelector("#traceDeadzone");
  deadzone.value = Math.round(touchTrace.deadzone * 100);
  deadzone.oninput = event => {
    touchTrace.deadzone = Number(event.target.value) / 100;
    scheduleTouchTraceUpdate();
  };
  document.querySelector("#clearTouchTrace").onclick = clearTouchTrace;
  document.querySelector("#exportTouchTrace").onclick = exportTouchTrace;
  updateTouchTraceInspector();
}

function simulate(widget) {
  const action = widget.action?.type || "none";
  if (action === "navigate") {
    activeScreen = widget.action.target_screen;
    selected = null;
    renderDisplayWorkspace();
    toast(`Navigated to ${screen().name}`);
    return;
  }
  if (widget.type === "toggle") widget.value = widget.value ? 0 : 1;
  if (action === "rgb_color") {
    keyboard.lighting.primary = `#${Number(widget.action.arg1 || 0).toString(16).padStart(6, "0")}`;
    keyboard.lighting.effect = "static";
    toast(`${widget.text} applied to the lighting preview`);
  } else if (action === "brightness") {
    keyboard.lighting.brightness = clamp(Number(widget.value), 0, 100);
    toast(`Lighting brightness set to ${keyboard.lighting.brightness}%`);
  } else if (action === "actuation") {
    keyboard.switches.actuation_mm = Number((Number(widget.value) / 255 * keyboard.switches.travel_mm).toFixed(2));
    toast(`Actuation set to ${mm(keyboard.switches.actuation_mm)}`);
  } else if (action === "rapid_trigger") {
    keyboard.switches.rapid_trigger = Boolean(widget.value);
    toast(`Rapid Trigger ${widget.value ? "enabled" : "disabled"}`);
  } else {
    toast(`${widget.text} · ${action}`);
  }
  markDirty(renderDisplayWorkspace);
}

function field(label, path, value, type = "text", options = null) {
  if (options) {
    return `<div class="field"><label>${label}</label><select data-key="${path}">${options.map(option => `<option ${option === value ? "selected" : ""}>${option}</option>`).join("")}</select></div>`;
  }
  return `<div class="field"><label>${label}</label><input data-key="${path}" type="${type}" value="${esc(value)}"></div>`;
}

function renderInspector() {
  if (mode === "trace") {
    renderTouchTraceInspector();
    return;
  }
  document.querySelector("#inspectorTitle").textContent = "Inspector";
  const widget = screen().widgets.find(item => item.id === selected);
  document.querySelector("#selectionLabel").textContent = widget ? `#${widget.id} ${widget.type}` : "Screen";
  if (!widget) {
    inspector.innerHTML = `<div class="inspector-group"><h3>Screen</h3>${field("Name", "screen.name", screen().name)}${field("Background", "screen.background", screen().background, "color")}${field("Boot screen", "screen.boot", doc.boot_screen === screen().id ? "yes" : "no", "text", ["yes", "no"])}</div>`;
  } else {
    inspector.innerHTML = `<div class="inspector-group"><h3>Content</h3>${field("Text", "text", widget.text)}${field("Type", "type", widget.type, "text", Object.keys(TYPES))}</div><div class="inspector-group"><h3>Geometry</h3><div class="field-grid">${field("X", "x", widget.x, "number")}${field("Y", "y", widget.y, "number")}${field("Width", "width", widget.width, "number")}${field("Height", "height", widget.height, "number")}</div></div><div class="inspector-group"><h3>Appearance</h3>${field("Foreground", "foreground", widget.foreground, "color")}${field("Background", "background", widget.background, "color")}</div><div class="inspector-group"><h3>Value & action</h3>${field("Value", "value", widget.value, "number")}${field("Minimum", "minimum", widget.minimum, "number")}${field("Maximum", "maximum", widget.maximum, "number")}${field("Action", "action.type", widget.action?.type || "none", "text", Object.keys(ACTIONS))}${field("Target screen", "action.target_screen", widget.action?.target_screen || 0, "number")}${field("Argument 0", "action.arg0", widget.action?.arg0 || 0, "number")}${field("Argument 1", "action.arg1", widget.action?.arg1 || 0, "number")}</div><button class="danger" id="deleteWidget">Remove widget</button>`;
    document.querySelector("#deleteWidget").onclick = () => {
      screen().widgets = screen().widgets.filter(item => item.id !== widget.id);
      selected = null;
      markDirty(renderDisplayWorkspace);
    };
  }
  inspector.querySelectorAll("[data-key]").forEach(input => {
    input.onchange = () => applyField(input.dataset.key, input.value, widget);
  });
}

function applyField(path, value, widget) {
  if (path.startsWith("screen.")) {
    if (path === "screen.name") screen().name = value;
    if (path === "screen.background") screen().background = value;
    if (path === "screen.boot" && value === "yes") doc.boot_screen = screen().id;
  } else {
    const target = path.startsWith("action.") ? (widget.action || (widget.action = {type: "none"})) : widget;
    const property = path.split(".").pop();
    const numeric = ["x", "y", "width", "height", "value", "minimum", "maximum", "target_screen", "arg0", "arg1"];
    target[property] = numeric.includes(property) ? Number(value) : value;
    if (path === "action.type") {
      target.flags = 0;
      target.target_screen = 0;
      target.arg0 = 0;
      target.arg1 = 0;
      if (value === "brightness") {
        widget.minimum = 0; widget.maximum = 100;
      } else if (value === "actuation") {
        widget.minimum = 0; widget.maximum = 255;
      } else if (value === "rapid_trigger") {
        widget.minimum = 0; widget.maximum = 1;
      }
      widget.value = clamp(widget.value, widget.minimum, widget.maximum);
    }
    if (["x", "y", "width", "height"].includes(property)) {
      widget.width = clamp(widget.width, 1, 480);
      widget.height = clamp(widget.height, 1, 800);
      widget.x = clamp(widget.x, 0, 480 - widget.width);
      widget.y = clamp(widget.y, 0, 800 - widget.height);
    }
  }
  markDirty(renderDisplayWorkspace);
}

function addWidget(type, x = 40, y = 120) {
  const sizes = {label: [300, 64], button: [190, 96], slider: [350, 90], toggle: [350, 84], gauge: [350, 120]};
  const [width, height] = sizes[type];
  const widget = {
    id: nextId++, type, x: clamp(x, 0, 480 - width), y: clamp(y, 0, 800 - height), width, height,
    text: type.toUpperCase(), foreground: "#eaf2ff", background: type === "label" ? "#07101e" : "#17243a",
    minimum: 0, maximum: 100, value: type === "toggle" ? 1 : 50, action: {type: "none"},
  };
  screen().widgets.push(widget);
  selected = widget.id;
  markDirty(renderDisplayWorkspace);
}

/* Keyboard canvases */
function mixColor(first, second, amount) {
  const parse = color => [1, 3, 5].map(offset => parseInt(color.slice(offset, offset + 2), 16));
  const a = parse(first);
  const b = parse(second);
  const mixed = a.map((component, index) => Math.round(component * (1 - amount) + b[index] * amount));
  return `#${mixed.map(component => component.toString(16).padStart(2, "0")).join("")}`;
}

function dimColor(color, brightness) {
  return mixColor("#0e1725", color, .18 + brightness / 100 * .82);
}

function keyEffectColor(id, index) {
  const lighting = keyboard.lighting;
  if (!lighting.enabled) return "#20293a";
  if (lighting.per_key[id]) return dimColor(lighting.per_key[id], lighting.brightness);
  let color = lighting.primary;
  if (lighting.effect === "gradient" || lighting.effect === "aurora") {
    const wave = lighting.effect === "aurora" ? (Math.sin(index * .48 + lighting.speed / 15) + 1) / 2 : index / Math.max(1, KEY_IDS.length - 1);
    color = mixColor(lighting.primary, lighting.secondary, wave);
  }
  if (lighting.effect === "reactive") color = mixColor("#142033", lighting.primary, .42);
  if (lighting.effect === "heatmap") {
    const activity = ((index * 17 + 23) % 41) / 40;
    color = mixColor(lighting.primary, lighting.reactive, activity);
  }
  return dimColor(color, lighting.brightness);
}

function selectorLabel(id) {
  return `logical ${id}`;
}

function createKeyButton(item, rowIndex, index, purpose) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `keycap${item.function || rowIndex === 0 ? " function-key" : ""}`;
  button.dataset.key = item.id;
  button.style.setProperty("--u", item.units);
  button.style.setProperty("--key-index", index);
  button.innerHTML = `<span>${esc(item.label)}</span><small class="key-selector">${selectorLabel(item.id)}</small>`;

  if (purpose === "lighting") {
    button.style.setProperty("--key-color", keyEffectColor(item.id, index));
    if (keyboard.lighting.per_key[item.id]) button.classList.add("painted");
    if (lightingSelection.size < KEY_IDS.length && lightingSelection.has(item.id)) button.classList.add("selected");
    button.onclick = event => selectCanvasKey("lighting", item.id, event);
  }

  if (purpose === "switches") {
    const override = keyboard.switches.per_key[item.id];
    if (override) button.classList.add("override");
    if (switchSelection.has(item.id)) button.classList.add("selected");
    const keyPoint = override?.actuation_mm ?? keyboard.switches.actuation_mm;
    button.querySelector(".key-selector").remove();
    button.insertAdjacentHTML("beforeend", `<small class="key-meta">${Number(keyPoint).toFixed(1)}</small>`);
    button.onclick = event => selectCanvasKey("switches", item.id, event);
  }

  if (purpose === "analog") {
    const bindings = keyboard.analog.bindings;
    const xRole = bindings.x_negative === item.id ? "X−" : bindings.x_positive === item.id ? "X+" : "";
    const yRole = bindings.y_negative === item.id ? "Y−" : bindings.y_positive === item.id ? "Y+" : "";
    if (xRole) button.classList.add("axis-x");
    if (yRole) button.classList.add("axis-y");
    if (xRole || yRole) {
      button.querySelector(".key-selector").remove();
      button.insertAdjacentHTML("beforeend", `<small class="key-meta">${xRole || yRole}</small>`);
    }
    button.onclick = () => toast(`${item.label} · ${selectorLabel(item.id)}`);
  }

  return button;
}

function renderKeyboard(container, purpose) {
  container.innerHTML = "";
  const physical = document.createElement("div");
  physical.className = "keyboard-physical";
  physical.dataset.layout = "modified-tkl-78";

  const left = document.createElement("div");
  left.className = "keyboard-left-stack";
  const actionBar = document.createElement("div");
  actionBar.className = "keyboard-actionbar";
  actionBar.setAttribute("aria-hidden", "true");
  actionBar.innerHTML = `
    <span class="hardware-dial"><i></i></span>
    <span class="hardware-media-control">‹</span>
    <span class="hardware-media-control">›</span>
    <span class="hardware-action-gap"></span>
    <span class="hardware-quick-control">◇</span>
    <span class="hardware-quick-control">◌</span>
    <span class="hardware-quick-control">⌁</span>
    <span class="hardware-quick-control">✦</span>`;
  left.appendChild(actionBar);

  const main = document.createElement("div");
  main.className = "keyboard-main";
  let index = 0;
  MAIN_KEY_ROWS.forEach((items, rowIndex) => {
    const row = document.createElement("div");
    row.className = "keyboard-row";
    items.forEach(item => {
      if (item.spacer) {
        const gap = document.createElement("span");
        gap.className = "key-spacer";
        gap.style.setProperty("--u", item.units);
        row.appendChild(gap);
        return;
      }
      row.appendChild(createKeyButton(item, rowIndex, index, purpose));
      index += 1;
    });
    main.appendChild(row);
  });
  left.appendChild(main);

  const right = document.createElement("div");
  right.className = "keyboard-right-stack";
  const miniDisplay = document.createElement("div");
  miniDisplay.className = "keyboard-mini-display";
  miniDisplay.setAttribute("aria-hidden", "true");
  miniDisplay.innerHTML = `<span class="mini-display-status"><i></i><i></i></span><span class="mini-display-grid">${Array.from({length: 12}, (_, cell) => `<i class="mini-display-cell cell-${cell + 1}"></i>`).join("")}</span>`;
  right.appendChild(miniDisplay);

  const arrowPad = document.createElement("div");
  arrowPad.className = "arrow-pad";
  ARROW_KEYS.forEach(item => {
    const button = createKeyButton(item, 5, index, purpose);
    button.classList.add(`arrow-${item.id.toLowerCase()}`);
    arrowPad.appendChild(button);
    index += 1;
  });
  right.appendChild(arrowPad);

  physical.append(left, right);
  container.appendChild(physical);
}

function selectCanvasKey(purpose, id, event) {
  const selection = purpose === "lighting" ? lightingSelection : switchSelection;
  if (event.shiftKey || event.ctrlKey || event.metaKey) {
    if (selection.has(id)) selection.delete(id);
    else selection.add(id);
  } else {
    selection.clear();
    selection.add(id);
  }
  if (!selection.size) selection.add(id);
  if (purpose === "lighting") renderLighting();
  else renderSwitches();
}

function setZone(purpose, zone) {
  const selection = purpose === "lighting" ? lightingSelection : switchSelection;
  selection.clear();
  ZONES[zone].forEach(id => selection.add(id));
  if (purpose === "lighting") renderLighting();
  else renderSwitches();
}

/* Lighting */
function renderLighting() {
  const lighting = keyboard.lighting;
  renderKeyboard(document.querySelector("#lightingKeyboard"), "lighting");
  document.querySelector(".lighting-canvas").classList.toggle("playing", lightingPlaying);
  document.querySelector(".lighting-canvas").classList.toggle("paused", !lightingPlaying);
  document.querySelectorAll("#lightingEffects button").forEach(button => button.classList.toggle("active", button.dataset.effect === lighting.effect));
  document.querySelectorAll("#lightingZones button").forEach(button => button.classList.toggle("active", sameSet(lightingSelection, new Set(ZONES[button.dataset.zone]))));
  const selectionLabel = lightingSelection.size === KEY_IDS.length ? "All keys" : lightingSelection.size === 1 ? KEY_BY_ID[[...lightingSelection][0]].label : `${lightingSelection.size} keys`;
  document.querySelector("#lightingSelectionCount").textContent = selectionLabel;
  document.querySelector("#lightingInspectorSelection").textContent = selectionLabel;
  document.querySelector("#lightingStatus").textContent = `${title(lighting.effect)} · ${lighting.brightness}%`;
  document.querySelector("#lightingEnabled").checked = lighting.enabled;
  ["Primary", "Secondary", "Reactive"].forEach(name => {
    const keyName = name.toLowerCase();
    document.querySelector(`#lighting${name}`).value = lighting[keyName];
    document.querySelector(`#lighting${name}Value`).textContent = lighting[keyName];
  });
  document.querySelector("#lightingBrightness").value = lighting.brightness;
  document.querySelector("#lightingBrightnessValue").textContent = `${lighting.brightness}%`;
  document.querySelector("#lightingSpeed").value = lighting.speed;
  document.querySelector("#lightingSpeedValue").textContent = `${lighting.speed}%`;
  document.querySelector("#lightingDirection").value = lighting.direction;
  document.querySelector("#lightingPhase").style.width = `${lighting.speed}%`;
  document.querySelector("#lightingPhaseLabel").textContent = `${lighting.speed}%`;
  const play = document.querySelector("#lightingPlay");
  play.textContent = lightingPlaying ? "Ⅱ" : "▶";
  play.title = lightingPlaying ? "Pause lighting preview" : "Play lighting preview";
  play.classList.toggle("active", lightingPlaying);
}

function sameSet(first, second) {
  return first.size === second.size && [...first].every(value => second.has(value));
}

/* Switches */
function effectiveActuation(id) {
  return keyboard.switches.per_key[id]?.actuation_mm ?? keyboard.switches.actuation_mm;
}

function selectedActuation() {
  const first = [...switchSelection][0] || "W";
  return effectiveActuation(first);
}

function renderSwitches() {
  const switches = keyboard.switches;
  renderKeyboard(document.querySelector("#switchKeyboard"), "switches");
  const label = switchSelection.size === KEY_IDS.length ? "All keys" : switchSelection.size === 1 ? KEY_BY_ID[[...switchSelection][0]].label : `${switchSelection.size} keys`;
  document.querySelector("#switchInspectorSelection").textContent = `${label}${sameSet(switchSelection, new Set(ZONES.wasd)) ? " · WASD" : ""}`;
  document.querySelectorAll("#switchZones button").forEach(button => button.classList.toggle("active", sameSet(switchSelection, new Set(ZONES[button.dataset.zone]))));
  const point = selectedActuation();
  document.querySelector("#actuationPoint").value = Math.round(point * 10);
  document.querySelector("#actuationValue").textContent = mm(point);
  document.querySelector("#fullTravel").value = Math.round(switches.travel_mm * 10);
  document.querySelector("#travelValue").textContent = mm(switches.travel_mm);
  document.querySelector("#rapidTrigger").checked = switches.rapid_trigger;
  document.querySelector("#rapidPress").value = Math.round(switches.rapid_press_delta_mm * 100);
  document.querySelector("#rapidRelease").value = Math.round(switches.rapid_release_delta_mm * 100);
  document.querySelector("#rapidPressValue").textContent = mm(switches.rapid_press_delta_mm);
  document.querySelector("#rapidReleaseValue").textContent = mm(switches.rapid_release_delta_mm);
  document.querySelector("#switchStatus").textContent = `${mm(switches.actuation_mm)} · ${switches.rapid_trigger ? "Rapid Trigger" : "Fixed reset"}`;
  const testKey = [...switchSelection][0] || "W";
  document.querySelector("#switchTestKey").textContent = KEY_BY_ID[testKey].label;
  document.querySelector("#switchTravelSimulation").max = Math.round(switches.travel_mm * 10);
  if (Number(document.querySelector("#switchTravelSimulation").value) > Number(document.querySelector("#switchTravelSimulation").max)) {
    document.querySelector("#switchTravelSimulation").value = document.querySelector("#switchTravelSimulation").max;
  }
  updateTravelLab();
}

function updateTravelLab() {
  const switches = keyboard.switches;
  const raw = Number(document.querySelector("#switchTravelSimulation").value);
  const depth = raw / 10;
  const point = selectedActuation();
  const pressed = depth >= point;
  document.querySelector("#switchTravelValue").textContent = mm(depth);
  const state = document.querySelector("#switchTravelState");
  state.textContent = pressed ? "Pressed" : "Released";
  state.classList.toggle("pressed", pressed);
  document.querySelector("#travelFill").style.width = `${clamp(depth / switches.travel_mm * 100, 0, 100)}%`;
  document.querySelector("#actuationMarker").style.left = `${clamp(point / switches.travel_mm * 100, 0, 100)}%`;
  const release = Math.max(0, point - switches.rapid_release_delta_mm);
  document.querySelector("#releaseMarker").style.left = `${clamp(release / switches.travel_mm * 100, 0, 100)}%`;
}

function applyActuation(value) {
  const point = clamp(value, .1, keyboard.switches.travel_mm);
  const perKey = document.querySelector("#perKeyActuation").checked && switchSelection.size < KEY_IDS.length;
  if (perKey) {
    switchSelection.forEach(id => {
      keyboard.switches.per_key[id] = {
        actuation_mm: Number(point.toFixed(2)),
        rapid_trigger: keyboard.switches.per_key[id]?.rapid_trigger ?? keyboard.switches.rapid_trigger,
      };
    });
  } else {
    keyboard.switches.actuation_mm = Number(point.toFixed(2));
  }
  markDirty(renderSwitches);
}

/* Analog */
function populateBindingSelectors() {
  const options = KEY_IDS.map(id => `<option value="${id}">${esc(KEY_BY_ID[id].label)} · ${selectorLabel(id)}</option>`).join("");
  ["bindingXNegative", "bindingXPositive", "bindingYNegative", "bindingYPositive"].forEach(id => {
    document.querySelector(`#${id}`).innerHTML = options;
  });
}

function renderAnalog() {
  const analog = keyboard.analog;
  renderKeyboard(document.querySelector("#analogKeyboard"), "analog");
  const map = {
    bindingXNegative: "x_negative",
    bindingXPositive: "x_positive",
    bindingYNegative: "y_negative",
    bindingYPositive: "y_positive",
  };
  Object.entries(map).forEach(([id, field]) => { document.querySelector(`#${id}`).value = analog.bindings[field]; });
  document.querySelector("#analogEnabled").checked = analog.enabled;
  document.querySelector("#analogOutput").value = analog.output;
  document.querySelector("#analogCurve").value = analog.curve;
  document.querySelector("#analogDeadzone").value = Math.round(analog.deadzone_mm * 100);
  document.querySelector("#analogSaturation").value = Math.round(analog.saturation_mm * 100);
  document.querySelector("#analogSmoothing").value = analog.smoothing;
  document.querySelector("#invertX").checked = analog.invert_x;
  document.querySelector("#invertY").checked = analog.invert_y;
  document.querySelector("#digitalPassthrough").checked = analog.digital_passthrough;
  document.querySelector("#deadzoneValue").textContent = mm(analog.deadzone_mm);
  document.querySelector("#saturationValue").textContent = mm(analog.saturation_mm);
  document.querySelector("#smoothingValue").textContent = analog.smoothing;
  document.querySelector("#analogStatus").textContent = `${outputLabel(analog.output)} · ${title(analog.curve)}`;
  document.querySelector("#stickOutputName").textContent = outputLabel(analog.output);
  const b = analog.bindings;
  document.querySelector("#analogBindingSummary").textContent = `${KEY_BY_ID[b.x_negative].label} ${KEY_BY_ID[b.x_positive].label} · ${KEY_BY_ID[b.y_negative].label} ${KEY_BY_ID[b.y_positive].label}`;
  const labels = {
    simXNegLabel: b.x_negative, simXPosLabel: b.x_positive,
    simYNegLabel: b.y_negative, simYPosLabel: b.y_positive,
  };
  Object.entries(labels).forEach(([id, keyId]) => { document.querySelector(`#${id}`).textContent = KEY_BY_ID[keyId].label; });
  updateAnalogMonitor();
}

function outputLabel(value) {
  return ({gamepad_left_stick: "Gamepad left stick", gamepad_right_stick: "Gamepad right stick", gamepad_triggers: "Gamepad triggers"})[value];
}

function shapedAxis(negativeRaw, positiveRaw, inverted) {
  const analog = keyboard.analog;
  const signedDepth = (positiveRaw - negativeRaw) / 10;
  const sign = Math.sign(signedDepth);
  const magnitude = Math.abs(signedDepth);
  let normalized = magnitude <= analog.deadzone_mm ? 0 : (magnitude - analog.deadzone_mm) / Math.max(.01, analog.saturation_mm - analog.deadzone_mm);
  normalized = clamp(normalized, 0, 1);
  if (analog.curve === "exponential") normalized **= 2;
  if (analog.curve === "s_curve") normalized = normalized * normalized * (3 - 2 * normalized);
  return Math.round(sign * normalized * 32767 * (inverted ? -1 : 1));
}

function updateAnalogMonitor() {
  const values = {
    xNegative: Number(document.querySelector("#simXNegative").value),
    xPositive: Number(document.querySelector("#simXPositive").value),
    yNegative: Number(document.querySelector("#simYNegative").value),
    yPositive: Number(document.querySelector("#simYPositive").value),
  };
  const x = shapedAxis(values.xNegative, values.xPositive, keyboard.analog.invert_x);
  const y = shapedAxis(values.yNegative, values.yPositive, keyboard.analog.invert_y);
  document.querySelector("#stickCoordinates").textContent = `X ${x} · Y ${y}`;
  const dot = document.querySelector("#stickDot");
  dot.style.left = `${50 + x / 32767 * 42}%`;
  dot.style.top = `${50 + y / 32767 * 42}%`;
  const ring = document.querySelector("#deadzoneRing");
  ring.style.width = `${Math.max(8, keyboard.analog.deadzone_mm / keyboard.analog.saturation_mm * 84)}%`;
  const pairs = {
    simXNegValue: values.xNegative,
    simXPosValue: values.xPositive,
    simYNegValue: values.yNegative,
    simYPosValue: values.yPositive,
  };
  Object.entries(pairs).forEach(([id, raw]) => { document.querySelector(`#${id}`).textContent = (raw / 10).toFixed(1); });
}

function centerAnalog() {
  ["simXNegative", "simXPositive", "simYNegative", "simYPositive"].forEach(id => { document.querySelector(`#${id}`).value = 0; });
  updateAnalogMonitor();
}

function exerciseAnalog() {
  clearInterval(analogExerciseTimer);
  let step = 0;
  const pattern = [
    [0, 24, 0, 0], [0, 32, 22, 0], [0, 0, 30, 0], [26, 0, 17, 0],
    [32, 0, 0, 0], [18, 0, 0, 25], [0, 0, 0, 32], [0, 20, 0, 18], [0, 0, 0, 0],
  ];
  analogExerciseTimer = setInterval(() => {
    const values = pattern[step++];
    if (!values) {
      clearInterval(analogExerciseTimer);
      analogExerciseTimer = null;
      centerAnalog();
      return;
    }
    ["simXNegative", "simXPositive", "simYNegative", "simYPositive"].forEach((id, index) => { document.querySelector(`#${id}`).value = values[index]; });
    updateAnalogMonitor();
  }, 180);
}

/* Validation and KBS codec */
const crcTable = (() => {
  const table = [];
  for (let number = 0; number < 256; number += 1) {
    let checksum = number;
    for (let bit = 0; bit < 8; bit += 1) checksum = checksum & 1 ? 0xedb88320 ^ (checksum >>> 1) : checksum >>> 1;
    table[number] = checksum >>> 0;
  }
  return table;
})();

function crc32(bytes) {
  let checksum = 0xffffffff;
  for (const byte of bytes) checksum = crcTable[(checksum ^ byte) & 255] ^ (checksum >>> 8);
  return (checksum ^ 0xffffffff) >>> 0;
}

function rgb565(hex) {
  const value = parseInt(hex.slice(1), 16);
  const red = value >> 16;
  const green = value >> 8 & 255;
  const blue = value & 255;
  return (red >> 3) << 11 | (green >> 2) << 5 | blue >> 3;
}

function rgb888(value) {
  const red = Math.floor((value >> 11 & 31) * 255 / 31);
  const green = Math.floor((value >> 5 & 63) * 255 / 63);
  const blue = Math.floor((value & 31) * 255 / 31);
  return `#${[red, green, blue].map(component => component.toString(16).padStart(2, "0")).join("")}`;
}

function validateAction(widget, screenIds, minimum, maximum) {
  const action = widget.action == null ? {} : widget.action;
  if (!action || typeof action !== "object" || Array.isArray(action)) throw Error(`Invalid action on widget ${widget.id}`);
  const actionType = action.type ?? "none";
  const target = action.target_screen ?? 0;
  const arg0 = action.arg0 ?? 0;
  const arg1 = action.arg1 ?? 0;
  const flags = action.flags ?? 0;
  if (!ACTIONS[actionType] && actionType !== "none") throw Error(`Invalid action on widget ${widget.id}`);
  if (![target, arg0, arg1, flags].every(Number.isInteger) || target < 0 || target > 0xffff || arg0 < 0 || arg0 > 0xffff || arg1 < 0 || arg1 > 0xffffffff || flags !== 0) throw Error(`Invalid action fields on widget ${widget.id}`);
  if (actionType !== "navigate" && target !== 0) throw Error(`Only navigation may target a screen (${widget.id})`);
  let valid = true;
  if (["none", "navigate"].includes(actionType)) valid = arg0 === 0 && arg1 === 0;
  else if (actionType === "rgb_color") valid = arg0 === 0 && arg1 <= 0xffffff;
  else if (actionType === "rgb_effect") valid = arg0 <= 4 && arg1 === 0;
  else if (actionType === "profile") valid = arg0 <= 3 && arg1 === 0;
  else if (actionType === "brightness") valid = minimum >= 0 && maximum <= 100 && arg0 === 0 && arg1 === 0;
  else if (actionType === "actuation") valid = minimum >= 0 && maximum <= 0xff && arg0 === 0 && arg1 === 0;
  else if (actionType === "rapid_trigger") valid = minimum >= 0 && maximum <= 1 && arg0 <= 0xff && arg1 <= 0xff;
  else if (actionType === "hid_key") valid = arg0 !== 0 && (arg0 < 152 || (arg0 >= 0xe0 && arg0 <= 0xe7)) && arg1 === 0;
  else if (actionType === "media_key") valid = arg0 !== 0 && arg1 === 0;
  if (!valid || (actionType === "navigate" && !screenIds.has(target))) throw Error(`Invalid action arguments on widget ${widget.id}`);
}

function validateScreens(documentValue = doc) {
  const documentFlags = documentValue.flags ?? 0;
  if (!documentValue || typeof documentValue !== "object" || Array.isArray(documentValue) || documentValue.format !== "kb7-screen-v1" || !Array.isArray(documentValue.screens) || !documentValue.screens.length || documentValue.screens.length > 16 || !Number.isInteger(documentFlags) || documentFlags !== 0) throw Error("Invalid screen document");
  const screenIds = new Set();
  const widgetIds = new Set();
  const encoder = new TextEncoder();
  const colorPattern = /^#[0-9a-f]{6}$/i;
  for (const item of documentValue.screens) {
    const name = item.name ?? "";
    const flags = item.flags ?? 0;
    if (!item || typeof item !== "object" || Array.isArray(item) || !Number.isInteger(item.id) || item.id < 0 || item.id > 0xffff || screenIds.has(item.id) || !Number.isInteger(flags) || flags !== 0 || typeof name !== "string" || encoder.encode(name).length > 0xffff || !colorPattern.test(item.background ?? "#08111f") || !Array.isArray(item.widgets)) throw Error("Invalid or duplicate screen");
    screenIds.add(item.id);
  }
  for (const item of documentValue.screens) {
    for (const widget of item.widgets) {
      const minimum = widget.minimum ?? 0;
      const maximum = widget.maximum ?? 100;
      const value = widget.value ?? minimum;
      const textValue = widget.text ?? "";
      const numbers = [widget.id, widget.x, widget.y, widget.width, widget.height, minimum, maximum, value];
      const flags = widget.flags ?? 0;
      if (!widget || typeof widget !== "object" || Array.isArray(widget) || !numbers.every(Number.isInteger) || widget.id < 0 || widget.id > 0xffff || widgetIds.has(widget.id) || !TYPES[widget.type] || !Number.isInteger(flags) || flags !== 0 || widget.x < 0 || widget.y < 0 || widget.width < 1 || widget.height < 1 || widget.x + widget.width > 480 || widget.y + widget.height > 800 || minimum < -32768 || maximum > 32767 || minimum > maximum || value < minimum || value > maximum || typeof textValue !== "string" || encoder.encode(textValue).length > 0xffff || !colorPattern.test(widget.foreground ?? "#f5f7ff") || !colorPattern.test(widget.background ?? "#17243a")) throw Error(`Invalid widget ${widget.id}`);
      widgetIds.add(widget.id);
      validateAction(widget, screenIds, minimum, maximum);
    }
  }
  if (!Number.isInteger(documentValue.boot_screen) || !screenIds.has(documentValue.boot_screen) || widgetIds.size > 128) throw Error("Invalid boot screen/object count");
}

function validateProfile() {
  validateScreens();
  const colorPattern = /^#[0-9a-f]{6}$/i;
  const lighting = keyboard.lighting;
  const finiteNumber = value => typeof value === "number" && Number.isFinite(value);
  const object = value => value && typeof value === "object" && !Array.isArray(value);
  if (!object(lighting) || typeof lighting.enabled !== "boolean" || !object(lighting.per_key) || Object.keys(lighting.per_key).length > KEY_IDS.length) throw Error("Invalid lighting settings");
  if (!colorPattern.test(lighting.primary) || !colorPattern.test(lighting.secondary) || !colorPattern.test(lighting.reactive)) throw Error("Lighting colors must use #rrggbb");
  if (!["static", "gradient", "aurora", "reactive", "heatmap"].includes(lighting.effect)) throw Error("Unsupported lighting effect");
  if (!["east", "west", "north", "south", "radial"].includes(lighting.direction) || !Number.isInteger(lighting.brightness) || lighting.brightness < 0 || lighting.brightness > 100 || !Number.isInteger(lighting.speed) || lighting.speed < 0 || lighting.speed > 100) throw Error("Invalid lighting motion settings");
  for (const [keyId, color] of Object.entries(lighting.per_key)) if (!KEY_BY_ID[keyId] || !colorPattern.test(color)) throw Error(`Invalid per-key color ${keyId}`);
  const switches = keyboard.switches;
  if (!object(switches) || typeof switches.rapid_trigger !== "boolean" || !object(switches.per_key) || Object.keys(switches.per_key).length > KEY_IDS.length || !finiteNumber(switches.travel_mm) || !finiteNumber(switches.actuation_mm) || switches.travel_mm < .5 || switches.travel_mm > 6 || switches.actuation_mm < .1 || switches.actuation_mm > switches.travel_mm) throw Error("Invalid Hall travel or actuation range");
  if (!finiteNumber(switches.rapid_press_delta_mm) || !finiteNumber(switches.rapid_release_delta_mm) || switches.rapid_press_delta_mm < .05 || switches.rapid_press_delta_mm > 1.5 || switches.rapid_release_delta_mm < .05 || switches.rapid_release_delta_mm > 1.5) throw Error("Invalid Rapid Trigger deltas");
  for (const [keyId, override] of Object.entries(switches.per_key)) if (!KEY_BY_ID[keyId] || !object(override) || !finiteNumber(override.actuation_mm) || override.actuation_mm < .1 || override.actuation_mm > switches.travel_mm || typeof override.rapid_trigger !== "boolean") throw Error(`Invalid switch override ${keyId}`);
  const analog = keyboard.analog;
  if (!object(analog) || typeof analog.enabled !== "boolean" || typeof analog.invert_x !== "boolean" || typeof analog.invert_y !== "boolean" || typeof analog.digital_passthrough !== "boolean" || !object(analog.bindings) || Object.keys(analog.bindings).sort().join(",") !== "x_negative,x_positive,y_negative,y_positive") throw Error("Invalid analog settings");
  const bindings = Object.values(analog.bindings);
  if (new Set(bindings).size !== 4 || bindings.some(keyId => !KEY_BY_ID[keyId])) throw Error("Analog bindings must use four distinct logical keys");
  if (!finiteNumber(analog.deadzone_mm) || !finiteNumber(analog.saturation_mm) || analog.deadzone_mm < 0 || analog.deadzone_mm > switches.travel_mm - .1 || analog.deadzone_mm >= analog.saturation_mm || analog.saturation_mm < .1 || analog.saturation_mm > switches.travel_mm) throw Error("Invalid analog deadzone or saturation");
  if (!["gamepad_left_stick", "gamepad_right_stick", "gamepad_triggers"].includes(analog.output) || !["linear", "exponential", "s_curve"].includes(analog.curve) || !Number.isInteger(analog.smoothing) || analog.smoothing < 0 || analog.smoothing > 10) throw Error("Invalid analog output settings");
  if (new TextEncoder().encode(profileDocument().name).length > 63) throw Error("Profile name is longer than 63 UTF-8 bytes");
  return profileDocument();
}

function compileScreens() {
  validateScreens();
  const encoder = new TextEncoder();
  const strings = [];
  const screens = [];
  const widgets = [];
  let stringLength = 0;
  let first = 0;
  const addString = value => {
    const bytes = encoder.encode(value || "");
    const offset = stringLength;
    strings.push(bytes);
    stringLength += bytes.length;
    return [offset, bytes.length];
  };
  for (const item of doc.screens) {
    const name = addString(item.name || "");
    screens.push({...item, first, count: item.widgets.length, name});
    for (const widget of item.widgets) widgets.push({...widget, encodedText: addString(widget.text)});
    first += item.widgets.length;
  }
  const total = 48 + screens.length * 16 + widgets.length * 40 + stringLength;
  if (total > 0x200000 - 64) throw Error("Compiled screen store exceeds firmware slot capacity");
  const buffer = new ArrayBuffer(total);
  const view = new DataView(buffer);
  const bytes = new Uint8Array(buffer);
  const screensOffset = 48;
  const widgetsOffset = screensOffset + screens.length * 16;
  const stringsOffset = widgetsOffset + widgets.length * 40;
  let offset = screensOffset;
  for (const item of screens) {
    view.setUint16(offset, item.id, true);
    view.setUint16(offset + 2, item.first, true);
    view.setUint16(offset + 4, item.count, true);
    view.setUint16(offset + 6, rgb565(item.background || "#08111f"), true);
    view.setUint32(offset + 8, item.name[0], true);
    view.setUint16(offset + 12, item.name[1], true);
    offset += 16;
  }
  offset = widgetsOffset;
  for (const widget of widgets) {
    const action = widget.action || {type: "none"};
    view.setUint16(offset, widget.id, true);
    view.setUint8(offset + 2, TYPES[widget.type]);
    view.setUint8(offset + 3, widget.flags || 0);
    [widget.x, widget.y, widget.width, widget.height].forEach((value, index) => view.setInt16(offset + 4 + index * 2, value, true));
    view.setUint16(offset + 12, rgb565(widget.foreground || "#f5f7ff"), true);
    view.setUint16(offset + 14, rgb565(widget.background || "#17243a"), true);
    view.setInt16(offset + 16, widget.minimum ?? 0, true);
    view.setInt16(offset + 18, widget.maximum ?? 100, true);
    view.setInt16(offset + 20, widget.value ?? widget.minimum ?? 0, true);
    view.setUint16(offset + 22, action.target_screen || 0, true);
    view.setUint8(offset + 24, ACTIONS[action.type || "none"]);
    view.setUint8(offset + 25, action.flags || 0);
    view.setUint16(offset + 26, action.arg0 || 0, true);
    view.setUint32(offset + 28, action.arg1 || 0, true);
    view.setUint32(offset + 32, widget.encodedText[0], true);
    view.setUint16(offset + 36, widget.encodedText[1], true);
    offset += 40;
  }
  offset = stringsOffset;
  for (const value of strings) {
    bytes.set(value, offset);
    offset += value.length;
  }
  view.setUint32(0, 0x3153424b, true);
  view.setUint16(4, 1, true);
  view.setUint16(6, 48, true);
  view.setUint32(8, total, true);
  view.setUint32(12, crc32(bytes.slice(48)), true);
  view.setUint16(16, screens.length, true);
  view.setUint16(18, doc.boot_screen, true);
  view.setUint16(20, widgets.length, true);
  view.setUint16(22, doc.flags || 0, true);
  view.setUint32(24, screensOffset, true);
  view.setUint32(28, widgetsOffset, true);
  view.setUint32(32, stringsOffset, true);
  view.setUint32(36, stringLength, true);
  return bytes;
}

function parseBinary(bytes) {
  if (bytes.length > 0x200000 - 64) throw Error("KBS exceeds the firmware screen-slot payload capacity");
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (bytes.length < 48 || view.getUint32(0, true) !== 0x3153424b || view.getUint16(4, true) !== 1 || view.getUint16(6, true) !== 48 || view.getUint32(8, true) !== bytes.length || crc32(bytes.slice(48)) !== view.getUint32(12, true)) throw Error("Invalid KBS header or CRC");
  const screenCount = view.getUint16(16, true);
  const boot = view.getUint16(18, true);
  const widgetCount = view.getUint16(20, true);
  const screensOffset = view.getUint32(24, true);
  const widgetsOffset = view.getUint32(28, true);
  const stringsOffset = view.getUint32(32, true);
  const stringLength = view.getUint32(36, true);
  if (screenCount < 1 || screenCount > 16 || widgetCount > 128 || view.getUint16(22, true) !== 0 || view.getUint32(40, true) !== 0 || view.getUint32(44, true) !== 0 || screensOffset !== 48 || widgetsOffset !== screensOffset + screenCount * 16 || stringsOffset !== widgetsOffset + widgetCount * 40 || stringsOffset + stringLength !== bytes.length) throw Error("Invalid KBS layout");
  const decoder = new TextDecoder("utf-8", {fatal: true});
  decoder.decode(bytes.slice(stringsOffset));
  const string = (offset, length) => {
    if (offset > stringLength || length > stringLength - offset) throw Error("String outside KBS pool");
    return decoder.decode(bytes.slice(stringsOffset + offset, stringsOffset + offset + length));
  };
  const widgets = [];
  const widgetIds = new Set();
  for (let index = 0; index < widgetCount; index += 1) {
    const offset = widgetsOffset + index * 40;
    const type = TYPE_NAMES[view.getUint8(offset + 2)];
    const action = ACTION_NAMES[view.getUint8(offset + 24)];
    const id = view.getUint16(offset, true);
    if (!type || !action || widgetIds.has(id) || view.getUint8(offset + 3) !== 0 || view.getUint8(offset + 25) !== 0 || view.getUint16(offset + 38, true) !== 0) throw Error("Unsupported/duplicate widget or reserved field");
    widgetIds.add(id);
    widgets.push({
      id, type, flags: 0,
      x: view.getInt16(offset + 4, true), y: view.getInt16(offset + 6, true),
      width: view.getInt16(offset + 8, true), height: view.getInt16(offset + 10, true),
      foreground: rgb888(view.getUint16(offset + 12, true)), background: rgb888(view.getUint16(offset + 14, true)),
      minimum: view.getInt16(offset + 16, true), maximum: view.getInt16(offset + 18, true), value: view.getInt16(offset + 20, true),
      text: string(view.getUint32(offset + 32, true), view.getUint16(offset + 36, true)),
      action: {type: action, flags: 0, target_screen: view.getUint16(offset + 22, true), arg0: view.getUint16(offset + 26, true), arg1: view.getUint32(offset + 28, true)},
    });
  }
  const screens = [];
  const screenIds = new Set();
  let nextWidget = 0;
  for (let index = 0; index < screenCount; index += 1) {
    const offset = screensOffset + index * 16;
    const first = view.getUint16(offset + 2, true);
    const count = view.getUint16(offset + 4, true);
    const id = view.getUint16(offset, true);
    if (screenIds.has(id) || view.getUint16(offset + 14, true) !== 0 || first !== nextWidget || first + count > widgetCount) throw Error("Bad screen widget range/ID/flags");
    screenIds.add(id);
    screens.push({
      id, name: string(view.getUint32(offset + 8, true), view.getUint16(offset + 12, true)),
      background: rgb888(view.getUint16(offset + 6, true)), flags: 0, widgets: widgets.slice(first, first + count),
    });
    nextWidget += count;
  }
  if (nextWidget !== widgetCount || !screenIds.has(boot)) throw Error("Invalid boot screen/widget partition");
  const result = {format: "kb7-screen-v1", boot_screen: boot, flags: 0, screens};
  validateScreens(result);
  return result;
}

function download(name, data, mimeType) {
  const blob = new Blob([data], {type: mimeType});
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function fileStem() {
  return (document.querySelector("#projectName").value.trim() || "kb7-profile").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "kb7-profile";
}

function loadProfile(profile, notify = true) {
  const object = value => value && typeof value === "object" && !Array.isArray(value);
  if (!object(profile) || profile.format !== "kb7-profile-v1") throw Error("Unsupported profile format");
  if (typeof profile.name !== "string" || !profile.name.trim() || new TextEncoder().encode(profile.name).length > 63) throw Error("Invalid profile name");
  if (!object(profile.screen_document) || !object(profile.lighting) || !object(profile.switches) || !object(profile.analog)) throw Error("Profile sections must be objects");
  const previous = {doc, keyboard, name: document.querySelector("#projectName").value};
  try {
    doc = clone(profile.screen_document);
    keyboard = {
      lighting: {...clone(DEFAULT_KEYBOARD.lighting), ...clone(profile.lighting || {}), per_key: clone(profile.lighting?.per_key || {})},
      switches: {...clone(DEFAULT_KEYBOARD.switches), ...clone(profile.switches || {}), per_key: clone(profile.switches?.per_key || {})},
      analog: {...clone(DEFAULT_KEYBOARD.analog), ...clone(profile.analog || {}), bindings: {...clone(DEFAULT_KEYBOARD.analog.bindings), ...clone(profile.analog?.bindings || {})}},
    };
    document.querySelector("#projectName").value = profile.name || "Imported profile";
    validateProfile();
  } catch (error) {
    doc = previous.doc;
    keyboard = previous.keyboard;
    document.querySelector("#projectName").value = previous.name;
    throw error;
  }
  activeScreen = doc.boot_screen;
  selected = null;
  nextId = Math.max(100, ...doc.screens.flatMap(item => item.widgets.map(widget => widget.id + 1)));
  if (notify) toast(`${profile.name || "Profile"} imported`);
  saveLocal();
}

function setDisplayMode(nextMode) {
  if (!["design", "preview", "trace"].includes(nextMode)) return;
  if (nextMode !== "trace" && touchTrace.active) {
    const pointerId = touchTrace.pointerId;
    touchTrace.active = false;
    touchTrace.pointerId = null;
    touchTrace.pressure = 0;
    if (pointerId !== null && display.hasPointerCapture?.(pointerId)) display.releasePointerCapture(pointerId);
  }
  mode = nextMode;
  document.querySelectorAll("#displayMode button").forEach(item => item.classList.toggle("active", item.dataset.mode === mode));
  selected = null;
  renderDisplayWorkspace();
}

/* Event wiring */
document.querySelectorAll("#workspaceNav button").forEach(button => { button.onclick = () => setWorkspace(button.dataset.workspace); });
document.querySelectorAll("#palette button").forEach(button => {
  button.ondragstart = event => event.dataTransfer.setData("text/kb7-widget", button.dataset.type);
  button.ondblclick = () => addWidget(button.dataset.type);
});
display.ondragover = event => {
  if (mode !== "design") return;
  event.preventDefault();
  display.classList.add("dragover");
};
display.ondragleave = () => display.classList.remove("dragover");
display.ondrop = event => {
  if (mode !== "design") return;
  event.preventDefault();
  display.classList.remove("dragover");
  const type = event.dataTransfer.getData("text/kb7-widget");
  if (!TYPES[type]) return;
  const rectangle = display.getBoundingClientRect();
  addWidget(type, Math.round((event.clientX - rectangle.left) * 480 / rectangle.width), Math.round((event.clientY - rectangle.top) * 800 / rectangle.height));
};
display.addEventListener("pointerdown", beginTouchTrace);
display.addEventListener(touchMoveEvent, moveTouchTrace);
display.addEventListener("pointerup", endTouchTrace);
display.addEventListener("pointercancel", endTouchTrace);
display.addEventListener("lostpointercapture", event => {
  if (touchTrace.active && event.pointerId === touchTrace.pointerId) endTouchTrace(event);
});
document.querySelectorAll("#displayMode button").forEach(button => {
  button.onclick = () => setDisplayMode(button.dataset.mode);
});
document.querySelector("#addScreen").onclick = () => {
  const id = Math.max(0, ...doc.screens.map(item => item.id)) + 1;
  doc.screens.push({id, name: `Screen ${id}`, background: "#08111f", widgets: []});
  activeScreen = id;
  markDirty(renderDisplayWorkspace);
};
document.querySelector("#resetView").onclick = () => { activeScreen = doc.boot_screen; selected = null; renderDisplayWorkspace(); };

document.querySelectorAll("#lightingEffects button").forEach(button => {
  button.onclick = () => { keyboard.lighting.effect = button.dataset.effect; markDirty(renderLighting); };
});
document.querySelectorAll("#lightingZones button").forEach(button => { button.onclick = () => setZone("lighting", button.dataset.zone); });
document.querySelector("#lightingPlay").onclick = () => { lightingPlaying = !lightingPlaying; renderLighting(); };
document.querySelector("#lightingEnabled").onchange = event => { keyboard.lighting.enabled = event.target.checked; markDirty(renderLighting); };
[["lightingPrimary", "primary"], ["lightingSecondary", "secondary"], ["lightingReactive", "reactive"]].forEach(([id, property]) => {
  document.querySelector(`#${id}`).oninput = event => { keyboard.lighting[property] = event.target.value.toLowerCase(); markDirty(renderLighting); };
});
document.querySelector("#lightingBrightness").oninput = event => { keyboard.lighting.brightness = Number(event.target.value); markDirty(renderLighting); };
document.querySelector("#lightingSpeed").oninput = event => { keyboard.lighting.speed = Number(event.target.value); markDirty(renderLighting); };
document.querySelector("#lightingDirection").onchange = event => { keyboard.lighting.direction = event.target.value; markDirty(renderLighting); };
document.querySelector("#applyKeyColor").onclick = () => {
  lightingSelection.forEach(id => { keyboard.lighting.per_key[id] = keyboard.lighting.primary; });
  markDirty(renderLighting);
  toast(`Painted ${lightingSelection.size} ${lightingSelection.size === 1 ? "key" : "keys"}`);
};
document.querySelector("#clearKeyColors").onclick = () => {
  lightingSelection.forEach(id => { delete keyboard.lighting.per_key[id]; });
  markDirty(renderLighting);
  toast("Selected key colors cleared");
};

document.querySelectorAll("#switchZones button").forEach(button => { button.onclick = () => setZone("switches", button.dataset.zone); });
document.querySelectorAll("#switchPresets button").forEach(button => {
  button.onclick = () => {
    const presets = {
      gaming: {actuation_mm: 1.0, rapid_trigger: true, rapid_press_delta_mm: .1, rapid_release_delta_mm: .1},
      balanced: {actuation_mm: 1.6, rapid_trigger: true, rapid_press_delta_mm: .15, rapid_release_delta_mm: .15},
      typing: {actuation_mm: 2.4, rapid_trigger: false, rapid_press_delta_mm: .25, rapid_release_delta_mm: .25},
    };
    Object.assign(keyboard.switches, presets[button.dataset.preset], {per_key: {}});
    document.querySelectorAll("#switchPresets button").forEach(item => item.classList.toggle("active", item === button));
    markDirty(renderSwitches);
    toast(`${title(button.dataset.preset)} switch preset applied`);
  };
});
document.querySelector("#actuationPoint").oninput = event => applyActuation(Number(event.target.value) / 10);
document.querySelector("#fullTravel").oninput = event => {
  keyboard.switches.travel_mm = Number(event.target.value) / 10;
  keyboard.switches.actuation_mm = Math.min(keyboard.switches.actuation_mm, keyboard.switches.travel_mm);
  Object.values(keyboard.switches.per_key).forEach(override => { override.actuation_mm = Math.min(override.actuation_mm, keyboard.switches.travel_mm); });
  keyboard.analog.saturation_mm = Math.min(keyboard.analog.saturation_mm, keyboard.switches.travel_mm);
  keyboard.analog.deadzone_mm = Math.min(keyboard.analog.deadzone_mm, Math.max(0, keyboard.analog.saturation_mm - .01));
  markDirty(renderSwitches);
};
document.querySelector("#rapidTrigger").onchange = event => { keyboard.switches.rapid_trigger = event.target.checked; markDirty(renderSwitches); };
document.querySelector("#rapidPress").oninput = event => { keyboard.switches.rapid_press_delta_mm = Number(event.target.value) / 100; markDirty(renderSwitches); };
document.querySelector("#rapidRelease").oninput = event => { keyboard.switches.rapid_release_delta_mm = Number(event.target.value) / 100; markDirty(renderSwitches); };
document.querySelector("#clearSwitchOverrides").onclick = () => {
  switchSelection.forEach(id => { delete keyboard.switches.per_key[id]; });
  markDirty(renderSwitches);
  toast("Selected switch overrides cleared");
};
document.querySelector("#resetSwitches").onclick = () => {
  keyboard.switches = clone(DEFAULT_KEYBOARD.switches);
  switchSelection = new Set(ZONES.wasd);
  markDirty(renderSwitches);
  toast("Switch tuning reset");
};
document.querySelector("#switchTravelSimulation").oninput = updateTravelLab;

const bindingFields = {
  bindingXNegative: "x_negative",
  bindingXPositive: "x_positive",
  bindingYNegative: "y_negative",
  bindingYPositive: "y_positive",
};
Object.entries(bindingFields).forEach(([id, field]) => {
  document.querySelector(`#${id}`).onchange = event => {
    const duplicate = Object.entries(keyboard.analog.bindings).find(([name, value]) => name !== field && value === event.target.value);
    if (duplicate) {
      event.target.value = keyboard.analog.bindings[field];
      toast(`${KEY_BY_ID[event.target.value].label} is already assigned to another direction`);
      return;
    }
    keyboard.analog.bindings[field] = event.target.value;
    markDirty(renderAnalog);
  };
});
document.querySelectorAll("#analogPresets button").forEach(button => {
  button.onclick = () => {
    const preset = button.dataset.preset;
    if (preset === "arrows") Object.assign(keyboard.analog, {output: "gamepad_left_stick", curve: "linear", bindings: {x_negative: "LEFT", x_positive: "RIGHT", y_negative: "UP", y_positive: "DOWN"}});
    if (preset === "wasd") Object.assign(keyboard.analog, {output: "gamepad_left_stick", curve: "linear", bindings: {x_negative: "A", x_positive: "D", y_negative: "W", y_positive: "S"}});
    if (preset === "racing") Object.assign(keyboard.analog, {output: "gamepad_triggers", curve: "exponential", bindings: {x_negative: "A", x_positive: "D", y_negative: "W", y_positive: "S"}});
    document.querySelectorAll("#analogPresets button").forEach(item => item.classList.toggle("active", item === button));
    centerAnalog();
    markDirty(renderAnalog);
    toast(`${title(preset)} analog preset applied`);
  };
});
document.querySelector("#analogEnabled").onchange = event => { keyboard.analog.enabled = event.target.checked; markDirty(renderAnalog); };
document.querySelector("#analogOutput").onchange = event => { keyboard.analog.output = event.target.value; markDirty(renderAnalog); };
document.querySelector("#analogCurve").onchange = event => { keyboard.analog.curve = event.target.value; markDirty(renderAnalog); };
document.querySelector("#analogDeadzone").oninput = event => {
  keyboard.analog.deadzone_mm = Math.min(Number(event.target.value) / 100, keyboard.analog.saturation_mm - .01);
  markDirty(renderAnalog);
};
document.querySelector("#analogSaturation").oninput = event => {
  keyboard.analog.saturation_mm = clamp(Number(event.target.value) / 100, keyboard.analog.deadzone_mm + .01, keyboard.switches.travel_mm);
  markDirty(renderAnalog);
};
document.querySelector("#analogSmoothing").oninput = event => { keyboard.analog.smoothing = Number(event.target.value); markDirty(renderAnalog); };
document.querySelector("#invertX").onchange = event => { keyboard.analog.invert_x = event.target.checked; markDirty(renderAnalog); };
document.querySelector("#invertY").onchange = event => { keyboard.analog.invert_y = event.target.checked; markDirty(renderAnalog); };
document.querySelector("#digitalPassthrough").onchange = event => { keyboard.analog.digital_passthrough = event.target.checked; markDirty(renderAnalog); };
["simXNegative", "simXPositive", "simYNegative", "simYPositive"].forEach(id => { document.querySelector(`#${id}`).oninput = updateAnalogMonitor; });
document.querySelector("#centerAnalog").onclick = centerAnalog;
document.querySelector("#randomAnalog").onclick = exerciseAnalog;

document.querySelector("#projectName").oninput = saveLocal;
document.querySelector("#exportJson").onclick = () => {
  try {
    validateScreens();
    download(`${fileStem()}-screens.json`, `${JSON.stringify(doc, null, 2)}\n`, "application/json");
    toast("Screen JSON exported");
  } catch (error) { toast(error.message); }
};
document.querySelector("#exportProfile").onclick = () => {
  try {
    const profile = validateProfile();
    download(`${fileStem()}.kb7.json`, `${JSON.stringify(profile, null, 2)}\n`, "application/json");
    toast("Complete offline profile exported");
  } catch (error) { toast(error.message); }
};
document.querySelector("#exportBinary").onclick = () => {
  try {
    const data = compileScreens();
    download(`${fileStem()}.kbs`, data, "application/octet-stream");
    toast(`${data.length} byte screen store exported`);
  } catch (error) {
    document.querySelector("#formatHealth").textContent = "Error";
    toast(error.message);
  }
};
document.querySelector("#fileInput").onchange = async event => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    if (file.name.endsWith(".kbs")) {
      doc = parseBinary(new Uint8Array(await file.arrayBuffer()));
      validateScreens();
      activeScreen = doc.boot_screen;
      selected = null;
      nextId = Math.max(100, ...doc.screens.flatMap(item => item.widgets.map(widget => widget.id + 1)));
      saveLocal();
      renderDisplayWorkspace();
      toast(`${file.name} screen store imported`);
    } else {
      const parsed = JSON.parse(await file.text());
      if (parsed.format === "kb7-profile-v1") loadProfile(parsed);
      else if (parsed.format === "kb7-screen-v1") {
        validateScreens(parsed);
        doc = parsed;
        activeScreen = doc.boot_screen;
        selected = null;
        nextId = Math.max(100, ...doc.screens.flatMap(item => item.widgets.map(widget => widget.id + 1)));
        saveLocal();
        renderDisplayWorkspace();
        toast(`${file.name} screens imported`);
      } else throw Error("Unsupported JSON format");
    }
  } catch (error) {
    toast(`Import failed: ${error.message}`);
  }
  event.target.value = "";
};

populateBindingSelectors();
loadLocal();
const query = new URLSearchParams(window.location.search);
const requestedWorkspace = query.get("workspace");
const requestedDisplayMode = query.get("mode");
if (["display", "lighting", "switches", "analog"].includes(requestedWorkspace)) activeWorkspace = requestedWorkspace;
if (["design", "preview", "trace"].includes(requestedDisplayMode)) mode = requestedDisplayMode;
document.querySelectorAll("#displayMode button").forEach(item => item.classList.toggle("active", item.dataset.mode === mode));
renderDisplayWorkspace();
renderLighting();
renderSwitches();
renderAnalog();
setWorkspace(activeWorkspace);
saveLocal();
