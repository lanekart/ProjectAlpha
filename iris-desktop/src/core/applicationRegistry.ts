import { policyForCommand, type CommandPolicy } from "./securityPolicy";

export type Platform = "macos" | "windows";

export type ApplicationDefinition = {
  id: string;
  label: string;
  aliases: string[];
  platforms: Platform[];
  macBundleName?: string;
  windowsAppId?: string;
  executableName?: string;
  safeToCloseWithoutConfirmation: boolean;
  configurablePath?: string;
};

export type ApplicationCommand =
  | { type: "open"; appId: string }
  | { type: "focus"; appId: string }
  | { type: "close"; appId: string; confirmed: boolean }
  | { type: "forceClose"; appId: string; confirmed: boolean };

export type ApplicationRoute =
  | {
      status: "APPROVED";
      app: ApplicationDefinition;
      policy: CommandPolicy;
      requiresConfirmation: boolean;
    }
  | { status: "NOT_APPROVED"; reason: string }
  | { status: "NOT_FOUND"; reason: string };

export const defaultApplicationRegistry: ApplicationDefinition[] = [
  {
    id: "chrome",
    label: "Google Chrome",
    aliases: ["chrome", "google chrome"],
    platforms: ["macos", "windows"],
    macBundleName: "Google Chrome",
    windowsAppId: "Chrome",
    executableName: "chrome.exe",
    safeToCloseWithoutConfirmation: false
  },
  {
    id: "safari",
    label: "Safari",
    aliases: ["safari"],
    platforms: ["macos"],
    macBundleName: "Safari",
    safeToCloseWithoutConfirmation: false
  },
  {
    id: "edge",
    label: "Microsoft Edge",
    aliases: ["edge", "microsoft edge"],
    platforms: ["macos", "windows"],
    macBundleName: "Microsoft Edge",
    windowsAppId: "MSEdge",
    executableName: "msedge.exe",
    safeToCloseWithoutConfirmation: false
  },
  {
    id: "spotify",
    label: "Spotify",
    aliases: ["spotify"],
    platforms: ["macos", "windows"],
    macBundleName: "Spotify",
    windowsAppId: "Spotify",
    executableName: "Spotify.exe",
    safeToCloseWithoutConfirmation: false
  },
  {
    id: "calculator",
    label: "Calculator",
    aliases: ["calculator", "calc"],
    platforms: ["macos", "windows"],
    macBundleName: "Calculator",
    windowsAppId: "calculator:",
    executableName: "calc.exe",
    safeToCloseWithoutConfirmation: true
  },
  {
    id: "notes",
    label: "Notes",
    aliases: ["notes", "apple notes"],
    platforms: ["macos"],
    macBundleName: "Notes",
    safeToCloseWithoutConfirmation: false
  },
  {
    id: "terminal",
    label: "Terminal",
    aliases: ["terminal", "windows terminal"],
    platforms: ["macos", "windows"],
    macBundleName: "Terminal",
    windowsAppId: "Microsoft.WindowsTerminal_8wekyb3d8bbwe!App",
    executableName: "wt.exe",
    safeToCloseWithoutConfirmation: false
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

export function findApprovedApplication(
  registry: ApplicationDefinition[],
  query: string,
  platform: Platform
): ApplicationDefinition | null {
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

export function routeApplicationCommand(
  command: ApplicationCommand,
  registry: ApplicationDefinition[],
  platform: Platform
): ApplicationRoute {
  const app = findApprovedApplication(registry, command.appId, platform);
  if (!app) {
    return {
      status: "NOT_APPROVED",
      reason: `${command.appId} is not in the approved application registry.`
    };
  }

  if (app.id === "project-alpha" && !app.configurablePath) {
    return {
      status: "NOT_FOUND",
      reason: "Project Alpha needs a configured launch target first."
    };
  }

  if (command.type === "close") {
    const policy = policyForCommand("CLOSE_APP");
    return {
      status: "APPROVED",
      app,
      policy,
      requiresConfirmation:
        !app.safeToCloseWithoutConfirmation && !command.confirmed
    };
  }

  if (command.type === "forceClose") {
    const policy = policyForCommand("FORCE_CLOSE_APP");
    return {
      status: "APPROVED",
      app,
      policy,
      requiresConfirmation: !command.confirmed
    };
  }

  return {
    status: "APPROVED",
    app,
    policy: policyForCommand("OPEN_APPROVED_APP"),
    requiresConfirmation: false
  };
}
