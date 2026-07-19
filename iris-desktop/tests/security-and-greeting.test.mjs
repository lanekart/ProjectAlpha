import assert from "node:assert/strict";
import test from "node:test";

const commandPolicies = {
  ARBITRARY_SHELL: {
    risk: "BLOCKED",
    reason: "IRIS never passes raw user text to a shell."
  },
  CLOSE_APP: {
    risk: "CONFIRM_ONCE",
    reason: "Closing an app may discard unsaved work."
  }
};

function redactSecrets(message) {
  return message
    .replace(/(access_token=)[^&\s]+/gi, "$1[REDACTED]")
    .replace(/(refresh_token=)[^&\s]+/gi, "$1[REDACTED]")
    .replace(/(client_secret=)[^&\s]+/gi, "$1[REDACTED]")
    .replace(/(code=)[^&\s]+/gi, "$1[REDACTED]")
    .replace(/(authorization:\s*bearer\s+)[^\s]+/gi, "$1[REDACTED]");
}

function minutesFromClock(value) {
  const [hours, minutes] = value.split(":").map(Number);
  return hours * 60 + minutes;
}

function shouldDeliverMorningGreeting({ now, config, lastGreeting }) {
  const current = now.getHours() * 60 + now.getMinutes();
  const inWindow =
    current >= minutesFromClock(config.morningWindowStart) &&
    current <= minutesFromClock(config.morningWindowEnd);
  if (!inWindow) return false;

  const today = `${now.getFullYear()}-${`${now.getMonth() + 1}`.padStart(2, "0")}-${`${now.getDate()}`.padStart(2, "0")}`;
  return !(lastGreeting?.date === today && lastGreeting.delivered);
}

function describeCalendar(calendar) {
  if (calendar.state !== "CONNECTED") return "Your calendar is not connected yet.";
  return `You have ${calendar.eventCount ?? 0} calendar events today.`;
}

test("arbitrary shell execution is blocked", () => {
  assert.equal(commandPolicies.ARBITRARY_SHELL.risk, "BLOCKED");
});

test("close app policy requires confirmation", () => {
  assert.equal(commandPolicies.CLOSE_APP.risk, "CONFIRM_ONCE");
});

test("morning greeting is once per configured day", () => {
  const input = {
    now: new Date("2026-07-17T08:15:00"),
    config: {
      morningWindowStart: "06:00",
      morningWindowEnd: "10:30"
    },
    lastGreeting: null
  };
  assert.equal(shouldDeliverMorningGreeting(input), true);
  assert.equal(
    shouldDeliverMorningGreeting({
      ...input,
      lastGreeting: { date: "2026-07-17", delivered: true }
    }),
    false
  );
});

test("disconnected integrations are reported honestly", () => {
  assert.equal(
    describeCalendar({ state: "DISCONNECTED" }),
    "Your calendar is not connected yet."
  );
});

test("secret redaction removes auth material", () => {
  assert.equal(
    redactSecrets("access_token=abc refresh_token=def client_secret=ghi code=jkl"),
    "access_token=[REDACTED] refresh_token=[REDACTED] client_secret=[REDACTED] code=[REDACTED]"
  );
});
