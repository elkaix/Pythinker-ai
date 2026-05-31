import { useState } from "react";
import { ChevronDown, ChevronRight, Pencil } from "lucide-react";

import { FileEditRow } from "@/components/thread/activity/FileEditRow";
import { ReasoningRow } from "@/components/thread/activity/ReasoningRow";
import { Button } from "@/components/ui/button";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { formatDiffStats, fileEditSummary } from "@/lib/activity-timeline";
import type { FileEditActivity, UIMessage } from "@/lib/types";
import { cn } from "@/lib/utils";

interface AgentActivityClusterProps {
  /** Messages in this activity cluster (trace, file_activity_cluster, reasoning-only). */
  messages: UIMessage[];
  /** True while the agent is still producing output in this turn. */
  isStreaming?: boolean;
  onChipClick?: (activity: FileEditActivity) => void;
}

/** Collect all FileEditActivity items from file_activity_cluster messages in the cluster. */
function collectFileActivities(messages: UIMessage[]): FileEditActivity[] {
  const activities: FileEditActivity[] = [];
  for (const m of messages) {
    if (m.kind === "file_activity_cluster" && m.activities) {
      activities.push(...m.activities);
    }
  }
  return activities;
}

/** Collect all trace content lines from trace messages. */
function collectTraceLines(messages: UIMessage[]): string[] {
  const lines: string[] = [];
  for (const m of messages) {
    if (m.kind === "trace") {
      lines.push(...(m.traces ?? [m.content]));
    }
  }
  return lines;
}

/** Collect reasoning content (think blocks) from the cluster messages. */
function collectReasoning(messages: UIMessage[]): string {
  const parts: string[] = [];
  for (const m of messages) {
    if (m.role === "assistant" && m.kind !== "trace") {
      const content = m.content;
      const thinkMatch = /<think>([\s\S]*?)<\/think>/g;
      let match;
      while ((match = thinkMatch.exec(content)) !== null) {
        const text = match[1].trim();
        if (text) parts.push(text);
      }
    }
  }
  return parts.join("\n\n");
}

export function AgentActivityCluster({
  messages,
  isStreaming,
  onChipClick,
}: AgentActivityClusterProps) {
  const [open, setOpen] = useState(false);
  const reducedMotion = useReducedMotion();

  const activities = collectFileActivities(messages);
  const traceLines = collectTraceLines(messages);
  const reasoningContent = collectReasoning(messages);

  const visibleActivities = activities.filter(
    (a) => a.path || (isStreaming && a.phase === "start"),
  );

  if (visibleActivities.length === 0 && traceLines.length === 0 && !reasoningContent) {
    return null;
  }

  const { added, deleted, errors } = fileEditSummary(visibleActivities);
  const stats = formatDiffStats(added, deleted);
  const fileCount = visibleActivities.length;
  const hasContent = visibleActivities.length > 0 || traceLines.length > 0 || !!reasoningContent;

  const summaryLabel = fileCount > 0
    ? isStreaming
      ? `Editing ${fileCount} file${fileCount === 1 ? "" : "s"}${stats ? ` (${stats})` : ""}…`
      : `${fileCount} file${fileCount === 1 ? "" : "s"} edited${stats ? ` (${stats})` : ""}${errors > 0 ? `, ${errors} error${errors === 1 ? "" : "s"}` : ""}`
    : traceLines.length > 0
    ? traceLines[0]?.slice(0, 60) + (traceLines[0]?.length > 60 ? "…" : "")
    : "Reasoning…";

  return (
    <section
      className={cn(
        "mx-2 my-1 rounded-xl border border-border/60 bg-card/40 px-3 py-2 text-xs",
      )}
      data-testid="agent-activity-cluster"
      aria-label={isStreaming ? "Agent activity in progress" : "Agent activity this turn"}
    >
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={() => setOpen((v) => !v)}
        className="h-7 w-full justify-start gap-2 px-1 text-xs hover:bg-accent/30"
      >
        {open ? (
          <ChevronDown className="h-3 w-3" aria-hidden />
        ) : (
          <ChevronRight className="h-3 w-3" aria-hidden />
        )}
        <Pencil className="h-3 w-3 text-sky-500 dark:text-sky-300" aria-hidden />
        <span className="truncate text-muted-foreground">{summaryLabel}</span>
      </Button>

      {open && hasContent && (
        <div className="mt-2 space-y-2 pl-1">
          {reasoningContent && (
            <ReasoningRow content={`<think>${reasoningContent}</think>`} defaultOpen={false} />
          )}
          {traceLines.length > 0 && (
            <div className="space-y-0.5">
              {traceLines.map((line, i) => (
                <div
                  key={i}
                  className="rounded px-2 py-1 font-mono text-[11px] text-muted-foreground bg-muted/30 truncate"
                >
                  {line}
                </div>
              ))}
            </div>
          )}
          {visibleActivities.length > 0 && (
            <div className="space-y-0.5">
              {visibleActivities.map((a) => (
                <FileEditRow
                  key={a.call_id}
                  activity={a}
                  isStreaming={isStreaming && !reducedMotion && a.phase === "start"}
                  onClick={onChipClick}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
