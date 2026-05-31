import { useMemo } from "react";

import { MessageBubble } from "@/components/MessageBubble";
import { AgentActivityCluster } from "@/components/thread/AgentActivityCluster";
import { normalizeActivityTimeline, type TurnUnit } from "@/lib/activity-timeline";
import type { FileEditActivity, UIMessage } from "@/lib/types";

interface ThreadMessagesProps {
  messages: UIMessage[];
  /** Re-run the last assistant turn from the trailing user message. */
  onRegenerate?: () => void;
  /** Rewrite a user bubble in place and resubmit from there. */
  onEdit?: (messageId: string, newContent: string) => void;
  /** Open the read-only side panel when a file chip is clicked. */
  onOpenFile?: (path: string) => void;
  /** Whether the agent is currently streaming (keeps activity clusters open). */
  isStreaming?: boolean;
}

export type DisplayUnit = TurnUnit;

export function buildDisplayUnits(messages: UIMessage[]): DisplayUnit[] {
  return normalizeActivityTimeline(messages);
}

export function ThreadMessages({
  messages,
  onRegenerate,
  onEdit,
  onOpenFile,
  isStreaming,
}: ThreadMessagesProps) {
  const units = useMemo(() => buildDisplayUnits(messages), [messages]);

  return (
    <div className="flex w-full flex-col gap-3">
      {units.map((unit, i) => (
        <div
          key={unitKey(unit, i)}
          data-message-id={unit.type === "message" ? unit.message.id : unit.messages[0]?.id}
          className="rounded-md"
        >
          {unit.type === "activity" ? (
            <AgentActivityCluster
              messages={unit.messages}
              isStreaming={isStreaming}
              onChipClick={(a: FileEditActivity) => onOpenFile?.(a.path)}
            />
          ) : (
            <MessageBubble
              message={unit.message}
              onRegenerate={onRegenerate}
              onEdit={onEdit}
            />
          )}
        </div>
      ))}
    </div>
  );
}

function unitKey(unit: DisplayUnit, index: number): string {
  if (unit.type === "activity") {
    return unit.messages[0]?.id ?? `activity-${index}`;
  }
  return unit.message.id;
}
