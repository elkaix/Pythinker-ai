import { ChevronDown, ChevronRight } from "lucide-react";
import { memo, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { ChatRow } from "@/components/ChatRow";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cleanChatTitle } from "@/lib/chatTitle";
import { cn } from "@/lib/utils";
import type { ChatSummary, WebUISidebarDensity } from "@/lib/types";

export interface ChatSection {
  id: string;
  label: string;
  items: ChatSummary[];
  collapsible?: boolean;
  defaultOpen?: boolean;
}

const INITIAL_VISIBLE_SESSIONS = 160;
const VISIBLE_SESSIONS_INCREMENT = 160;

interface ChatListProps {
  /** New section-aware shape. When omitted, the list falls back to ``sessions``
   * wrapped in a single unlabeled section so existing callers keep working. */
  sections?: ChatSection[];
  /** Legacy flat list. Equivalent to ``[{ id: 'all', label: '', items: sessions }]``. */
  sessions?: ChatSummary[];
  activeKey: string | null;
  loading?: boolean;
  density?: WebUISidebarDensity;
  /** When supplied, section collapse state is controlled by the parent
   * (persisted to ``webui_sidebar_state.collapsed_groups``) rather than
   * the per-Section local ``useState``. */
  onToggleCollapse?: (sectionId: string, collapsed: boolean) => void;
  onSelect: (key: string) => void;
  onRequestDelete: (key: string, label: string) => void;
  onTogglePin?: (key: string) => void;
  onToggleArchive?: (key: string) => void;
}

function titleFor(s: ChatSummary, fallbackTitle: string): string {
  // Prefer the LLM-generated chat title, then the literal first user
  // message preview, then the i18n fallback. The title is already capped
  // server-side; preview is truncated here for sidebar layout.
  // ``cleanChatTitle`` strips legacy ``<think>...</think>`` blocks (and
  // unterminated streaming tails) so old chats from before the backend
  // fix land cleanly without a one-shot migration.
  const summarized = cleanChatTitle(s.title);
  if (summarized) return summarized;
  const p = cleanChatTitle(s.preview);
  if (p) return p.length > 48 ? `${p.slice(0, 45)}…` : p;
  return fallbackTitle;
}

function resolveSections(
  sections: ChatSection[] | undefined,
  sessions: ChatSummary[] | undefined,
): ChatSection[] {
  if (sections) return sections;
  return [{ id: "all", label: "", items: sessions ?? [] }];
}

export const ChatList = memo(function ChatList({
  sections,
  sessions,
  activeKey,
  loading,
  density = "comfortable",
  onToggleCollapse,
  onSelect,
  onRequestDelete,
  onTogglePin,
  onToggleArchive,
}: ChatListProps) {
  const { t } = useTranslation();
  const [visibleLimit, setVisibleLimit] = useState(INITIAL_VISIBLE_SESSIONS);
  const resolved = useMemo(() => resolveSections(sections, sessions), [sections, sessions]);
  const totalItems = useMemo(
    () => resolved.reduce((n, sec) => n + sec.items.length, 0),
    [resolved],
  );
  const visibleSections = useMemo(
    () => limitSections(resolved, visibleLimit, activeKey),
    [activeKey, resolved, visibleLimit],
  );
  const visibleItems = useMemo(
    () => visibleSections.reduce((n, sec) => n + sec.items.length, 0),
    [visibleSections],
  );
  const hiddenItems = Math.max(0, totalItems - visibleItems);

  useEffect(() => {
    setVisibleLimit(INITIAL_VISIBLE_SESSIONS);
  }, [sections, sessions]);

  if (loading && totalItems === 0) {
    return (
      <div className="px-3 py-6 text-[12px] text-muted-foreground">
        {t("chat.loading")}
      </div>
    );
  }
  if (totalItems === 0) {
    return (
      <div className="px-3 py-6 text-xs text-muted-foreground">
        {t("chat.noSessions")}
      </div>
    );
  }

  return (
    <ScrollArea className="h-full">
      <div className="space-y-1 pb-2">
        {visibleSections.map((sec) =>
          sec.items.length > 0 ? (
            <Section
              key={sec.id}
              section={sec}
              density={density}
              fallbackTitle={t("chat.fallbackTitle")}
              activeKey={activeKey}
              onToggleCollapse={onToggleCollapse}
              onSelect={onSelect}
              onRequestDelete={onRequestDelete}
              onTogglePin={onTogglePin}
              onToggleArchive={onToggleArchive}
            />
          ) : null,
        )}
        {hiddenItems > 0 ? (
          <div className="px-2 pb-2 pt-1">
            <button
              type="button"
              onClick={() =>
                setVisibleLimit((limit) =>
                  Math.min(totalItems, limit + VISIBLE_SESSIONS_INCREMENT),
                )
              }
              className="h-8 w-full rounded-full text-[12px] font-medium text-muted-foreground transition-colors hover:bg-sidebar-accent/65 hover:text-sidebar-foreground"
            >
              {t("chat.showMore", { count: hiddenItems })}
            </button>
          </div>
        ) : null}
      </div>
    </ScrollArea>
  );
});

