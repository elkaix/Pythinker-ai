import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
import { useClient } from "@/providers/ClientProvider";
import type { ConnectionStatus } from "@/lib/types";

const COPY: Record<ConnectionStatus, { color: string }> = {
  idle: { color: "bg-card/40 text-muted-foreground" },
  connecting: {
    color: "bg-amber-500/10 text-amber-700 dark:text-amber-300",
  },
  open: {
    color: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
  },
  reconnecting: {
    color: "bg-amber-500/10 text-amber-700 dark:text-amber-300",
  },
  closed: {
    color: "bg-card/40 text-muted-foreground",
  },
  error: {
    color: "bg-destructive/10 text-destructive",
  },
};

export function ConnectionBadge() {
  const { t } = useTranslation();
  const { client } = useClient();
  const [status, setStatus] = useState<ConnectionStatus>(client.status);

  useEffect(() => client.onStatus(setStatus), [client]);

  const meta = COPY[status];
  const pulsing =
    status === "connecting" ||
    status === "reconnecting" ||
    status === "error";
  const label = t(`connection.${status}`);
  return (
    <span
      className={cn(
        "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition-colors",
        "text-muted-foreground/70 hover:bg-sidebar-accent/65",
        meta.color,
      )}
      aria-live="polite"
      role="status"
      title={label}
    >
      <span className="relative flex h-2 w-2" aria-hidden>
        {pulsing && (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-75" />
        )}
        <span className="relative inline-flex h-2 w-2 rounded-full bg-current" />
      </span>
      <span className="sr-only">{label}</span>
    </span>
  );
}
