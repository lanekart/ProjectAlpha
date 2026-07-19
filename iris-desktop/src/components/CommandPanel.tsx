import { Loader2, Send, Square } from "lucide-react";
import type { RobotState } from "../state/robotState";

type CommandPanelProps = {
  robotState: RobotState;
  transcription: string;
  response: string;
  pendingClose: string | null;
  onTranscriptionChange: (value: string) => void;
  onSubmit: (value: string) => void;
  onCancel: () => void;
};

export function CommandPanel({
  robotState,
  transcription,
  response,
  pendingClose,
  onTranscriptionChange,
  onSubmit,
  onCancel
}: CommandPanelProps) {
  const busy = ["LISTENING", "TRANSCRIBING", "THINKING", "EXECUTING"].includes(
    robotState
  );

  return (
    <aside className="command-panel">
      <div className="panel-header">
        <span>{busy ? "Working" : "Ready"}</span>
        {busy ? <Loader2 size={16} className="spin" /> : null}
      </div>
      <textarea
        value={transcription}
        onChange={(event) => onTranscriptionChange(event.target.value)}
        placeholder="Open Spotify"
        aria-label="Command"
      />
      {pendingClose ? (
        <div className="confirmation">
          <strong>Close {pendingClose}?</strong>
          <span>Unsaved work may exist.</span>
          <div>
            <button onClick={() => onSubmit(`close ${pendingClose}`)}>Confirm</button>
            <button onClick={onCancel}>Cancel</button>
          </div>
        </div>
      ) : null}
      <div className="panel-actions">
        <button onClick={() => onSubmit(transcription)}>
          <Send size={16} />
          Send
        </button>
        <button onClick={onCancel}>
          <Square size={15} />
          Cancel
        </button>
      </div>
      <p className="response">{response}</p>
    </aside>
  );
}
