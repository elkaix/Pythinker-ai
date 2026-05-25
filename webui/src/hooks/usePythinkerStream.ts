import { useCallback, useEffect, useRef, useState } from "react";

import { useClient } from "@/providers/ClientProvider";
import { extractThinkBlocks } from "@/lib/extractThinkBlocks";
import type { StreamError } from "@/lib/pythinker-client";
import type {
  FileEditActivity,
  InboundEvent,
  OutboundMedia,
  UIImage,
  UIMessage,
} from "@/lib/types";

interface StreamBuffer {
  /** ID of the assistant message currently receiving deltas. */
  messageId: string;
  /** Sequence of deltas accumulated in order. */
  parts: string[];
}

interface LatencyTracker {
  /** ID of the placeholder bubble being timed. */
  messageId: string;
  /** Timestamp captured at send() / regenerate() / editMessage(). */
  startedAt: number;
  /** ID returned by ``setInterval`` so cleanup can clear it. */
  intervalId: ReturnType<typeof setInterval>;
}

/**
 * Subscribe to a chat by ID. Returns the in-memory message list for the chat,
 * a streaming flag, and a ``send`` function. Initial history must be seeded
 * separately (e.g. via ``fetchSessionMessages``) since the server only replays
 * live events.
 */
/** Payload passed to ``send`` when the user attaches one or more images.
 *
 * ``media`` is handed to the wire client verbatim; ``preview`` powers the
 * optimistic user bubble (blob URLs so the preview appears before the server
 * acks the frame). Keeping the two separate lets the bubble re-use the local
 * blob URL even after the server persists the file under a different name. */
export interface SendImage {
  media: OutboundMedia;
  preview: UIImage;
}

/** One-shot failover-toast row: the agent silently swapped the primary model
 * for a fallback. ``key`` dedupes within a turn (same ``primary -> fallback``
 * pair only surfaces once). */
export interface FailoverNotice {
  id: string;
  primary: string;
  fallback: string;
  reason: string;
  receivedAt: number;
}

/** Turn-scoped dedupe window: a primary->fallback pair only generates one
 * toast per turn, but a fresh turn re-enables the same pair if it failovers
 * again. The hook clears the set on user ``send`` / ``regenerate`` /
 * ``editMessage``. */
const FAILOVER_DEDUPE_WINDOW_MS = 60_000;

