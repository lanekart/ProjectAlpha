import { animationNameForState, type RobotState } from "../state/robotState";

type RobotProps = {
  state: RobotState;
  onClick: () => void;
};

export function Robot({ state, onClick }: RobotProps) {
  return (
    <button
      className="robot"
      data-animation={animationNameForState(state)}
      onClick={onClick}
      aria-label="Open IRIS panel"
    >
      <span className="antenna" />
      <span className="head">
        <span className="eye eye-left" />
        <span className="eye eye-right" />
        <span className="mouth" />
      </span>
      <span className="body">
        <span className="core" />
      </span>
      <span className="status-ring" />
    </button>
  );
}
