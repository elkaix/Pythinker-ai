import { useState } from "react";
import { Brain, ChevronDown, ChevronRight } from "lucide-react";

import { extractThinkBlocks } from "@/lib/extractThinkBlocks";

interface ReasoningRowProps {
  content: string;
  defaultOpen?: boolean;
}

export function ReasoningRow({ content, defaultOpen = false }: ReasoningRowProps) {
  const [open, setOpen] = useState(defaultOpen);
  const { reasoning } = extractThinkBlocks(content);
  if (!reasoning) return null;

  return (
    <div className="rounded-md border border-border/50 bg-muted/20 text-xs">
      <button
        type="button"
        className="flex w-full items-center gap-2 px-3 py-2 text-muted-foreground hover:text-foreground"
        onClick={() => setOpen((v) => !v)}
      >
        {open ? (
          <ChevronDown className="h-3 w-3 shrink-0" aria-hidden />
        ) : (
          <ChevronRight className="h-3 w-3 shrink-0" aria-hidden />
        )}
        <Brain className="h-3 w-3 shrink-0 text-violet-500" aria-hidden />
        <span className="font-medium">Reasoning</span>
        {!open && (
          <span className="ml-auto max-w-48 truncate text-[10px] opacity-70">{reasoning}</span>
        )}
      </button>
      {open && (
        <div className="border-t border-border/30 px-3 py-2 font-mono text-[11px] text-muted-foreground whitespace-pre-wrap leading-relaxed max-h-48 overflow-y-auto">
          {reasoning}
        </div>
      )}
    </div>
  );
}
