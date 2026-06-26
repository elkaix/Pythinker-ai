/**
 * Activity timeline helpers for Pythinker's message model.
 *
 * Pythinker's UIMessage model differs from the upstream source:
 *  - Reasoning is embedded in content as <think>...</think> tags
 *  - File edits arrive as a separate ``file_activity_cluster`` kind message
 *  - Tool traces arrive as ``trace`` kind messages
 *
 * This module normalizes those messages into ``TurnUnit[]`` for the
 * activity timeline display, using a Pythinker-specific adapter rather
 * than relying on upstream's ``reasoning``/``fileEdits`` fields.
 */

import { extractThinkBlocks } from "@/lib/extractThinkBlocks";
import type { FileEditActivity, UIMessage } from "@/lib/types";

export type ActivityItemType = "reasoning" | "tool" | "file_edit";
export type ActivityStepStatus = "pending" | "running" | "done" | "error";
export type ActivityStepSource = "reasoning" | "tool" | "shell" | "mcp" | "file";

export interface ActivityStepItem {
  id: string;
  label: string;
  detail?: string;
  status: ActivityStepStatus;
  source: ActivityStepSource;
  error?: string;
}

export interface ActivityGroup {
  id: string;
  title: string;
  source: ActivityStepSource;
  steps: ActivityStepItem[];
}

export interface ActivityItem {
  type: ActivityItemType;
  message: UIMessage;
}

export type TurnUnit =
  | { type: "activity"; messages: UIMessage[]; items: ActivityItem[]; turnLatencyMs?: number }
  | { type: "message"; message: UIMessage };

/** True when this assistant message has only <think> content (no visible answer). */
export function isReasoningOnlyAssistant(message: UIMessage): boolean {
  if (message.role !== "assistant" || message.kind === "trace") return false;
  if (message.isStreaming) return false;
  const { visible } = extractThinkBlocks(message.content);
  return visible.trim().length === 0 && message.content.includes("<think");
}

/** True when this message belongs in an activity cluster rather than a conversation turn. */
export function isAgentActivityMember(message: UIMessage): boolean {
  return (
    message.kind === "trace" ||
    message.kind === "file_activity_cluster" ||
    isReasoningOnlyAssistant(message)
  );
}

/** Normalise a flat message list into ``TurnUnit[]`` for the activity timeline. */
export function normalizeActivityTimeline(messages: UIMessage[]): TurnUnit[] {
  const units: TurnUnit[] = [];
  let activityMessages: UIMessage[] = [];

  const flushActivity = () => {
    if (activityMessages.length === 0) return;
    const items: ActivityItem[] = activityMessages.map((m) => ({
      type: activityTypeOf(m),
      message: m,
    }));
    units.push({ type: "activity", messages: activityMessages, items });
    activityMessages = [];
  };

  for (const message of messages) {
    if (isAgentActivityMember(message)) {
      activityMessages.push(message);
    } else {
      // Non-activity message: if it's an assistant turn preceded by activity, keep them together
      if (message.role === "assistant" && activityMessages.length > 0) {
        const items: ActivityItem[] = activityMessages.map((m) => ({
          type: activityTypeOf(m),
          message: m,
        }));
        units.push({ type: "activity", messages: activityMessages, items });
        activityMessages = [];
      } else {
        flushActivity();
      }
      units.push({ type: "message", message });
    }
  }

  flushActivity();
  return units;
}

function activityTypeOf(message: UIMessage): ActivityItemType {
  if (message.kind === "file_activity_cluster") return "file_edit";
  if (isReasoningOnlyAssistant(message)) return "reasoning";
  return "tool";
}

/** Build a display label for a trace message (first trace line, truncated). */
export function traceLabel(message: UIMessage): string {
  const line = message.traces?.[0] ?? message.content;
  if (line.length <= 80) return line;
  return line.slice(0, 79) + "…";
}

/** Summarise file-edit activities from a file_activity_cluster message. */
export function fileEditSummary(activities: FileEditActivity[]): {
  fileCount: number;
  added: number;
  deleted: number;
  errors: number;
} {
  let added = 0;
  let deleted = 0;
  let errors = 0;
  for (const a of activities) {
    if (a.phase === "end" && !a.binary) {
      added += a.added;
      deleted += a.deleted;
    }
    if (a.phase === "error") errors += 1;
  }
  return { fileCount: activities.length, added, deleted, errors };
}

/** Format +/- stats for display. */
export function formatDiffStats(added: number, deleted: number): string {
  const a = added > 0 ? `+${added}` : "";
  const d = deleted > 0 ? `-${deleted}` : "";
  if (a && d) return `${a} ${d}`;
  return a || d;
}