function limitSections(
  sections: ChatSection[],
  limit: number,
  activeKey: string | null,
): ChatSection[] {
  let remaining = Math.max(0, limit);
  let activeVisible = !activeKey;
  const out: ChatSection[] = [];

  for (const section of sections) {
    const visible = remaining > 0 ? section.items.slice(0, remaining) : [];
    remaining -= visible.length;
    if (activeKey && visible.some((item) => item.key === activeKey)) {
      activeVisible = true;
    }
    if (visible.length > 0) {
      out.push({ ...section, items: visible });
    }
  }

  if (activeVisible || !activeKey) return out;

  for (const section of sections) {
    const active = section.items.find((item) => item.key === activeKey);
    if (!active) continue;
    const existing = out.find((item) => item.id === section.id);
    if (existing) {
      existing.items = [...existing.items, active];
    } else {
      out.push({ ...section, items: [active] });
    }
    return out;
  }

  return out;
}

function Section({
  section,
  density,
  fallbackTitle,
  activeKey,
  onToggleCollapse,
  onSelect,
  onRequestDelete,
  onTogglePin,
  onToggleArchive,
}: {
  section: ChatSection;
  density: WebUISidebarDensity;
  fallbackTitle: string;
  activeKey: string | null;
  onToggleCollapse?: (sectionId: string, collapsed: boolean) => void;
  onSelect: (key: string) => void;
  onRequestDelete: (key: string, label: string) => void;
  onTogglePin?: (key: string) => void;
  onToggleArchive?: (key: string) => void;
}) {
  const [localOpen, setLocalOpen] = useState(section.defaultOpen ?? true);
  const controlled = onToggleCollapse !== undefined;
  const open = controlled ? (section.defaultOpen ?? true) : localOpen;
  const showItems = !section.collapsible || open;
  const hasLabel = section.label.length > 0;
  const toggle = () => {
    if (controlled) {
      onToggleCollapse?.(section.id, open);
    } else {
      setLocalOpen((v) => !v);
    }
  };
  const itemSpacing = density === "compact" ? "space-y-0" : "space-y-0.5";

  return (
    <div>
      {hasLabel ? (
        <div className="flex items-center justify-between px-2.5 py-1 text-[11px] font-medium text-muted-foreground">
          {section.collapsible ? (
            <button
              type="button"
              onClick={toggle}
              className="inline-flex items-center gap-1 hover:text-foreground"
              aria-expanded={open}
            >
              {open ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
              {section.label}
            </button>
          ) : (
            <span>{section.label}</span>
          )}
        </div>
      ) : null}
      {showItems ? (
        <ul className={cn(itemSpacing, "px-2 py-1")}>
          {section.items.map((s) => (
            <li key={s.key}>
              <ChatRow
                session={s}
                active={s.key === activeKey}
                title={titleFor(s, fallbackTitle)}
                onSelect={onSelect}
                onRequestDelete={onRequestDelete}
                onTogglePin={onTogglePin}
                onToggleArchive={onToggleArchive}
              />
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
