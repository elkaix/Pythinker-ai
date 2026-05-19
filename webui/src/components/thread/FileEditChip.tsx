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
 * ``done`` chips render a check, ``error`` an alert + tooltip. */
export function FileEditChip({ activity, active, onClick }: FileEditChipProps) {
  const isError = activity.phase === "error";
  const isDone = activity.phase === "end";
  const stats = formatStats(activity);
  const ariaLabel = isError
    ? `Edit failed for ${activity.path}`
    : isDone
      ? `Edited ${activity.path}${stats ? ` (${stats})` : ""}`
      : `Editing ${activity.path}`;

  return (
    <button
      type="button"
      onClick={() => onClick?.(activity)}
      aria-label={ariaLabel}
      title={activity.error ?? activity.path}
      data-testid="file-edit-chip"
      data-phase={activity.phase}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px]",
        "transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        isError
          ? "border-destructive/50 bg-destructive/10 text-destructive hover:bg-destructive/15"
          : "border-sky-400/30 bg-sky-500/10 text-sky-700 hover:bg-sky-500/15 dark:text-sky-300",
      )}
    >
      <FileReferenceChip
        path={activity.path}
        active={active && !isError && !isDone}
        textClassName="text-[11px]"
      />
      {isDone && stats ? (
        <span className="font-mono text-[10px] text-muted-foreground">{stats}</span>
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
  if (a.phase !== "end") return "";
  const added = a.added > 0 ? `+${a.added}` : "";
  const deleted = a.deleted > 0 ? `-${a.deleted}` : "";
  if (added && deleted) return `${added} ${deleted}`;
  return added || deleted;
}
