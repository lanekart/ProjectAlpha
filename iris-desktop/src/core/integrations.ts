export const providerStates = [
  "CONNECTED",
  "DISCONNECTED",
  "AUTH_EXPIRED",
  "PERMISSION_DENIED",
  "TEMPORARILY_UNAVAILABLE"
] as const;

export type ProviderState = (typeof providerStates)[number];

export type CalendarBriefing = {
  state: ProviderState;
  eventCount?: number;
  firstEventTitle?: string;
  firstEventStartTime?: string;
};

export type MailBriefing = {
  state: ProviderState;
  unreadCount?: number;
  importantUnreadCount?: number;
};

export function describeCalendar(calendar: CalendarBriefing): string {
  if (calendar.state !== "CONNECTED") {
    return "Your calendar is not connected yet.";
  }

  const count = calendar.eventCount ?? 0;
  if (count === 0) {
    return "You have no calendar events today.";
  }

  const first = calendar.firstEventTitle && calendar.firstEventStartTime
    ? ` Your first event is ${calendar.firstEventTitle} at ${calendar.firstEventStartTime}.`
    : "";
  return `You have ${count} calendar event${count === 1 ? "" : "s"} today.${first}`;
}

export function describeMail(mail: MailBriefing): string {
  if (mail.state !== "CONNECTED") {
    return "Gmail is not connected yet.";
  }

  const unread = mail.unreadCount ?? 0;
  const important = mail.importantUnreadCount ?? 0;
  return `Gmail is connected and you have ${unread} unread message${unread === 1 ? "" : "s"}, including ${important} important.`;
}
