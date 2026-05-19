import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { usePythinkerStream } from "@/hooks/usePythinkerStream";
import type { InboundEvent } from "@/lib/types";
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

function failoverEvent(primary: string, fallback: string, reason = "rate_limit"): InboundEvent {
  return {
    event: "provider_failover",
    chat_id: "chat-f",
    info: { version: 1, primary, fallback, reason },
  };
}

describe("usePythinkerStream / provider_failover notices", () => {
  it("surfaces one notice per primary->fallback pair", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => usePythinkerStream("chat-f", []), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-f", failoverEvent("openai/gpt-5", "anthropic/claude"));
    });

    expect(result.current.failoverNotices).toHaveLength(1);
    expect(result.current.failoverNotices[0].primary).toBe("openai/gpt-5");
    expect(result.current.failoverNotices[0].fallback).toBe("anthropic/claude");
    expect(result.current.failoverNotices[0].reason).toBe("rate_limit");
  });

  it("dedupes repeated events within the same turn", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => usePythinkerStream("chat-f", []), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-f", failoverEvent("openai/gpt-5", "anthropic/claude"));
      fake.emit("chat-f", failoverEvent("openai/gpt-5", "anthropic/claude"));
      fake.emit("chat-f", failoverEvent("openai/gpt-5", "anthropic/claude"));
    });

    expect(result.current.failoverNotices).toHaveLength(1);
  });

  it("re-enables the same pair after the user starts a new turn", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => usePythinkerStream("chat-f", []), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-f", failoverEvent("openai/gpt-5", "anthropic/claude"));
    });
    expect(result.current.failoverNotices).toHaveLength(1);

    act(() => {
      result.current.send("another question");
    });
    act(() => {
      fake.emit("chat-f", failoverEvent("openai/gpt-5", "anthropic/claude"));
    });
    expect(result.current.failoverNotices).toHaveLength(2);
  });

  it("dismissFailoverNotice drops the matching notice only", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => usePythinkerStream("chat-f", []), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-f", failoverEvent("openai/gpt-5", "anthropic/claude"));
      fake.emit("chat-f", failoverEvent("anthropic/claude", "openai/gpt-mini"));
    });
    expect(result.current.failoverNotices).toHaveLength(2);

    const targetId = result.current.failoverNotices[0].id;
    act(() => {
      result.current.dismissFailoverNotice(targetId);
    });
    expect(result.current.failoverNotices).toHaveLength(1);
    expect(result.current.failoverNotices[0].id).not.toBe(targetId);
  });

  it("ignores malformed failover events with missing primary/fallback", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => usePythinkerStream("chat-f", []), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      // Cast through unknown because the InboundEvent union requires both
      // fields; we're simulating a defensive boundary check.
      fake.emit(
        "chat-f",
        {
          event: "provider_failover",
          chat_id: "chat-f",
          info: { version: 1, primary: "", fallback: "", reason: "" },
        } as unknown as InboundEvent,
      );
    });
    expect(result.current.failoverNotices).toEqual([]);
  });
});