export function usePythinkerStream(
  chatId: string | null,
  initialMessages: UIMessage[] = [],
): {
  messages: UIMessage[];
  isStreaming: boolean;
  send: (content: string, images?: SendImage[]) => void;
  /** Cancel the in-flight turn for ``chatId`` and drop the typing placeholder. */
  stop: () => void;
  /** Drop the trailing assistant turn and ask the agent to produce a new one. */
  regenerate: () => void;
  /** Rewrite the user bubble with id ``messageId`` and resubmit from there. */
  editMessage: (messageId: string, newContent: string) => void;
  setMessages: React.Dispatch<React.SetStateAction<UIMessage[]>>;
  /** Latest transport-level fault raised since the last ``dismissStreamError``.
   * ``null`` when there is nothing to show. */
  streamError: StreamError | null;
  /** Clear the current ``streamError`` (e.g. after the user dismisses the
   * notification or starts a fresh action). */
  dismissStreamError: () => void;
  /** Open ``provider_failover`` notices for the current chat, deduped per
   * turn so a single failover yields exactly one visible toast. */
  failoverNotices: FailoverNotice[];
  /** Drop a notice once the user dismisses it. */
  dismissFailoverNotice: (id: string) => void;
} {
  const { client } = useClient();
  const [messages, setMessages] = useState<UIMessage[]>(initialMessages);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamError, setStreamError] = useState<StreamError | null>(null);
  const [failoverNotices, setFailoverNotices] = useState<FailoverNotice[]>([]);
  /** Per-turn dedupe of ``primary->fallback`` keys: cleared whenever the
   * user starts a new turn (send/regenerate/edit). Within the same turn,
   * repeated failover events from the same swap collapse to one toast. */
  const failoverSeen = useRef<Map<string, number>>(new Map());
  /** Per-turn file-edit cluster. ``messageId`` points at the cluster row in
   * ``messages``; ``activities`` is the latest phase per ``call_id`` (so a
   * late ``start`` after ``end`` / ``error`` is ignored). Cleared on each
   * fresh turn so a new cluster appears for the next assistant bubble. */
  const cluster = useRef<{
    messageId: string;
    activities: Map<string, FileEditActivity>;
  } | null>(null);
  const buffer = useRef<StreamBuffer | null>(null);
  const latency = useRef<LatencyTracker | null>(null);
  // rAF coalescer: bursty WS frames (5-10 small deltas in the same frame) used
  // to trigger that many re-renders. We append to ``buffer.current.parts``
  // synchronously and schedule a single flush per animation frame, so the
  // displayed text grows smoothly at the device's native frame rate even when
  // the wire delivers chunks unevenly.
  const flushHandle = useRef<number | null>(null);

  const cancelFlush = useCallback(() => {
    if (flushHandle.current !== null) {
      cancelAnimationFrame(flushHandle.current);
      flushHandle.current = null;
    }
  }, []);

  const scheduleFlush = useCallback(() => {
    if (flushHandle.current !== null) return;
    flushHandle.current = requestAnimationFrame(() => {
      flushHandle.current = null;
      const buf = buffer.current;
      if (!buf) return;
      const combined = buf.parts.join("");
      const targetId = buf.messageId;
      setMessages((prev) =>
        prev.map((m) => {
          if (m.id !== targetId) return m;
          if (m.latencyMs === undefined) return { ...m, content: combined };
          const { latencyMs: _drop, ...rest } = m;
          void _drop;
          return { ...rest, content: combined };
        }),
      );
    });
  }, []);

  const startLatency = useCallback((placeholderId: string) => {
    if (latency.current) {
      clearInterval(latency.current.intervalId);
    }
    const startedAt = Date.now();
    const intervalId = setInterval(() => {
      const elapsed = Date.now() - startedAt;
      setMessages((prev) =>
        prev.map((m) =>
          m.id === placeholderId && m.isStreaming
            ? { ...m, latencyMs: elapsed }
            : m,
        ),
      );
    }, 1_000);
    latency.current = { messageId: placeholderId, startedAt, intervalId };
  }, []);

  const stopLatency = useCallback((stripFromId?: string) => {
    if (!latency.current) return;
    clearInterval(latency.current.intervalId);
    const trackedId = latency.current.messageId;
    latency.current = null;
    const target = stripFromId ?? trackedId;
    setMessages((prev) =>
      prev.map((m) => {
        if (m.id !== target) return m;
        if (m.latencyMs === undefined) return m;
        const { latencyMs: _drop, ...rest } = m;
        void _drop;
        return rest;
      }),
    );
  }, []);

  useEffect(() => {
    return client.onError((err) => {
      setStreamError(err);
      // A transport fault means no further deltas are coming — drop the
      // typing-dots placeholder so the user isn't left staring at it.
      const stuckId = buffer.current?.messageId;
      cancelFlush();
      buffer.current = null;
      stopLatency(stuckId);
      setIsStreaming(false);
      if (stuckId) {
        setMessages((prev) =>
          prev.filter((m) => !(m.id === stuckId && m.content.trim() === "")),
        );
      }
    });
  }, [client, stopLatency, cancelFlush]);

  const dismissStreamError = useCallback(() => setStreamError(null), []);

  // Reset local state when switching chats. ``streamError`` is scoped to the
  // send that triggered it, so a chat swap should wipe it out: a stale
  // "Message too large" banner on a freshly-opened chat-B would confuse the
  // user about which send actually failed (and in which chat).
  useEffect(() => {
    setMessages(initialMessages);
    setIsStreaming(false);
    setStreamError(null);
    cancelFlush();
    buffer.current = null;
    cluster.current = null;
    failoverSeen.current.clear();
    if (latency.current) {
      clearInterval(latency.current.intervalId);
      latency.current = null;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatId]);

  useEffect(() => {
    if (!chatId) return;

    const handle = (ev: InboundEvent) => {
      if (ev.event === "delta") {
        const id = buffer.current?.messageId ?? crypto.randomUUID();
        if (!buffer.current) {
          buffer.current = { messageId: id, parts: [] };
          setMessages((prev) => [
            ...prev,
            {
              id,
              role: "assistant",
              content: "",
              isStreaming: true,
              createdAt: Date.now(),
            },
          ]);
          setIsStreaming(true);
        }
        buffer.current.parts.push(ev.text);
        // First delta — drop the latency tick so the bubble reads cleanly.
        stopLatency(buffer.current.messageId);
        // Defer the actual setMessages to the next animation frame so a
        // burst of small WS chunks collapses into a single React render.
        scheduleFlush();
        return;
      }

      if (ev.event === "stream_end") {
        if (!ev.resuming && cluster.current) {
          // Freeze the per-turn cluster: clear isStreaming so chip pulses
          // stop, but keep the row in the thread so the user sees what
          // was edited. ``activities`` is preserved as-is.
          const frozenId = cluster.current.messageId;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === frozenId ? { ...m, isStreaming: false } : m,
            ),
          );
          cluster.current = null;
        }
        if (!buffer.current) {
          const finalFrameText = typeof ev.text === "string" ? ev.text : "";
          if (finalFrameText.length > 0) {
            const id = crypto.randomUUID();
            setMessages((prev) => [
              ...prev,
              {
                id,
                role: "assistant",
                content: finalFrameText,
                isStreaming: false,
                createdAt: Date.now(),
              },
            ]);
          }
          if (!ev.resuming) setIsStreaming(false);
          return;
        }
        const finalId = buffer.current.messageId;
        const finalText = typeof ev.text === "string" ? ev.text : buffer.current.parts.join("");
        cancelFlush();
        // ``resuming`` means the agent is still working (usually executing a
        // tool before the next model turn). Keep the placeholder alive so the
        // screen never looks idle between stream segments.
        if (ev.resuming) {
          buffer.current = { messageId: finalId, parts: [] };
          setMessages((prev) =>
            prev.map((m) =>
              m.id === finalId
                ? { ...m, content: "", isStreaming: true, latencyMs: 0 }
                : m,
            ),
          );
          setIsStreaming(true);
          startLatency(finalId);
          return;
        }
        buffer.current = null;
        // Stop latency BEFORE filtering — otherwise the interval keeps
        // firing against an id that no longer exists in the messages list.
        stopLatency(finalId);
        setIsStreaming(false);
        // Reasoning + tool-call assistant turns stream raw ``<think>...
        // </think>`` content followed by a tool call. ``finalText`` is
        // non-empty (the think block IS on the wire as deltas), but after
        // stripping reasoning, the visible answer is empty. Finalizing
        // the placeholder leaves a bare "Reasoning" pill in the thread
        // for every tool pivot. Drop the placeholder entirely when the
        // post-extractThink visible text is empty; reasoning is only
        // worth keeping when paired with a real answer.
        const visible = extractThinkBlocks(finalText).visible.trim();
        if (visible.length === 0) {
          setMessages((prev) => prev.filter((m) => m.id !== finalId));
          return;
        }
        // Flush any deltas that hadn't yet been painted in the trailing
        // frame, then mark the bubble as no longer streaming.
        setMessages((prev) =>
          prev.map((m) =>
            m.id === finalId
              ? { ...m, content: finalText, isStreaming: false }
              : m,
          ),
        );
        return;
      }

      if (ev.event === "message") {
        // Intermediate agent breadcrumbs (tool-call hints, raw progress).
        // Attach them to the last trace row if it was the last emitted item
        // so a sequence of calls collapses into one compact trace group.
        if (ev.kind === "tool_hint" || ev.kind === "progress") {
          const line = ev.text;
          setMessages((prev) => {
            const activeId = buffer.current?.messageId;
            const active = activeId ? prev.find((m) => m.id === activeId) : undefined;
            const base = activeId ? prev.filter((m) => m.id !== activeId) : prev;
            const last = base[base.length - 1];
            let next: UIMessage[];
            if (last && last.kind === "trace" && !last.isStreaming) {
              const merged: UIMessage = {
                ...last,
                traces: [...(last.traces ?? [last.content]), line],
                content: line,
              };
              next = [...base.slice(0, -1), merged];
            } else {
              next = [
                ...base,
                {
                  id: crypto.randomUUID(),
                  role: "tool",
                  kind: "trace",
                  content: line,
                  traces: [line],
                  createdAt: Date.now(),
                },
              ];
            }
            return active ? [...next, active] : next;
          });
          return;
        }

        // A complete (non-streamed) assistant message. If a stream was in
        // flight, drop the placeholder so we don't render the text twice.
        const activeId = buffer.current?.messageId;
        cancelFlush();
        buffer.current = null;
        stopLatency(activeId);
        setIsStreaming(false);
        // Tool-pivot turns can also arrive as full ``message`` frames rather
        // than streamed deltas. Skip if there's no visible answer text after
        // stripping reasoning — otherwise the thread accumulates a bare
        // "Reasoning" pill for every tool call.
        const messageVisible = extractThinkBlocks(ev.text).visible.trim();
        if (messageVisible.length === 0) {
          if (activeId) {
            setMessages((prev) => prev.filter((m) => m.id !== activeId));
          }
          return;
        }
        setMessages((prev) => {
          const filtered = activeId ? prev.filter((m) => m.id !== activeId) : prev;
          return [
            ...filtered,
            {
              id: crypto.randomUUID(),
              role: "assistant",
              content: ev.text,
              createdAt: Date.now(),
            },
          ];
        });
        return;
      }
      if (ev.event === "file_activity") {
        const a = ev.activity;
        if (!a || !a.call_id) return;
        const current = cluster.current;
        const prevEntry = current?.activities.get(a.call_id);
        // Phase state machine: once end/error has landed, ignore a late
        // ``start`` for that call (e.g. out-of-order delivery).
        if (prevEntry && prevEntry.phase !== "start" && a.phase === "start") {
          return;
        }
        const merged: FileEditActivity = {
          call_id: a.call_id,
          tool: a.tool,
          path: a.path,
          phase: a.phase,
          status: a.status,
          added: typeof a.added === "number" ? a.added : 0,
          deleted: typeof a.deleted === "number" ? a.deleted : 0,
          approximate: !!a.approximate,
          binary: !!a.binary,
          error: a.error,
          updatedAt: Date.now(),
        };
        const placeholderId = buffer.current?.messageId;
        if (!current) {
          // First activity of this turn: spawn the cluster row immediately
          // before the assistant placeholder (or at the end if none yet).
          const newId = crypto.randomUUID();
          const activities = new Map<string, FileEditActivity>();
          activities.set(a.call_id, merged);
          cluster.current = { messageId: newId, activities };
          const next: UIMessage = {
            id: newId,
            role: "tool",
            content: "",
            kind: "file_activity_cluster",
            isStreaming: true,
            createdAt: Date.now(),
            activities: Array.from(activities.values()),
          };
          setMessages((prev) => {
            const idx = placeholderId
              ? prev.findIndex((m) => m.id === placeholderId)
              : -1;
            if (idx < 0) return [...prev, next];
            return [...prev.slice(0, idx), next, ...prev.slice(idx)];
          });
          return;
        }
        current.activities.set(a.call_id, merged);
        const frozen = Array.from(current.activities.values());
        const clusterId = current.messageId;
        setMessages((prev) =>
          prev.map((m) =>
            m.id === clusterId ? { ...m, activities: frozen } : m,
          ),
        );
        return;
      }

      if (ev.event === "provider_failover") {
        const info = ev.info;
        if (!info || !info.primary || !info.fallback) return;
        const key = `${info.primary}->${info.fallback}`;
        const now = Date.now();
        const lastSeen = failoverSeen.current.get(key);
        if (lastSeen && now - lastSeen < FAILOVER_DEDUPE_WINDOW_MS) return;
        failoverSeen.current.set(key, now);
        setFailoverNotices((prev) => [
          ...prev,
          {
            id: crypto.randomUUID(),
            primary: info.primary,
            fallback: info.fallback,
            reason: info.reason,
            receivedAt: now,
          },
        ]);
        return;
      }
      if (ev.event === "webui_activity_replay") {
        // Refresh-survival: rebuild the in-flight chip cluster from the
        // persisted slice. The server already trimmed to events after the
        // most recent turn boundary, so a non-empty payload means the turn
        // is still in flight (or just finished and the live ``stream_end``
        // will arrive shortly and freeze the cluster via the existing path).
        if (ev.chat_id !== chatId) return;
        const seeded = new Map<string, FileEditActivity>(
          cluster.current ? cluster.current.activities : [],
        );
        for (const record of ev.events) {
          if (record.kind !== "file_activity") continue;
          const a = record.activity;
          if (!a.call_id) continue;
          const prev = seeded.get(a.call_id);
          // Phase state machine: a late ``start`` arriving after ``end`` /
          // ``error`` (e.g. live event arrived first then replay landed)
          // is silently dropped. Otherwise overwrite — most-recent wins.
          if (prev && prev.phase !== "start" && a.phase === "start") continue;
          seeded.set(a.call_id, {
            call_id: a.call_id,
            tool: a.tool,
            path: a.path,
            phase: a.phase,
            status: a.status,
            added: typeof a.added === "number" ? a.added : 0,
            deleted: typeof a.deleted === "number" ? a.deleted : 0,
            approximate: !!a.approximate,
            binary: !!a.binary,
            error: a.error,
            updatedAt: Date.now(),
          });
        }
        if (seeded.size === 0) return;
        const placeholderId = buffer.current?.messageId;
        const frozen = Array.from(seeded.values());
        if (cluster.current) {
          // Live events already spawned a cluster row — just patch its
          // activities list with the merged set.
          const clusterId = cluster.current.messageId;
          cluster.current.activities = seeded;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === clusterId ? { ...m, activities: frozen } : m,
            ),
          );
          return;
        }
        const newId = crypto.randomUUID();
        cluster.current = { messageId: newId, activities: seeded };
        const next: UIMessage = {
          id: newId,
          role: "tool",
          content: "",
          kind: "file_activity_cluster",
          isStreaming: true,
          createdAt: Date.now(),
          activities: frozen,
        };
        setMessages((prev) => {
          const idx = placeholderId
            ? prev.findIndex((m) => m.id === placeholderId)
            : -1;
          if (idx < 0) return [...prev, next];
          return [...prev.slice(0, idx), next, ...prev.slice(idx)];
        });
        return;
      }
      if (ev.event === "webui_activity_replay_error") {
        // Replay is a UX nicety, not a correctness gate — swallow.
        return;
      }
      if (ev.event === "error") {
        // Server rejected the request — clear the typing-dots placeholder so
        // the user isn't stuck staring at it. The dedicated error UI is driven
        // by ``client.onError`` (set up via the useEffect at the top of this
        // hook); we just need to land the local UI state cleanly.
        const stuckId = buffer.current?.messageId;
        cancelFlush();
        buffer.current = null;
        stopLatency(stuckId);
        setIsStreaming(false);
        if (stuckId) {
          setMessages((prev) =>
            prev.filter((m) => !(m.id === stuckId && m.content.trim() === "")),
          );
        }
        return;
      }
      // ``attached`` frames aren't actionable here; the client shell handles them.
    };

    const unsub = client.onChat(chatId, handle);
    // Ask for the in-flight activity slice so refresh mid-turn restores the
    // chip cluster. Fire-and-forget — the response routes through ``handle``
    // as ``webui_activity_replay`` (or is silently dropped on error).
    client.requestActivityReplay(chatId);
    return () => {
      unsub();
      cancelFlush();
      buffer.current = null;
      if (latency.current) {
        clearInterval(latency.current.intervalId);
        latency.current = null;
      }
    };
  }, [chatId, client, stopLatency, scheduleFlush, cancelFlush]);

  const send = useCallback(
    (content: string, images?: SendImage[]) => {
      if (!chatId) return;
      const hasImages = !!images && images.length > 0;
      // Text is optional when images are attached — the agent will still see
      // the image blocks via ``media`` paths.
      if (!hasImages && !content.trim()) return;

      const previews = hasImages ? images!.map((i) => i.preview) : undefined;
      // Pre-allocate the assistant placeholder bubble so the typing indicator
      // shows immediately (between Enter and the first delta) instead of
      // appearing only once tokens start streaming. The delta handler reuses
      // this bubble's id via buffer.current so we don't spawn a duplicate.
      const placeholderId = crypto.randomUUID();
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "user",
          content,
          createdAt: Date.now(),
          ...(previews ? { images: previews } : {}),
        },
        {
          id: placeholderId,
          role: "assistant",
          content: "",
          isStreaming: true,
          latencyMs: 0,
          createdAt: Date.now(),
        },
      ]);
      buffer.current = { messageId: placeholderId, parts: [] };
      setIsStreaming(true);
      startLatency(placeholderId);
      // Fresh user turn re-enables the failover dedupe set so the same
      // primary->fallback swap can surface again on the next attempt.
      failoverSeen.current.clear();
      cluster.current = null;
      const wireMedia = hasImages ? images!.map((i) => i.media) : undefined;
      client.sendMessage(chatId, content, wireMedia);
    },
    [chatId, client, startLatency],
  );

  const dismissFailoverNotice = useCallback((id: string) => {
    setFailoverNotices((prev) => prev.filter((n) => n.id !== id));
  }, []);

  const stop = useCallback(() => {
    if (!chatId) return;
    client.sendStop(chatId);
    // Drop the empty typing-dots placeholder; the agent will not produce
    // further deltas for the cancelled turn.
    const stuckId = buffer.current?.messageId;
    cancelFlush();
    buffer.current = null;
    if (latency.current) {
      clearInterval(latency.current.intervalId);
      latency.current = null;
    }
    setIsStreaming(false);
    if (stuckId) {
      setMessages((prev) =>
        prev.filter((m) => !(m.id === stuckId && m.content.trim() === "")),
      );
    }
  }, [chatId, client, cancelFlush]);

  const regenerate = useCallback(() => {
    if (!chatId) return;
    // Cancel any in-flight stream before swapping the buffer; otherwise late
    // delta events for the old turn would leak into the new placeholder bubble.
    if (buffer.current) {
      client.sendStop(chatId);
    }
    cancelFlush();
    // Pre-allocate the typing placeholder so dots show immediately. Merging
    // truncate + placeholder into a single ``setMessages`` avoids a flash
    // of "user message with no assistant" between two state updates.
    const placeholderId = crypto.randomUUID();
    setMessages((prev) => {
      // Drop the trailing assistant message (and any tool-trace rows that
      // followed it) so the user only sees the in-flight regeneration once
      // the new stream begins. Stop at the last user message.
      let cut = prev.length;
      for (let i = prev.length - 1; i >= 0; i--) {
        if (prev[i].role === "user") {
          cut = i + 1;
          break;
        }
      }
      return [
        ...prev.slice(0, cut),
        {
          id: placeholderId,
          role: "assistant",
          content: "",
          isStreaming: true,
          latencyMs: 0,
          createdAt: Date.now(),
        },
      ];
    });
    buffer.current = { messageId: placeholderId, parts: [] };
    setIsStreaming(true);
    startLatency(placeholderId);
    failoverSeen.current.clear();
    cluster.current = null;
    client.regenerate(chatId);
  }, [chatId, client, startLatency, cancelFlush]);

  const editMessage = useCallback(
    (messageId: string, newContent: string) => {
      if (!chatId) return;
      // Cancel any in-flight stream before swapping the buffer; otherwise late
      // delta events for the old turn would leak into the new placeholder bubble.
      if (buffer.current) {
        client.sendStop(chatId);
      }
      cancelFlush();
      const idx = messages.findIndex(
        (m) => m.id === messageId && m.role === "user",
      );
      if (idx < 0) return;
      // Compute the user-only index for the wire envelope.
      const userMsgIndex =
        messages.slice(0, idx + 1).filter((m) => m.role === "user").length - 1;
      const placeholderId = crypto.randomUUID();
      setMessages((prev) => {
        // Defensive findIndex in case messages drifted between callback
        // creation and invocation (e.g. an inbound delta arrived first).
        const targetIdx = prev.findIndex(
          (m) => m.id === messageId && m.role === "user",
        );
        if (targetIdx < 0) return prev;
        return [
          ...prev.slice(0, targetIdx),
          { ...prev[targetIdx], content: newContent },
          {
            id: placeholderId,
            role: "assistant",
            content: "",
            isStreaming: true,
            latencyMs: 0,
            createdAt: Date.now(),
          },
        ];
      });
      buffer.current = { messageId: placeholderId, parts: [] };
      setIsStreaming(true);
      startLatency(placeholderId);
      failoverSeen.current.clear();
      cluster.current = null;
      client.editAndResend(chatId, userMsgIndex, newContent);
    },
    [chatId, client, messages, startLatency, cancelFlush],
  );

  return {
    messages,
    isStreaming,
    send,
    stop,
    regenerate,
    editMessage,
    setMessages,
    streamError,
    dismissStreamError,
    failoverNotices,
    dismissFailoverNotice,
  };
}
