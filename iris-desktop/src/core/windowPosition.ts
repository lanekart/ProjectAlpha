export type Point = {
  x: number;
  y: number;
};

export type Size = {
  width: number;
  height: number;
};

export type DisplayBounds = Point & Size;

export const robotWindowSize: Size = {
  width: 260,
  height: 360
};

export function defaultRobotPosition(
  screen: DisplayBounds,
  windowSize: Size = robotWindowSize
): Point {
  return {
    x: Math.max(screen.x, screen.x + screen.width - windowSize.width - 28),
    y: Math.max(screen.y, screen.y + screen.height - windowSize.height - 36)
  };
}

export function recoverOffscreenPosition(
  saved: Point | null,
  screens: DisplayBounds[],
  windowSize: Size = robotWindowSize
): Point {
  const primary = screens[0] ?? { x: 0, y: 0, width: 1440, height: 900 };
  if (!saved) {
    return defaultRobotPosition(primary, windowSize);
  }

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
