"use strict";

(function exposeTouchTraceMath(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.TouchTraceMath = api;
})(typeof globalThis !== "undefined" ? globalThis : this, () => {
  const WIDTH = 480;
  const HEIGHT = 800;
  const clamp = (value, minimum, maximum) => Math.max(minimum, Math.min(maximum, value));

  function coordinate(clientX, clientY, rectangle) {
    if (!rectangle || rectangle.width <= 0 || rectangle.height <= 0) throw Error("Invalid display rectangle");
    return {
      x: clamp((clientX - rectangle.left) * WIDTH / rectangle.width, 0, WIDTH - 1),
      y: clamp((clientY - rectangle.top) * HEIGHT / rectangle.height, 0, HEIGHT - 1),
    };
  }

  function vector(x, y, originX, originY, deadzone = 0) {
    const safeOriginX = clamp(originX, 0, WIDTH - 1);
    const safeOriginY = clamp(originY, 0, HEIGHT - 1);
    const dx = clamp(x, 0, WIDTH - 1) - safeOriginX;
    const dy = clamp(y, 0, HEIGHT - 1) - safeOriginY;
    const xExtent = dx < 0 ? safeOriginX : WIDTH - 1 - safeOriginX;
    const yExtent = dy < 0 ? safeOriginY : HEIGHT - 1 - safeOriginY;
    const rawX = clamp(dx / Math.max(1, xExtent), -1, 1);
    const rawY = clamp(dy / Math.max(1, yExtent), -1, 1);
    const rawMagnitude = Math.hypot(rawX, rawY);
    const limitedMagnitude = Math.min(1, rawMagnitude);
    const safeDeadzone = clamp(Number(deadzone) || 0, 0, .95);

    if (rawMagnitude === 0 || limitedMagnitude <= safeDeadzone) {
      return {x: 0, y: 0, magnitude: 0, rawX, rawY, rawMagnitude: limitedMagnitude};
    }

    const scaledMagnitude = (limitedMagnitude - safeDeadzone) / (1 - safeDeadzone);
    return {
      x: rawX / rawMagnitude * scaledMagnitude,
      y: rawY / rawMagnitude * scaledMagnitude,
      magnitude: scaledMagnitude,
      rawX,
      rawY,
      rawMagnitude: limitedMagnitude,
    };
  }

  return Object.freeze({WIDTH, HEIGHT, coordinate, vector});
});
