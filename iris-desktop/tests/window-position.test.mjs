import assert from "node:assert/strict";
import test from "node:test";

const robotWindowSize = { width: 260, height: 360 };

function defaultRobotPosition(screen, windowSize = robotWindowSize) {
  return {
    x: Math.max(screen.x, screen.x + screen.width - windowSize.width - 28),
    y: Math.max(screen.y, screen.y + screen.height - windowSize.height - 36)
  };
}

function recoverOffscreenPosition(saved, screens, windowSize = robotWindowSize) {
  const primary = screens[0] ?? { x: 0, y: 0, width: 1440, height: 900 };
  if (!saved) return defaultRobotPosition(primary, windowSize);

  const isVisible = screens.some((screen) => {
    const rightEdge = saved.x + windowSize.width;
    const bottomEdge = saved.y + windowSize.height;
    return (
      saved.x >= screen.x &&
      saved.y >= screen.y &&
      rightEdge <= screen.x + screen.width &&
      bottomEdge <= screen.y + screen.height
    );
  });

  return isVisible ? saved : defaultRobotPosition(primary, windowSize);
}

test("uses lower-right default when no position is saved", () => {
  assert.deepEqual(
    recoverOffscreenPosition(null, [{ x: 0, y: 0, width: 1440, height: 900 }]),
    { x: 1152, y: 504 }
  );
});

test("keeps a visible saved position", () => {
  const saved = { x: 300, y: 200 };
  assert.deepEqual(
    recoverOffscreenPosition(saved, [{ x: 0, y: 0, width: 1440, height: 900 }]),
    saved
  );
});

test("recovers off-screen positions after monitor changes", () => {
  assert.deepEqual(
    recoverOffscreenPosition(
      { x: 2200, y: 100 },
      [{ x: 0, y: 0, width: 1440, height: 900 }]
    ),
    { x: 1152, y: 504 }
  );
});
