import assert from "node:assert/strict";
import test from "node:test";

const registry = [
  {
    id: "chrome",
    label: "Google Chrome",
    aliases: ["chrome", "google chrome"],
    platforms: ["macos", "windows"],
    safeToCloseWithoutConfirmation: false
  },
  {
    id: "calculator",
    label: "Calculator",
    aliases: ["calculator", "calc"],
    platforms: ["macos", "windows"],
    safeToCloseWithoutConfirmation: true
  },
  {
    id: "project-alpha",
    label: "Project Alpha",
    aliases: ["project alpha", "alpha"],
    platforms: ["macos", "windows"],
    safeToCloseWithoutConfirmation: false,
    configurablePath: ""
  }
];

function findApprovedApplication(query, platform) {
  const normalized = query.trim().toLowerCase();
  return (
    registry.find((app) => {
      return (
        app.platforms.includes(platform) &&
        (app.id === normalized ||
          app.label.toLowerCase() === normalized ||
          app.aliases.includes(normalized))
      );
    }) ?? null
  );
}

function routeApplicationCommand(command, platform) {
  const app = findApprovedApplication(command.appId, platform);
  if (!app) {
    return { status: "NOT_APPROVED" };
  }

  if (app.id === "project-alpha" && !app.configurablePath) {
    return { status: "NOT_FOUND" };
  }

  if (command.type === "close") {
    return {
      status: "APPROVED",
      requiresConfirmation:
        !app.safeToCloseWithoutConfirmation && !command.confirmed
    };
  }

  return { status: "APPROVED", requiresConfirmation: false };
}

test("matches approved applications by alias", () => {
  assert.equal(findApprovedApplication("google chrome", "macos")?.id, "chrome");
});

test("rejects unapproved applications", () => {
  assert.equal(
    routeApplicationCommand({ type: "open", appId: "unknown", confirmed: false }, "macos")
      .status,
    "NOT_APPROVED"
  );
});

test("opening approved apps is immediate", () => {
  assert.deepEqual(
    routeApplicationCommand({ type: "open", appId: "chrome", confirmed: false }, "macos"),
    { status: "APPROVED", requiresConfirmation: false }
  );
});

test("close requires confirmation unless configured safe", () => {
  assert.equal(
    routeApplicationCommand({ type: "close", appId: "chrome", confirmed: false }, "macos")
      .requiresConfirmation,
    true
  );
  assert.equal(
    routeApplicationCommand({ type: "close", appId: "calculator", confirmed: false }, "macos")
      .requiresConfirmation,
    false
  );
});

test("project alpha reports missing configurable target", () => {
  assert.equal(
    routeApplicationCommand(
      { type: "open", appId: "project-alpha", confirmed: false },
      "macos"
    ).status,
    "NOT_FOUND"
  );
});
