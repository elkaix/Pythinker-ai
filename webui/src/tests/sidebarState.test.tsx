import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { defaultSidebarState, useSidebarState } from "@/hooks/useSidebarState";
import type { PythinkerClient } from "@/lib/pythinker-client";
import type { WebUISidebarState } from "@/lib/types";
import { ClientProvider } from "@/providers/ClientProvider";

function makeClient(): {
  client: PythinkerClient;
  getMock: ReturnType<typeof vi.fn>;
  setMock: ReturnType<typeof vi.fn>;
} {
  const getMock = vi.fn();
  const setMock = vi.fn();
  const client = {
    getSidebarState: getMock,
    setSidebarState: setMock,
  } as unknown as PythinkerClient;
  return { client, getMock, setMock };
}

function wrap(client: PythinkerClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <ClientProvider client={client} token="admin">
        {children}
      </ClientProvider>
    );
  };
}

describe("useSidebarState", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("fetches state on mount and exposes it", async () => {
    const persisted: WebUISidebarState = {
      ...defaultSidebarState(),
      view: { ...defaultSidebarState().view, show_archived: true, density: "compact" },
      collapsed_groups: { archived: true },
      updated_at: "2026-05-19T10:00:00Z",
    };
    const { client, getMock } = makeClient();
    getMock.mockResolvedValue(persisted);

    const { result } = renderHook(() => useSidebarState(), { wrapper: wrap(client) });

    await act(async () => {
      await vi.runAllTimersAsync();
    });

    expect(getMock).toHaveBeenCalledTimes(1);
    expect(result.current.loading).toBe(false);
    expect(result.current.isLocal).toBe(false);
    expect(result.current.state.view.show_archived).toBe(true);
    expect(result.current.state.view.density).toBe("compact");
    expect(result.current.state.collapsed_groups.archived).toBe(true);
  });

  it("debounces .set writes and sends the full merged state", async () => {
    const { client, getMock, setMock } = makeClient();
    getMock.mockResolvedValue(defaultSidebarState());
    setMock.mockImplementation(async (state) => state);

    const { result } = renderHook(() => useSidebarState(), { wrapper: wrap(client) });
    await act(async () => {
      await vi.runAllTimersAsync();
    });

    // Three rapid updates within the debounce window collapse to one .set.
    act(() => {
      result.current.update({ view: { show_archived: true } });
      result.current.update({ view: { density: "compact" } });
      result.current.update({ collapsed_groups: { recent: true } });
    });
    expect(setMock).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });
    expect(setMock).toHaveBeenCalledTimes(1);
    const sent = setMock.mock.calls[0][0] as WebUISidebarState;
    expect(sent.view.show_archived).toBe(true);
    expect(sent.view.density).toBe("compact");
    expect(sent.collapsed_groups.recent).toBe(true);
    // Pin/archive arrays remain empty — sidecars own those fields.
    expect(sent.pinned_keys).toEqual([]);
    expect(sent.archived_keys).toEqual([]);
  });

  it("falls back to in-memory state when initial fetch fails", async () => {
    const { client, getMock, setMock } = makeClient();
    getMock.mockRejectedValue(new Error("admin token required"));

    const { result } = renderHook(() => useSidebarState(), { wrapper: wrap(client) });
    await act(async () => {
      await vi.runAllTimersAsync();
    });

    expect(result.current.loading).toBe(false);
    expect(result.current.isLocal).toBe(true);

    act(() => {
      result.current.update({ view: { show_archived: true } });
    });
    expect(result.current.state.view.show_archived).toBe(true);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });
    // No persistence attempt while in local-fallback mode.
    expect(setMock).not.toHaveBeenCalled();
  });

  it("downgrades to local mode when a .set call is refused", async () => {
    const { client, getMock, setMock } = makeClient();
    getMock.mockResolvedValue(defaultSidebarState());
    setMock.mockRejectedValue(new Error("admin token required"));

    const { result } = renderHook(() => useSidebarState(), { wrapper: wrap(client) });
    await act(async () => {
      await vi.runAllTimersAsync();
    });

    act(() => {
      result.current.update({ view: { show_archived: true } });
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
      // Let the rejected setSidebarState promise's .catch() run so isLocal
      // updates before we assert. Two flushes cover the chain.
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(setMock).toHaveBeenCalledTimes(1);
    expect(result.current.isLocal).toBe(true);

    // Further updates do not retry.
    act(() => {
      result.current.update({ view: { density: "compact" } });
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });
    expect(setMock).toHaveBeenCalledTimes(1);
  });
});
