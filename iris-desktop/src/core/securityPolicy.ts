export const riskLevels = [
  "IMMEDIATE",
  "CONFIRM_ONCE",
  "ALWAYS_CONFIRM",
  "BLOCKED"
] as const;

export type RiskLevel = (typeof riskLevels)[number];

export type CommandKind =
  | "OPEN_APPROVED_APP"
  | "READ_CALENDAR_COUNT"
  | "READ_UNREAD_MAIL_COUNT"
  | "CLOSE_APP"
  | "FORCE_CLOSE_APP"
  | "SHUTDOWN_COMPUTER"
  | "DELETE_FILES"
  | "ARBITRARY_SHELL"
  | "SEND_EMAIL"
  | "EXECUTE_FINANCIAL_TRADE";

export type CommandPolicy = {
  risk: RiskLevel;
  reason: string;
};

export const commandPolicies: Record<CommandKind, CommandPolicy> = {
  OPEN_APPROVED_APP: {
    risk: "IMMEDIATE",
    reason: "Approved applications can be opened directly."
  },
  READ_CALENDAR_COUNT: {
    risk: "IMMEDIATE",
    reason: "Only aggregate calendar counts are read."
  },
  READ_UNREAD_MAIL_COUNT: {
    risk: "IMMEDIATE",
    reason: "Only aggregate unread mail counts are read."
  },
  CLOSE_APP: {
    risk: "CONFIRM_ONCE",
    reason: "Closing an app may discard unsaved work."
  },
  FORCE_CLOSE_APP: {
    risk: "ALWAYS_CONFIRM",
    reason: "Force-closing can discard unsaved work immediately."
  },
  SHUTDOWN_COMPUTER: {
    risk: "ALWAYS_CONFIRM",
    reason: "Shutting down affects the whole device."
  },
  DELETE_FILES: {
    risk: "BLOCKED",
    reason: "File deletion is outside this milestone."
  },
  ARBITRARY_SHELL: {
    risk: "BLOCKED",
    reason: "IRIS never passes raw user text to a shell."
  },
  SEND_EMAIL: {
    risk: "BLOCKED",
    reason: "Sending email is not enabled in this milestone."
  },
  EXECUTE_FINANCIAL_TRADE: {
    risk: "BLOCKED",
    reason: "Financial trade execution is blocked from the desktop companion."
  }
};

export function policyForCommand(kind: CommandKind): CommandPolicy {
  return commandPolicies[kind];
}
