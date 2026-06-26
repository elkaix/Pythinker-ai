import { FilePenLine, FileX2, Plus, Minus } from "lucide-react";

import { cn } from "@/lib/utils";
import type { FileEditActivity } from "@/lib/types";

interface FileEditRowProps {
  activity: FileEditActivity;
  isStreaming?: boolean;
  onClick?: (activity: FileEditActivity) => void;
}

export function FileEditRow({ activity, isStreaming, onClick }: FileEditRowProps) {
  const isPending = activity.phase === "start";
  const isError = activity.phase === "error";
  const isDone = activity.phase === "end";

  const label = activity.path
    ? activity.path.split("/").pop() ?? activity.path
    : activity.tool;

  const addedStr = isDone && !activity.binary && activity.added > 0 ? `+${activity.added}` : null;
  const deletedStr = isDone && !activity.binary && activity.deleted > 0 ? `-${activity.deleted}` : null;

  return (
    <button
      type="button"
      className={cn(
        "group flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors",
        onClick ? "hover:bg-accent/50 cursor-pointer" : "cursor-default",
        isError && "text-destructive",
        isPending && isStreaming && "animate-pulse",
      )}
      onClick={onClick ? () => onClick(activity) : undefined}
      disabled={!onClick}
    >
      {isError ? (
        <FileX2 className="h-3.5 w-3.5 shrink-0 text-destructive" aria-hidden />
      ) : (
        <FilePenLine
          className={cn(
            "h-3.5 w-3.5 shrink-0",
            isDone ? "text-sky-500 dark:text-sky-400" : "text-muted-foreground",
          )}
          aria-hidden
        />
      )}
      <span className="min-w-0 flex-1 truncate font-mono">{label}</span>
      {(addedStr || deletedStr) && (
        <span className="flex shrink-0 items-center gap-1 font-mono text-[10px]">
          {addedStr && (
            <span className="flex items-center text-green-600 dark:text-green-400">
              <Plus className="h-2.5 w-2.5" />{activity.added}
            </span>
          )}
          {deletedStr && (
            <span className="flex items-center text-red-500 dark:text-red-400">
              <Minus className="h-2.5 w-2.5" />{activity.deleted}
            </span>
          )}
        </span>
      )}
      {isError && activity.error && (
        <span className="max-w-32 truncate text-[10px] text-destructive/70">{activity.error}</span>
      )}
    </button>
  );
}
