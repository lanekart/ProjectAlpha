export const robotStates = [
  "STARTING",
  "IDLE",
  "LISTENING",
  "TRANSCRIBING",
  "THINKING",
  "SPEAKING",
  "EXECUTING",
  "SUCCESS",
  "ERROR",
  "SLEEPING",
  "DO_NOT_DISTURB",
  "HIDDEN"
] as const;

export type RobotState = (typeof robotStates)[number];

export type RobotEvent =
  | "BOOTED"
  | "WAKE"
  | "START_LISTENING"
  | "STOP_LISTENING"
  | "TRANSCRIPTION_READY"
  | "SUBMIT_COMMAND"
  | "START_EXECUTION"
  | "EXECUTION_SUCCEEDED"
  | "EXECUTION_FAILED"
  | "ACKNOWLEDGED"
  | "SLEEP"
  | "ENABLE_DND"
  | "DISABLE_DND"
  | "HIDE"
  | "RESTORE";

export type Transition = {
  from: RobotState;
  event: RobotEvent;
  to: RobotState;
};

export const transitions: Transition[] = [
  { from: "STARTING", event: "BOOTED", to: "IDLE" },
  { from: "IDLE", event: "START_LISTENING", to: "LISTENING" },
  { from: "LISTENING", event: "STOP_LISTENING", to: "IDLE" },
  { from: "LISTENING", event: "TRANSCRIPTION_READY", to: "TRANSCRIBING" },
  { from: "TRANSCRIBING", event: "SUBMIT_COMMAND", to: "THINKING" },
  { from: "IDLE", event: "SUBMIT_COMMAND", to: "THINKING" },
  { from: "THINKING", event: "START_EXECUTION", to: "EXECUTING" },
  { from: "EXECUTING", event: "EXECUTION_SUCCEEDED", to: "SUCCESS" },
  { from: "EXECUTING", event: "EXECUTION_FAILED", to: "ERROR" },
  { from: "THINKING", event: "EXECUTION_FAILED", to: "ERROR" },
  { from: "SUCCESS", event: "ACKNOWLEDGED", to: "IDLE" },
  { from: "ERROR", event: "ACKNOWLEDGED", to: "IDLE" },
  { from: "IDLE", event: "SLEEP", to: "SLEEPING" },
  { from: "SLEEPING", event: "WAKE", to: "IDLE" },
  { from: "IDLE", event: "ENABLE_DND", to: "DO_NOT_DISTURB" },
  { from: "LISTENING", event: "ENABLE_DND", to: "DO_NOT_DISTURB" },
  { from: "THINKING", event: "ENABLE_DND", to: "DO_NOT_DISTURB" },
  { from: "DO_NOT_DISTURB", event: "DISABLE_DND", to: "IDLE" },
  { from: "IDLE", event: "HIDE", to: "HIDDEN" },
  { from: "SLEEPING", event: "HIDE", to: "HIDDEN" },
  { from: "DO_NOT_DISTURB", event: "HIDE", to: "HIDDEN" },
  { from: "HIDDEN", event: "RESTORE", to: "IDLE" }
];

export function transitionRobotState(
  current: RobotState,
  event: RobotEvent
): RobotState {
  return transitions.find((transition) => {
    return transition.from === current && transition.event === event;
  })?.to ?? current;
}

export function animationNameForState(state: RobotState): string {
  switch (state) {
    case "LISTENING":
      return "listen";
    case "TRANSCRIBING":
    case "THINKING":
      return "think";
    case "SPEAKING":
      return "speak";
    case "EXECUTING":
      return "execute";
    case "SUCCESS":
      return "success";
    case "ERROR":
      return "error";
    case "SLEEPING":
      return "sleep";
    case "DO_NOT_DISTURB":
      return "quiet";
    case "HIDDEN":
      return "paused";
    default:
      return "idle";
  }
}
