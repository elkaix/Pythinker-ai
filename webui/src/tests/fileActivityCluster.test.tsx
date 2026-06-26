import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { AgentActivityCluster } from "@/components/thread/AgentActivityCluster";
import { usePythinkerStream } from "@/hooks/usePythinkerStream";
import type { FileActivityPayload, FileEditActivity, InboundEvent, UIMessage } from "@/lib/types";
import { ClientProvider } from "@/providers/ClientProvider";

function fakeClient() {
  const handlers = new Map<string, Set<(ev: InboundEvent) => void>>();
  return {
    client: {
      status: "open" as const,
      defaultChatId: null as string | null,
      onStatus: () => () => {},
      onError: () => () => {},
      onChat(chatId: string, h: (ev: InboundEvent) => void) {
        let set = handlers.get(chatId);
        if (!set) {
          set = new Set();
          handlers.set(chatId, set);
        }
        set.add(h);
        return () => set!.delete(h);
      },
      sendMessage: vi.fn(),
      requestActivityReplay: vi.fn(),
      newChat: vi.fn(),
      attach: vi.fn(),
      connect: vi.fn(),
      close: vi.fn(),
      updateUrl: vi.fn(),
    },
    emit(chatId: string, ev: InboundEvent) {
      const set = handlers.get(chatId);
      set?.forEach((h) => h(ev));
    },
  };
}

function wrap(client: ReturnType<typeof fakeClient>["client"]) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <ClientProvider
        client={
          client as unknown as import("@/lib/pythinker-client").PythinkerClient
        }
        token="tok"
      >
        {children}
      </ClientProvider>
    );
  };
}

function activity(overrides: Partial<FileActivityPayload> = {}): FileActivityPayload {
  return {
    version: 1,
    call_id: "call-1",
    tool: "write_file",
    path: "pkg/mod.py",
    phase: "start",
    status: "editing",
    added: 0,
    deleted: 0,
    approximate: true,
    binary: false,
    ...overrides,
  };
}

function makeClusterMessage(activities: FileEditActivity[], id = "msg-1"): UIMessage {
  return {
    id,
    role: "tool" as const,
    content: "",
    kind: "file_activity_cluster" as const,
    isStreaming: false,
    createdAt: Date.now(),
    activities,
  };
}

describe("AgentActivityCluster", () => {
  it("does not show unresolved pathless edit counters after completion", () => {
    render(
      <AgentActivityCluster
        messages={[
          makeClusterMessage([
            {
              call_id: "call-pending",
              tool: "write_file",
              path: "",
              phase: "start",
              status: "editing",
              added: 98,
              deleted: 0,
              approximate: true,
              binary: false,
              updatedAt: Date.now(),
            },
          ]),
        ]}
        isStreaming={false}
      />,
    );

    expect(screen.queryByTestId("agent-activity-cluster")).not.toBeInTheDocument();
  });

  it("shows diff stats for visible file edits after expanding", () => {
    render(
      <AgentActivityCluster
        messages={[
          makeClusterMessage([
            {
              call_id: "call-done",
              tool: "write_file",
              path: "pkg/mod.py",
              phase: "end",
              status: "done",
              added: 12,
              deleted: 3,
              approximate: false,
              binary: false,
              updatedAt: Date.now(),
            },
          ]),
        ]}
        isStreaming={false}
      />,
    );

    // Cluster renders
    expect(screen.getByTestId("agent-activity-cluster")).toBeInTheDocument();
    // Expand the cluster
    fireEvent.click(screen.getByRole("button"));
    // Stats are visible
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    // File path label visible
    expect(screen.getByText("mod.py")).toBeInTheDocument();
  });
});

describe("usePythinkerStream / file_activity cluster", () => {
  it("creates a cluster on the first activity event", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => usePythinkerStream("chat-a", []), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-a", { event: "file_activity", chat_id: "chat-a", activity: activity() });
    });

    const cluster = result.current.messages.find(
      (m) => m.kind === "file_activity_cluster",
    );
    expect(cluster).toBeDefined();
    expect(cluster?.activities).toHaveLength(1);
    expect(cluster?.activities?.[0].call_id).toBe("call-1");
    expect(cluster?.isStreaming).toBe(true);
  });

  it("collapses repeated phases for the same call_id and progresses start->end", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => usePythinkerStream("chat-a", []), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-a", { event: "file_activity", chat_id: "chat-a", activity: activity() });
      fake.emit("chat-a", {
        event: "file_activity",
        chat_id: "chat-a",
        activity: activity({ phase: "end", status: "done", added: 12, deleted: 3, approximate: false }),
      });
      // Late start after end is ignored.
      fake.emit("chat-a", { event: "file_activity", chat_id: "chat-a", activity: activity() });
    });

    const cluster = result.current.messages.find(
      (m) => m.kind === "file_activity_cluster",
    );
    expect(cluster?.activities).toHaveLength(1);
    const a = cluster?.activities?.[0];
    expect(a?.phase).toBe("end");
    expect(a?.added).toBe(12);
    expect(a?.deleted).toBe(3);
  });

  it("freezes the cluster on stream_end without resuming and starts a fresh one next turn", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => usePythinkerStream("chat-a", []), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-a", { event: "file_activity", chat_id: "chat-a", activity: activity() });
      fake.emit("chat-a", { event: "stream_end", chat_id: "chat-a" });
    });

    const firstCluster = result.current.messages.find(
      (m) => m.kind === "file_activity_cluster",
    );
    expect(firstCluster?.isStreaming).toBe(false);

    act(() => {
      fake.emit("chat-a", {
        event: "file_activity",
        chat_id: "chat-a",
        activity: activity({ call_id: "call-2", path: "pkg/other.py" }),
      });
    });

    const clusters = result.current.messages.filter(
      (m) => m.kind === "file_activity_cluster",
    );
    expect(clusters).toHaveLength(2);
    expect(clusters[1].activities?.[0].call_id).toBe("call-2");
  });

  it("keeps the cluster streaming while stream_end signals resuming", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => usePythinkerStream("chat-a", []), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-a", { event: "file_activity", chat_id: "chat-a", activity: activity() });
      fake.emit("chat-a", { event: "stream_end", chat_id: "chat-a", resuming: true });
    });

    const cluster = result.current.messages.find(
      (m) => m.kind === "file_activity_cluster",
    );
    expect(cluster?.isStreaming).toBe(true);
  });

  it("renders error phase distinctly and carries the error string", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => usePythinkerStream("chat-a", []), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-a", {
        event: "file_activity",
        chat_id: "chat-a",
        activity: activity({ phase: "error", status: "error", error: "permission denied" }),
      });
    });

    const cluster = result.current.messages.find(
      (m) => m.kind === "file_activity_cluster",
    );
    expect(cluster?.activities?.[0].phase).toBe("error");
    expect(cluster?.activities?.[0].error).toBe("permission denied");
  });
});
