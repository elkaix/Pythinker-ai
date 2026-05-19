import { ChevronDown, ChevronRight, Pencil } from "lucide-react";
import { useState } from "react";

import { FileEditChip } from "@/components/thread/FileEditChip";
import { Button } from "@/components/ui/button";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import type { FileEditActivity } from "@/lib/types";
import { cn } from "@/lib/utils";

interface AgentActivityClusterProps {
  activities: FileEditActivity[];
  isStreaming: boolean;
  onChipClick?: (activity: FileEditActivity) => void;
}

/** Render the per-turn file-edit cluster as a single collapsed summary row.
 * Expanding reveals the underlying ``FileEditChip``s; while ``isStreaming``
 * is true the active chips pulse via ``FileReferenceChip``'s sheen anim
 * (gated by ``useReducedMotion``). */
export function AgentActivityCluster({
  activities,
  isStreaming,
  onChipClick,
}: AgentActivityClusterProps) {
  const [open, setOpen] = useState(false);
  const reducedMotion = useReducedMotion();
  if (activities.length === 0) return null;

  const totals = activities.reduce(
    (acc, a) => {
      if (a.phase === "end" && !a.binary) {
        acc.added += a.added;
        acc.deleted += a.deleted;
      }
      if (a.phase === "error") acc.errors += 1;
      return acc;
    },
    { added: 0, deleted: 0, errors: 0 },
  );
  const fileCount = activities.length;
  const stats = formatTotals(totals.added, totals.deleted);

  return (
    <section
      className={cn(
        "mx-2 my-1 rounded-xl border border-border/60 bg-card/40 px-3 py-2 text-xs",
      )}
      data-testid="agent-activity-cluster"
      aria-label={isStreaming ? "Editing files" : "Files edited this turn"}
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
        <span className="text-muted-foreground">
          {isStreaming
            ? `Editing ${fileCount} file${fileCount === 1 ? "" : "s"}${stats ? ` (${stats})` : ""}…`
            : `${fileCount} file${fileCount === 1 ? "" : "s"} edited${stats ? ` (${stats})` : ""}${totals.errors > 0 ? `, ${totals.errors} error${totals.errors === 1 ? "" : "s"}` : ""}`}
        </span>
      </Button>
      {open ? (
        <div className="mt-2 flex flex-wrap gap-1.5 pl-5">
          {activities.map((a) => (
            <FileEditChip
              key={a.call_id}
              activity={a}
              active={isStreaming && !reducedMotion && a.phase === "start"}
              onClick={onChipClick}
            />
          ))}
        </div>
      ) : null}
    </section>
  );
}

function formatTotals(added: number, deleted: number): string {
  const a = added > 0 ? `+${added}` : "";
  const d = deleted > 0 ? `-${deleted}` : "";
  if (a && d) return `${a} ${d}`;
  return a || d;
}
