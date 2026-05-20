import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useClient } from "@/providers/ClientProvider";
import type { WebUIFileReadResult } from "@/lib/pythinker-client";
import { cn } from "@/lib/utils";

interface FileReadPanelProps {
  path: string | null;
  onOpenChange: (open: boolean) => void;
}

type State =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; result: WebUIFileReadResult }
  | { kind: "error"; message: string };

/** Side-panel viewer for a workspace file referenced by a ``FileEditChip``.
 * Fetches via ``webui_file_read.get``; binary content shows a placeholder
 * and oversize text shows a "truncated" banner. */
export function FileReadPanel({ path, onOpenChange }: FileReadPanelProps) {
  const { t } = useTranslation();
  const { client } = useClient();
  const [state, setState] = useState<State>({ kind: "idle" });

  useEffect(() => {
    if (!path) {
      setState({ kind: "idle" });
      return;
    }
    setState({ kind: "loading" });
    let cancelled = false;
    (async () => client.getFileContent(path))()
      .then((result) => {
        if (cancelled) return;
        setState({ kind: "ready", result });
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setState({ kind: "error", message: err.message || t("thread.filePanel.readFailed") });
      });
    return () => {
      cancelled = true;
    };
  }, [client, path]);

  return (
    <Sheet open={path !== null} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="flex h-full w-full max-w-3xl flex-col gap-3 p-0 sm:max-w-3xl"
      >
        <SheetHeader className="border-b border-border px-4 py-3">
          <SheetTitle className="break-all font-mono text-sm">
            {path ?? ""}
          </SheetTitle>
        </SheetHeader>
        <div className="flex-1 overflow-auto px-4 pb-4">
          {state.kind === "loading" ? (
            <p className="py-12 text-center text-sm text-muted-foreground">{t("thread.filePanel.loading")}</p>
          ) : null}
          {state.kind === "error" ? (
            <p
              className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
              data-testid="file-read-error"
            >
              {state.message}
            </p>
          ) : null}
          {state.kind === "ready" ? (
            <ReadyView result={state.result} />
          ) : null}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function ReadyView({ result }: { result: WebUIFileReadResult }) {
  const { t } = useTranslation();
  if (result.binary) {
    return (
      <p
        className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground"
        data-testid="file-read-binary"
      >
        {t("thread.filePanel.binary", { size: formatBytes(result.size) })}
      </p>
    );
  }
  return (
    <>
      {result.truncated ? (
        <p
          className="mb-2 rounded-md border border-amber-400/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300"
          data-testid="file-read-truncated"
        >
          {t("thread.filePanel.truncated")}
        </p>
      ) : null}
      <pre
        className={cn(
          "whitespace-pre-wrap break-all rounded-md border border-border bg-muted/40 p-3",
          "font-mono text-[12px] leading-relaxed text-foreground",
        )}
        data-testid="file-read-content"
      >
        {result.content}
      </pre>
    </>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MiB`;
}
