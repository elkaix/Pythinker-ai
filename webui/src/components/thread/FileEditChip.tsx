import { AlertCircle, CheckCircle2 } from "lucide-react";

import { FileReferenceChip } from "@/components/FileReferenceChip";
import type { FileEditActivity } from "@/lib/types";
import { cn } from "@/lib/utils";

interface FileEditChipProps {
  activity: FileEditActivity;
  active: boolean;
  onClick?: (activity: FileEditActivity) => void;
}

/** Wrap ``FileReferenceChip`` with phase visuals. ``active`` (no reduced
 * motion + cluster still streaming) drives the chip's sheen animation;
 * ``done`` chips render a check, ``error`` an alert + tooltip.
 *
 * When a streaming chip has not resolved its ``path`` yet (the pending
 * state from ``StreamingFileEditTracker`` — common for the OpenAI Responses
 * API which only ships the path at ``output_item.done`` time), render a
 * "writing…" placeholder so the user sees something concrete instead of a
 * bare file icon. */
export function FileEditChip({ activity, active, onClick }: FileEditChipProps) {
  const isError = activity.phase === "error";
  const isDone = activity.phase === "end";
  const hasPath = Boolean(activity.path);
  const stats = formatStats(activity);
  const pendingLabel = activity.tool === "edit_file" ? "editing…" : "writing…";
  const ariaLabel = isError
    ? `Edit failed for ${activity.path}`
    : isDone
      ? `Edited ${activity.path}${stats ? ` (${stats})` : ""}`
      : hasPath
        ? `Editing ${activity.path}`
        : "Editing file…";

  return (
    <button
      type="button"
      onClick={() => {
        // Pending chips have no usable path yet — clicking would open an
        // empty read panel and fire a 404. Wait for the path to resolve.
        if (!hasPath) return;
        onClick?.(activity);
      }}
      disabled={!hasPath}
      aria-label={ariaLabel}
      title={activity.error ?? activity.path ?? "Editing file…"}
      data-testid="file-edit-chip"
      data-phase={activity.phase}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px]",
        "transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        !hasPath ? "cursor-default" : null,
        isError
          ? "border-destructive/50 bg-destructive/10 text-destructive hover:bg-destructive/15"
          : "border-sky-400/30 bg-sky-500/10 text-sky-700 hover:bg-sky-500/15 dark:text-sky-300",
      )}
    >
      {hasPath ? (
        <FileReferenceChip
          path={activity.path}
          active={active && !isError && !isDone}
          textClassName="text-[11px]"
        />
      ) : (
        <span className="italic text-[11px] opacity-80">{pendingLabel}</span>
      )}
      {stats ? (
        <span
          className={cn(
            "font-mono text-[10px] text-muted-foreground",
            activity.approximate && !isDone ? "italic opacity-80" : null,
          )}
        >
          {stats}
        </span>
      ) : null}
      {activity.binary && isDone ? (
        <span className="rounded bg-muted px-1 text-[9px] uppercase tracking-wider text-muted-foreground">
          binary
        </span>
      ) : null}
      {isDone ? <CheckCircle2 className="h-3 w-3" aria-hidden /> : null}
      {isError ? <AlertCircle className="h-3 w-3" aria-hidden /> : null}
    </button>
  );
}

function formatStats(a: FileEditActivity): string {
  if (a.binary) return "";
  // Streaming "approximate" counts ride along with the live chip so the user
  // sees the file growing under their cursor; the leading "~" cues the value
  // is mid-stream and may revise upward by the time the tool completes.
  const isLiveApproximate = a.phase !== "end" && a.approximate && (a.added > 0 || a.deleted > 0);
  if (a.phase !== "end" && !isLiveApproximate) return "";
  const added = a.added > 0 ? `+${a.added}` : "";
  const deleted = a.deleted > 0 ? `-${a.deleted}` : "";
  const raw = added && deleted ? `${added} ${deleted}` : added || deleted;
  if (!raw) return "";
  return isLiveApproximate ? `~${raw}` : raw;
}
