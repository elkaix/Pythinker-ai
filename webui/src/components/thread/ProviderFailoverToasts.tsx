import { useTranslation } from "react-i18next";
import { AlertTriangle, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { FailoverNotice } from "@/hooks/usePythinkerStream";
import { cn } from "@/lib/utils";

interface ProviderFailoverToastsProps {
  notices: FailoverNotice[];
  onDismiss: (id: string) => void;
  className?: string;
}

/** Render dismissible failover notices stacked above the composer. Each
 * notice persists until the user dismisses it; the parent hook handles
 * per-turn dedupe so repeats within the same turn never reach this list. */
export function ProviderFailoverToasts({ notices, onDismiss, className }: ProviderFailoverToastsProps) {
  const { t } = useTranslation();
  if (notices.length === 0) return null;
  return (
    <div
      className={cn("pointer-events-none flex flex-col gap-2 px-4 pb-2", className)}
      data-testid="provider-failover-toasts"
      role="status"
    >
      {notices.map((notice) => (
        <div
          key={notice.id}
          className={cn(
            "pointer-events-auto flex items-start gap-2 rounded-xl border border-amber-400/40",
            "bg-amber-500/10 px-3 py-2 text-sm text-amber-700 shadow-sm",
            "dark:text-amber-300",
          )}
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <div className="flex-1 min-w-0">
            <p>
              <span className="font-mono">{notice.primary}</span> failed
              {notice.reason ? <> with <span className="font-mono">{notice.reason}</span></> : null}
              {" — "}
              falling back to <span className="font-mono">{notice.fallback}</span>.
            </p>
          </div>
          <Button
            variant="ghost"
            size="icon"
            aria-label={t("common.dismiss")}
            className="-mr-1 -mt-1 h-6 w-6 text-amber-700 hover:bg-amber-500/15 dark:text-amber-300"
            onClick={() => onDismiss(notice.id)}
          >
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
      ))}
    </div>
  );
}
