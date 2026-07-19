import assert from "node:assert/strict";
import test from "node:test";

const transitions = [
  ["STARTING", "BOOTED", "IDLE"],
  ["IDLE", "START_LISTENING", "LISTENING"],
  ["LISTENING", "TRANSCRIPTION_READY", "TRANSCRIBING"],
  ["TRANSCRIBING", "SUBMIT_COMMAND", "THINKING"],
  ["THINKING", "START_EXECUTION", "EXECUTING"],
  ["EXECUTING", "EXECUTION_SUCCEEDED", "SUCCESS"],
  ["SUCCESS", "ACKNOWLEDGED", "IDLE"],
  ["IDLE", "ENABLE_DND", "DO_NOT_DISTURB"],
  ["DO_NOT_DISTURB", "HIDE", "HIDDEN"],
  ["HIDDEN", "RESTORE", "IDLE"]
];

function transitionRobotState(current, event) {
  return transitions.find(([from, transitionEvent]) => {
    return from === current && transitionEvent === event;
  })?.[2] ?? current;
}

test("robot state transitions are deterministic", () => {
  let state = "STARTING";
  for (const event of [
    "BOOTED",
    "START_LISTENING",
    "TRANSCRIPTION_READY",
    "SUBMIT_COMMAND",
    "START_EXECUTION",
    "EXECUTION_SUCCEEDED",
    "ACKNOWLEDGED"
  ]) {
    state = transitionRobotState(state, event);
  }

  assert.equal(state, "IDLE");
});

test("unknown transitions keep the current state", () => {
  assert.equal(transitionRobotState("IDLE", "RESTORE"), "IDLE");
});

test("hidden tray restore returns to idle", () => {
  assert.equal(transitionRobotState("HIDDEN", "RESTORE"), "IDLE");
});
