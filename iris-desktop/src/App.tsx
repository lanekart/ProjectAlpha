import { useEffect, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { listen } from "@tauri-apps/api/event";
import { Mic, Moon, PanelRightClose, Settings, Volume2 } from "lucide-react";
import { CommandPanel } from "./components/CommandPanel";
import { Robot } from "./components/Robot";
import { SettingsPanel } from "./components/SettingsPanel";
import {
  defaultApplicationRegistry,
  routeApplicationCommand,
  type Platform
} from "./core/applicationRegistry";
import {
  buildMorningBriefing,
  localDateKey,
  shouldDeliverMorningGreeting,
  type GreetingRecord
} from "./core/morningGreeting";
import { policyForCommand } from "./core/securityPolicy";
import {
  transitionRobotState,
  type RobotEvent,
  type RobotState
} from "./state/robotState";

type CommandResult = {
  ok: boolean;
  message: string;
};

const platform: Platform =
  navigator.userAgent.toLowerCase().includes("windows") ? "windows" : "macos";

function parseApplicationCommand(text: string):
  | { intent: "open" | "close"; appId: string }
  | { intent: "blocked"; reason: string }
  | { intent: "unknown"; reason: string } {
  const normalized = text.trim().toLowerCase();
  if (!normalized) {
    return { intent: "unknown", reason: "Type a command first." };
  }

  if (
    normalized.includes("shell") ||
    normalized.includes("terminal command") ||
    normalized.startsWith("rm ") ||
    normalized.startsWith("del ")
  ) {
    return {
      intent: "blocked",
      reason: policyForCommand("ARBITRARY_SHELL").reason
    };
  }

  const openMatch = normalized.match(/^(open|launch|start)\s+(.+)$/);
  if (openMatch) {
    return { intent: "open", appId: openMatch[2] };
  }

  const closeMatch = normalized.match(/^(close|quit)\s+(.+)$/);
  if (closeMatch) {
    return { intent: "close", appId: closeMatch[2] };
  }

  return {
    intent: "unknown",
    reason: "Try opening or closing an approved application."
  };
}

export default function App() {
  const [robotState, setRobotState] = useState<RobotState>("STARTING");
  const [panelOpen, setPanelOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [transcription, setTranscription] = useState("");
  const [response, setResponse] = useState("Starting IRIS...");
  const [muted, setMuted] = useState(false);
  const [pendingClose, setPendingClose] = useState<string | null>(null);
  const [lastGreeting, setLastGreeting] = useState<GreetingRecord | null>(null);

  const registry = useMemo(() => defaultApplicationRegistry, []);

  function sendEvent(event: RobotEvent) {
    setRobotState((current) => transitionRobotState(current, event));
  }

  useEffect(() => {
    sendEvent("BOOTED");
    setResponse("Hi. IRIS is ready.");

    const unlistenPromise = listen("iris://restore", () => {
      setPanelOpen(false);
      sendEvent("RESTORE");
    });

    return () => {
      unlistenPromise.then((unlisten) => unlisten()).catch(() => undefined);
    };
  }, []);

  useEffect(() => {
    const input = {
      now: new Date(),
      config: {
        displayName: "Rishab",
        morningWindowStart: "06:00",
        morningWindowEnd: "10:30"
      },
      calendar: { state: "DISCONNECTED" as const },
      mail: { state: "DISCONNECTED" as const },
      lastGreeting
    };

    if (shouldDeliverMorningGreeting(input)) {
      const greeting = buildMorningBriefing(input);
      setResponse(greeting);
      setLastGreeting({
        date: localDateKey(new Date()),
        delivered: true
      });
      if (!muted) {
        invoke("speak_text", { text: greeting }).catch(() => undefined);
      }
    }
  }, [lastGreeting, muted]);

  async function executeCommand(text: string): Promise<CommandResult> {
    const parsed = parseApplicationCommand(text);
    if (parsed.intent === "blocked" || parsed.intent === "unknown") {
      return { ok: false, message: parsed.reason };
    }

    const route = routeApplicationCommand(
      {
        type: parsed.intent,
        appId: parsed.appId,
        confirmed: pendingClose === parsed.appId
      },
      registry,
      platform
    );

    if (route.status !== "APPROVED") {
      return { ok: false, message: route.reason };
    }

    if (route.requiresConfirmation) {
      setPendingClose(parsed.appId);
      return {
        ok: false,
        message: `Confirm closing ${route.app.label}. Unsaved work may exist.`
      };
    }

    if (parsed.intent === "open") {
      return invoke<CommandResult>("open_approved_application", {
        appId: route.app.id
      });
    }

    setPendingClose(null);
    return invoke<CommandResult>("request_close_application", {
      appId: route.app.id
    });
  }

  async function handleSubmit(text: string) {
    sendEvent("SUBMIT_COMMAND");
    setResponse("Thinking...");

    try {
      sendEvent("START_EXECUTION");
      const result = await executeCommand(text);
      setResponse(result.message);
      sendEvent(result.ok ? "EXECUTION_SUCCEEDED" : "EXECUTION_FAILED");
      if (!muted) {
        await invoke("speak_text", { text: result.message });
      }
    } catch (error) {
      setResponse(error instanceof Error ? error.message : "Command failed.");
      sendEvent("EXECUTION_FAILED");
    } finally {
      window.setTimeout(() => sendEvent("ACKNOWLEDGED"), 1800);
    }
  }

  async function hideRobot() {
    sendEvent("HIDE");
    setPanelOpen(false);
    await invoke("hide_robot_window");
  }

  async function startPushToTalk() {
    sendEvent("START_LISTENING");
    setResponse("Listening...");
    try {
      const result = await invoke<string>("start_push_to_talk");
      setTranscription(result);
      sendEvent("TRANSCRIPTION_READY");
    } catch {
      setResponse("Microphone permission is unavailable. Text commands still work.");
      sendEvent("EXECUTION_FAILED");
    }
  }

  return (
    <main className="iris-shell" data-state={robotState}>
      <section
        className="robot-stage"
        data-tauri-drag-region
        onDoubleClick={() => getCurrentWindow().startDragging()}
      >
        <Robot state={robotState} onClick={() => setPanelOpen((open) => !open)} />
        <div className="quick-actions">
          <button title="Push to talk" onClick={startPushToTalk}>
            <Mic size={17} />
          </button>
          <button
            title="Do Not Disturb"
            onClick={() =>
              sendEvent(
                robotState === "DO_NOT_DISTURB" ? "DISABLE_DND" : "ENABLE_DND"
              )
            }
          >
            <Moon size={17} />
          </button>
          <button title="Mute speech" onClick={() => setMuted((value) => !value)}>
            <Volume2 size={17} />
          </button>
          <button title="Settings" onClick={() => setSettingsOpen(true)}>
            <Settings size={17} />
          </button>
          <button title="Hide IRIS" onClick={hideRobot}>
            <PanelRightClose size={17} />
          </button>
        </div>
      </section>

      {panelOpen ? (
        <CommandPanel
          robotState={robotState}
          transcription={transcription}
          response={response}
          pendingClose={pendingClose}
          onTranscriptionChange={setTranscription}
          onSubmit={handleSubmit}
          onCancel={() => {
            setPendingClose(null);
            setResponse("Cancelled.");
            sendEvent("ACKNOWLEDGED");
          }}
        />
      ) : null}

      {settingsOpen ? (
        <SettingsPanel
          registry={registry}
          onClose={() => setSettingsOpen(false)}
        />
      ) : null}
    </main>
  );
}
