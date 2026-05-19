import { useCallback, useEffect, useRef, useState } from "react";

import { useClient } from "@/providers/ClientProvider";
import type {
  WebUISidebarDensity,
  WebUISidebarSort,
  WebUISidebarState,
} from "@/lib/types";

const DEBOUNCE_MS = 500;

/** Match the schema-v1 defaults in ``pythinker/webui/sidebar_state.py`` so
 * the UI starts with the same shape regardless of whether the server replied
 * yet. Pin/archive arrays stay empty because pin/archive lives in per-session
 * sidecars; the hook never writes those fields. */
export function defaultSidebarState(): WebUISidebarState {
  return {
    schema_version: 1,
    pinned_keys: [],
    archived_keys: [],
    title_overrides: {},
    tags_by_key: {},
    collapsed_groups: {},
    view: {
      density: "comfortable",
      show_previews: false,
      show_timestamps: false,
      show_archived: false,
      sort: "updated_desc",
    },
    updated_at: null,
  };
}

export type SidebarStateUpdate = {
  view?: Partial<WebUISidebarState["view"]>;
  collapsed_groups?: Record<string, boolean>;
  title_overrides?: Record<string, string>;
  tags_by_key?: Record<string, string[]>;
};

export interface UseSidebarStateResult {
  state: WebUISidebarState;
  loading: boolean;
  /** True when persistence fell back to in-memory only — either the initial
   * fetch failed or a ``.set`` write was refused (non-admin connection). UI
   * still updates but reloads will lose changes. */
  isLocal: boolean;
  update: (patch: SidebarStateUpdate) => void;
}

function mergeState(prev: WebUISidebarState, patch: SidebarStateUpdate): WebUISidebarState {
  const next: WebUISidebarState = {
    ...prev,
    view: patch.view ? { ...prev.view, ...patch.view } : prev.view,
    collapsed_groups: patch.collapsed_groups
      ? { ...prev.collapsed_groups, ...patch.collapsed_groups }
      : prev.collapsed_groups,
    title_overrides: patch.title_overrides
      ? { ...prev.title_overrides, ...patch.title_overrides }
      : prev.title_overrides,
    tags_by_key: patch.tags_by_key
      ? { ...prev.tags_by_key, ...patch.tags_by_key }
      : prev.tags_by_key,
  };
  return next;
}

export function useSidebarState(): UseSidebarStateResult {
  const { client } = useClient();
  const [state, setState] = useState<WebUISidebarState>(() => defaultSidebarState());
  const [loading, setLoading] = useState(true);
  const [isLocal, setIsLocal] = useState(false);
  const stateRef = useRef(state);
  stateRef.current = state;
  const isLocalRef = useRef(isLocal);
  isLocalRef.current = isLocal;
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;
    const fetched = (async () => client.getSidebarState())();
    fetched
      .then((next) => {
        if (cancelled) return;
        setState(next);
        setLoading(false);
      })
      .catch(() => {
        if (cancelled) return;
        setLoading(false);
        setIsLocal(true);
      });
    return () => {
      cancelled = true;
      if (debounceTimer.current) {
        clearTimeout(debounceTimer.current);
        debounceTimer.current = null;
      }
    };
  }, [client]);

  const update = useCallback(
    (patch: SidebarStateUpdate) => {
      setState((prev) => {
        const next = mergeState(prev, patch);
        stateRef.current = next;
        return next;
      });
      if (isLocalRef.current) return;
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
      debounceTimer.current = setTimeout(() => {
        debounceTimer.current = null;
        const written = (async () => client.setSidebarState(stateRef.current))();
        written.then((saved) => setState(saved)).catch(() => setIsLocal(true));
      }, DEBOUNCE_MS);
    },
    [client],
  );

  return { state, loading, isLocal, update };
}

export type { WebUISidebarDensity, WebUISidebarSort };
