import {
  describeCalendar,
  describeMail,
  type CalendarBriefing,
  type MailBriefing
} from "./integrations";

export type MorningGreetingConfig = {
  displayName: string;
  morningWindowStart: string;
  morningWindowEnd: string;
};

export type GreetingRecord = {
  date: string;
  delivered: boolean;
};

export type MorningBriefingInput = {
  now: Date;
  config: MorningGreetingConfig;
  calendar: CalendarBriefing;
  mail: MailBriefing;
  lastGreeting: GreetingRecord | null;
};

export function localDateKey(now: Date): string {
  const year = now.getFullYear();
  const month = `${now.getMonth() + 1}`.padStart(2, "0");
  const day = `${now.getDate()}`.padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function minutesFromClock(value: string): number {
  const [hours, minutes] = value.split(":").map(Number);
  return hours * 60 + minutes;
}

export function isWithinMorningWindow(
  now: Date,
  config: MorningGreetingConfig
): boolean {
  const current = now.getHours() * 60 + now.getMinutes();
  return (
    current >= minutesFromClock(config.morningWindowStart) &&
    current <= minutesFromClock(config.morningWindowEnd)
  );
}

export function shouldDeliverMorningGreeting(
  input: MorningBriefingInput
): boolean {
  if (!isWithinMorningWindow(input.now, input.config)) {
    return false;
  }

  const today = localDateKey(input.now);
  return !(input.lastGreeting?.date === today && input.lastGreeting.delivered);
}

export function buildMorningBriefing(input: MorningBriefingInput): string {
  const dateText = new Intl.DateTimeFormat(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric"
  }).format(input.now);

  return [
    `Good morning, ${input.config.displayName}.`,
    `Today is ${dateText}.`,
    describeCalendar(input.calendar),
    describeMail(input.mail)
  ].join(" ");
}
