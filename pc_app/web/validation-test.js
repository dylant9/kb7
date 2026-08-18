"use strict";

/* Execute the browser's real validation functions under Node.  This prevents
 * the offline editor from drifting away from the C and Python store parsers. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync(__dirname + "/app.js", "utf8");
const extract = (start, end) => {
  const first = source.indexOf(start);
  const last = source.indexOf(end, first);
  assert(first >= 0 && last > first, `could not extract ${start}`);
  return source.slice(first, last);
};

const ACTIONS = {
  none: 0, navigate: 1, rgb_color: 0x10, rgb_effect: 0x11,
  brightness: 0x12, profile: 0x20, actuation: 0x21,
  rapid_trigger: 0x22, hid_key: 0x30, media_key: 0x31,
  host_event: 0x40,
};
const actionContext = {ACTIONS};
vm.runInNewContext(
  extract("function validateAction", "function validateScreens") +
    "; this.validateAction = validateAction;",
  actionContext,
);
const action = (type, arg0 = 0, arg1 = 0) => ({id: 1, action: {type, arg0, arg1}});
const screenIds = new Set([1]);
assert.doesNotThrow(() => actionContext.validateAction(action("rgb_effect", 4), screenIds, 0, 100));
assert.doesNotThrow(() => actionContext.validateAction(action("profile", 3), screenIds, 0, 100));
assert.doesNotThrow(() => actionContext.validateAction(action("hid_key", 4), screenIds, 0, 100));
assert.doesNotThrow(() => actionContext.validateAction(action("media_key", 0xe9), screenIds, 0, 100));
for (const invalid of [
  action("rgb_effect", 5), action("profile", 4),
  action("hid_key", 0), action("media_key", 0),
  {id: 1, action: {type: "none", flags: false}},
]) assert.throws(() => actionContext.validateAction(invalid, screenIds, 0, 100));

const colorContext = {};
vm.runInNewContext(
  extract("function rgb565", "function validateAction") +
    "; this.rgb888 = rgb888;",
  colorContext,
);
assert.equal(colorContext.rgb888(3), "#000018");

const keyboard = {
  lighting: {
    enabled: true, effect: "static", brightness: 50, speed: 50,
    direction: "east", primary: "#000000", secondary: "#ffffff",
    reactive: "#123456", per_key: {},
  },
  switches: {
    travel_mm: 3.2, actuation_mm: 1.6, rapid_trigger: true,
    rapid_press_delta_mm: 0.1, rapid_release_delta_mm: 0.1,
    per_key: {},
  },
  analog: {
    enabled: true, output: "gamepad_left_stick", curve: "linear",
    deadzone_mm: 0.1, saturation_mm: 3.2, smoothing: 2,
    invert_x: false, invert_y: false, digital_passthrough: true,
    bindings: {x_negative: "A", x_positive: "D", y_negative: "W", y_positive: "S"},
  },
};
const profileContext = {
  keyboard,
  validateScreens() {},
  KEY_IDS: ["A", "D", "W", "S"],
  KEY_BY_ID: {A: {}, D: {}, W: {}, S: {}},
  TextEncoder,
  profileDocument: () => ({name: "Profile"}),
};
vm.runInNewContext(
  extract("function validateProfile", "function compileScreens") +
    "; this.validateProfile = validateProfile;",
  profileContext,
);
assert.doesNotThrow(() => profileContext.validateProfile());

const invalidMutations = [
  value => { value.lighting.enabled = 1; },
  value => { value.switches.rapid_trigger = "yes"; },
  value => { value.switches.travel_mm = NaN; },
  value => { value.analog.enabled = 1; },
  value => { value.analog.invert_x = "false"; },
  value => { value.analog.digital_passthrough = 0; },
  value => { value.analog.deadzone_mm = Infinity; },
  value => { value.analog.deadzone_mm = 3.15; },
  value => { value.analog.bindings.extra = "A"; },
];
for (const mutate of invalidMutations) {
  const candidate = structuredClone(keyboard);
  mutate(candidate);
  profileContext.keyboard = candidate;
  assert.throws(() => profileContext.validateProfile());
}
profileContext.keyboard = keyboard;
profileContext.profileDocument = () => ({name: "x".repeat(64)});
assert.throws(() => profileContext.validateProfile());

const binaryContext = {};
vm.runInNewContext(
  extract("function parseBinary", "function download") +
    "; this.parseBinary = parseBinary;",
  binaryContext,
);
assert.throws(
  () => binaryContext.parseBinary(new Uint8Array(0x200000 - 63)),
  /screen-slot payload capacity/,
);
