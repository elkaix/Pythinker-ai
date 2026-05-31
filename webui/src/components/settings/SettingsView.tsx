import { useCallback, useEffect, useState } from "react";
import {
  Brain,
  Check,
  ChevronLeft,
  Eye,
  EyeOff,
  ImageIcon,
  Loader2,
  Palette,
  Search,
  Server,
  ShieldCheck,
  SlidersHorizontal,
  Zap,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  fetchSettings,
  updateNetworkSafetySettings,
  updateProviderSettings,
  updateSettings,
  updateWebSearchSettings,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { useClient } from "@/providers/ClientProvider";
import type { SettingsPayload, SettingsProviderRow } from "@/lib/types";

export type SettingsSectionKey =
  | "overview"
  | "appearance"
  | "models"
  | "providers"
  | "browser"
  | "image"
  | "runtime"
  | "advanced";

interface SettingsViewProps {
  onBack?: () => void;
  initialSection?: SettingsSectionKey;
}

const SECTION_LABELS: Record<SettingsSectionKey, string> = {
  overview: "Overview",
  appearance: "Appearance",
  models: "Models",
  providers: "Providers",
  browser: "Web Search",
  image: "Image Generation",
  runtime: "Runtime",
  advanced: "Advanced",
};

const SECTION_ICONS: Record<SettingsSectionKey, React.ComponentType<{ className?: string }>> = {
  overview: SlidersHorizontal,
  appearance: Palette,
  models: Brain,
  providers: Zap,
  browser: Search,
  image: ImageIcon,
  runtime: Server,
  advanced: ShieldCheck,
};

const CONTEXT_WINDOW_OPTIONS = [65_536, 262_144] as const;

function formatContextWindow(tokens: number): string {
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1)}M`;
  if (tokens >= 1_000) return `${Math.round(tokens / 1_000)}K`;
  return String(tokens);
}

function SecretInput({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  const [show, setShow] = useState(false);
  return (
    <div className="relative">
      <Input
        type={show ? "text" : "password"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="pr-10 font-mono text-sm"
      />
      <button
        type="button"
        className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
        onClick={() => setShow((v) => !v)}
        tabIndex={-1}
      >
        {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
      </button>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-4">
      <h3 className="text-base font-semibold text-foreground">{title}</h3>
      <div className="space-y-3">{children}</div>
    </div>
  );
}

function SettingRow({
  label,
  description,
  children,
}: {
  label: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 py-2">
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium text-foreground">{label}</div>
        {description ? (
          <div className="mt-0.5 text-xs text-muted-foreground">{description}</div>
        ) : null}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

function OverviewPanel({ settings }: { settings: SettingsPayload }) {
  const { agent, runtime } = settings;
  return (
    <div className="space-y-6">
      <Section title="Active Configuration">
        <div className="rounded-lg border border-border bg-muted/30 p-4 space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-muted-foreground">Model</span>
            <span className="font-mono text-xs">{agent.model}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Provider</span>
            <span className="font-mono text-xs">{agent.resolved_provider}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Context Window</span>
            <span className="font-mono text-xs">{formatContextWindow(agent.context_window_tokens)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Config</span>
            <span className="font-mono text-xs truncate max-w-48">{runtime.config_path}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Workspace</span>
            <span className="font-mono text-xs truncate max-w-48">{runtime.workspace_path}</span>
          </div>
        </div>
      </Section>
      {settings.requires_restart ? (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
          Restart required to apply changes.
        </div>
      ) : null}
    </div>
  );
}

function ModelsPanel({
  settings,
  onSaved,
}: {
  settings: SettingsPayload;
  onSaved: (p: SettingsPayload) => void;
}) {
  const { token } = useClient();
  const [model, setModel] = useState(settings.agent.model);
  const [provider, setProvider] = useState(settings.agent.provider);
  const [contextWindow, setContextWindow] = useState(settings.agent.context_window_tokens);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const dirty =
    model !== settings.agent.model ||
    provider !== settings.agent.provider ||
    contextWindow !== settings.agent.context_window_tokens;

  const save = useCallback(async () => {
    setSaving(true);
    try {
      const update: Record<string, string> = {};
      if (model !== settings.agent.model) update.model = model;
      if (provider !== settings.agent.provider) update.provider = provider;
      if (contextWindow !== settings.agent.context_window_tokens) {
        update.context_window_tokens = String(contextWindow);
      }
      const result = await updateSettings(update, token, "");
      onSaved(result);
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    } finally {
      setSaving(false);
    }
  }, [token, model, provider, contextWindow, settings, onSaved]);

  return (
    <div className="space-y-6">
      <Section title="Default Model">
        <SettingRow
          label="Model ID"
          description="The model used for new conversations"
        >
          <Input
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="w-64 font-mono text-sm"
            placeholder="e.g. openai/gpt-4o"
          />
        </SettingRow>
        <SettingRow label="Provider" description="Force a specific provider, or 'auto'">
          <Input
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            className="w-48 font-mono text-sm"
            placeholder="auto"
          />
        </SettingRow>
        <SettingRow
          label="Context Window"
          description="Max tokens for the conversation context"
        >
          <div className="flex gap-1">
            {CONTEXT_WINDOW_OPTIONS.map((opt) => (
              <button
                key={opt}
                type="button"
                className={cn(
                  "rounded-md border px-3 py-1 text-xs font-medium transition-colors",
                  contextWindow === opt
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-border bg-background text-muted-foreground hover:border-primary/50",
                )}
                onClick={() => setContextWindow(opt)}
              >
                {formatContextWindow(opt)}
              </button>
            ))}
          </div>
        </SettingRow>
      </Section>

      <div className="flex items-center gap-2">
        <Button
          size="sm"
          onClick={save}
          disabled={!dirty || saving}
        >
          {saving ? (
            <Loader2 className="mr-2 h-3 w-3 animate-spin" />
          ) : saved ? (
            <Check className="mr-2 h-3 w-3" />
          ) : null}
          {saved ? "Saved" : "Save"}
        </Button>
        {dirty && !saving ? (
          <span className="text-xs text-muted-foreground">Unsaved changes</span>
        ) : null}
      </div>
    </div>
  );
}

function ProviderRow({
  provider,
  onSaved,
}: {
  provider: SettingsProviderRow;
  onSaved: (p: SettingsPayload) => void;
}) {
  const { token } = useClient();
  const [expanded, setExpanded] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [apiBase, setApiBase] = useState(provider.api_base || "");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const save = useCallback(async () => {
    setSaving(true);
    try {
      const update: Record<string, string> = { provider: provider.name };
      if (apiKey.trim()) update.api_key = apiKey.trim();
      if (apiBase.trim() !== (provider.api_base || "")) update.api_base = apiBase.trim();
      const result = await updateProviderSettings(update, token, "");
      onSaved(result);
      setSaved(true);
      setApiKey("");
      setTimeout(() => setSaved(false), 1500);
      setExpanded(false);
    } finally {
      setSaving(false);
    }
  }, [token, apiKey, apiBase, provider, onSaved]);

  return (
    <div className="rounded-lg border border-border">
      <button
        type="button"
        className="flex w-full items-center justify-between px-4 py-3 text-sm"
        onClick={() => setExpanded((v) => !v)}
      >
        <div className="flex items-center gap-3">
          <div
            className={cn(
              "h-2 w-2 rounded-full",
              provider.configured ? "bg-green-500" : "bg-muted-foreground/40",
            )}
          />
          <span className="font-medium">{provider.label}</span>
          <span className="font-mono text-xs text-muted-foreground">{provider.name}</span>
        </div>
        <span className="text-xs text-muted-foreground">
          {provider.configured ? "Configured" : provider.api_key_hint || "Not configured"}
        </span>
      </button>
      {expanded ? (
        <div className="border-t border-border px-4 py-3 space-y-3">
          {provider.api_key_required ? (
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">
                API Key {provider.api_key_hint ? `(current: ${provider.api_key_hint})` : ""}
              </label>
              <SecretInput
                value={apiKey}
                onChange={setApiKey}
                placeholder="Enter new API key to replace"
              />
            </div>
          ) : null}
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">
              API Base URL {provider.default_api_base ? `(default: ${provider.default_api_base})` : ""}
            </label>
            <Input
              value={apiBase}
              onChange={(e) => setApiBase(e.target.value)}
              className="font-mono text-sm"
              placeholder={provider.default_api_base || "https://api.example.com/v1"}
            />
          </div>
          <div className="flex gap-2">
            <Button size="sm" onClick={save} disabled={saving}>
              {saving ? <Loader2 className="mr-2 h-3 w-3 animate-spin" /> : saved ? <Check className="mr-2 h-3 w-3" /> : null}
              {saved ? "Saved" : "Save"}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setExpanded(false)}>Cancel</Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ProvidersPanel({
  settings,
  onSaved,
}: {
  settings: SettingsPayload;
  onSaved: (p: SettingsPayload) => void;
}) {
  return (
    <div className="space-y-3">
      {settings.providers.map((provider) => (
        <ProviderRow key={provider.name} provider={provider} onSaved={onSaved} />
      ))}
    </div>
  );
}

function WebSearchPanel({
  settings,
  onSaved,
}: {
  settings: SettingsPayload;
  onSaved: (p: SettingsPayload) => void;
}) {
  const { token } = useClient();
  const { web_search } = settings;
  const [provider, setProvider] = useState(web_search.provider);
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState(web_search.base_url || "");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const selectedProvider = web_search.providers.find((p) => p.name === provider);

  const save = useCallback(async () => {
    setSaving(true);
    try {
      const update: Record<string, string> = { provider };
      if (apiKey.trim()) update.api_key = apiKey.trim();
      if (baseUrl.trim()) update.base_url = baseUrl.trim();
      const result = await updateWebSearchSettings(update, token, "");
      onSaved(result);
      setSaved(true);
      setApiKey("");
      setTimeout(() => setSaved(false), 1500);
    } finally {
      setSaving(false);
    }
  }, [token, provider, apiKey, baseUrl, onSaved]);

  return (
    <div className="space-y-6">
      <Section title="Search Provider">
        <div className="flex flex-wrap gap-2">
          {web_search.providers.map((p) => (
            <button
              key={p.name}
              type="button"
              className={cn(
                "rounded-md border px-3 py-1.5 text-xs font-medium transition-colors",
                provider === p.name
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-background text-muted-foreground hover:border-primary/50",
              )}
              onClick={() => setProvider(p.name)}
            >
              {p.label}
            </button>
          ))}
        </div>
        {selectedProvider?.credential === "api_key" ? (
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">
              API Key {web_search.api_key_hint ? `(current: ${web_search.api_key_hint})` : ""}
            </label>
            <SecretInput
              value={apiKey}
              onChange={setApiKey}
              placeholder="Enter API key"
            />
          </div>
        ) : null}
        {selectedProvider?.credential === "base_url" ? (
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">
              Base URL
            </label>
            <Input
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              className="font-mono text-sm"
              placeholder="https://searxng.example.com"
            />
          </div>
        ) : null}
        <Button size="sm" onClick={save} disabled={saving}>
          {saving ? <Loader2 className="mr-2 h-3 w-3 animate-spin" /> : saved ? <Check className="mr-2 h-3 w-3" /> : null}
          {saved ? "Saved" : "Save"}
        </Button>
      </Section>
    </div>
  );
}

function RuntimePanel({ settings }: { settings: SettingsPayload }) {
  const { runtime } = settings;
  return (
    <div className="space-y-6">
      <Section title="Gateway">
        <div className="rounded-lg border border-border bg-muted/30 p-4 space-y-2 text-sm font-mono">
          <div className="flex justify-between">
            <span className="text-muted-foreground text-xs">Host</span>
            <span className="text-xs">{runtime.gateway_host}:{runtime.gateway_port}</span>
          </div>
        </div>
      </Section>
      <Section title="Heartbeat">
        <div className="rounded-lg border border-border bg-muted/30 p-4 space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-muted-foreground text-xs">Enabled</span>
            <span className="text-xs">{runtime.heartbeat.enabled ? "Yes" : "No"}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground text-xs">Interval</span>
            <span className="text-xs">{runtime.heartbeat.interval_s}s</span>
          </div>
        </div>
      </Section>
      <Section title="Dream">
        <div className="rounded-lg border border-border bg-muted/30 p-4 space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-muted-foreground text-xs">Schedule</span>
            <span className="text-xs">{runtime.dream.schedule}</span>
          </div>
        </div>
      </Section>
    </div>
  );
}

function AdvancedPanel({
  settings,
  onSaved,
}: {
  settings: SettingsPayload;
  onSaved: (p: SettingsPayload) => void;
}) {
  const { token } = useClient();
  const { advanced } = settings;
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const setAccessMode = useCallback(
    async (mode: "default" | "full") => {
      setSaving(true);
      try {
        const result = await updateNetworkSafetySettings(
          { webuiDefaultAccessMode: mode },
          token,
          "",
        );
        onSaved(result);
        setSaved(true);
        setTimeout(() => setSaved(false), 1500);
      } finally {
        setSaving(false);
      }
    },
    [token, onSaved],
  );

  return (
    <div className="space-y-6">
      <Section title="Workspace Security">
        <div className="rounded-lg border border-border bg-muted/30 p-4 space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-muted-foreground text-xs">Restrict to workspace</span>
            <span className="text-xs">{advanced.restrict_to_workspace ? "Yes" : "No"}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground text-xs">Sandbox</span>
            <span className="text-xs">{advanced.workspace_sandbox.level}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground text-xs">Summary</span>
            <span className="text-xs max-w-64 text-right">{advanced.workspace_sandbox.summary}</span>
          </div>
        </div>
      </Section>
      <Section title="WebUI Access Mode">
        <SettingRow
          label="Default access mode"
          description="Restricts which workspace directories the agent can access"
        >
          <div className="flex gap-1">
            {(["default", "full"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                disabled={saving}
                className={cn(
                  "rounded-md border px-3 py-1 text-xs font-medium capitalize transition-colors",
                  advanced.webui_default_access_mode === mode
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-border bg-background text-muted-foreground hover:border-primary/50",
                )}
                onClick={() => setAccessMode(mode)}
              >
                {mode}
              </button>
            ))}
          </div>
        </SettingRow>
        {saved ? (
          <div className="flex items-center gap-1 text-xs text-green-600">
            <Check className="h-3 w-3" /> Saved
          </div>
        ) : null}
      </Section>
      <Section title="Counts">
        <div className="rounded-lg border border-border bg-muted/30 p-4 space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-muted-foreground text-xs">MCP Servers</span>
            <span className="text-xs">{advanced.mcp_server_count}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground text-xs">SSRF Whitelist</span>
            <span className="text-xs">{advanced.ssrf_whitelist_count}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground text-xs">Exec</span>
            <span className="text-xs">
              {advanced.exec_enabled ? `enabled${advanced.exec_sandbox ? ` (${advanced.exec_sandbox})` : ""}` : "disabled"}
            </span>
          </div>
        </div>
      </Section>
    </div>
  );
}

function AppearancePanel() {
  return (
    <div className="space-y-4 text-sm text-muted-foreground">
      <p>Theme and appearance preferences are managed via the toolbar buttons.</p>
    </div>
  );
}

export default function SettingsView({ onBack, initialSection = "overview" }: SettingsViewProps) {
  const { token } = useClient();
  const [section, setSection] = useState<SettingsSectionKey>(initialSection);
  const [settings, setSettings] = useState<SettingsPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetchSettings(token, "")
      .then(setSettings)
      .catch((err) => setError(String(err)))
      .finally(() => setLoading(false));
  }, [token]);

  const handleSaved = useCallback((payload: SettingsPayload) => {
    setSettings(payload);
  }, []);

  const sections: SettingsSectionKey[] = [
    "overview",
    "models",
    "providers",
    "browser",
    "image",
    "runtime",
    "advanced",
  ];

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-border px-4 py-3">
        {onBack ? (
          <button
            type="button"
            onClick={onBack}
            className="text-muted-foreground hover:text-foreground"
            aria-label="Back"
          >
            <ChevronLeft className="h-5 w-5" />
          </button>
        ) : null}
        <h2 className="text-sm font-semibold">Settings</h2>
      </div>

      {/* Body */}
      <div className="flex min-h-0 flex-1 overflow-hidden">
        {/* Sidebar nav */}
        <nav className="w-48 shrink-0 overflow-y-auto border-r border-border py-3">
          {sections.map((s) => {
            const Icon = SECTION_ICONS[s];
            return (
              <button
                key={s}
                type="button"
                onClick={() => setSection(s)}
                className={cn(
                  "flex w-full items-center gap-2.5 px-4 py-2 text-sm transition-colors",
                  section === s
                    ? "bg-accent text-accent-foreground font-medium"
                    : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
                )}
              >
                <Icon className="h-4 w-4 shrink-0" />
                {SECTION_LABELS[s]}
              </button>
            );
          })}
        </nav>

        {/* Content */}
        <div className="min-w-0 flex-1 overflow-y-auto p-6">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : error ? (
            <div className="rounded-md border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
              {error}
            </div>
          ) : settings ? (
            <>
              {section === "overview" && <OverviewPanel settings={settings} />}
              {section === "appearance" && <AppearancePanel />}
              {section === "models" && (
                <ModelsPanel settings={settings} onSaved={handleSaved} />
              )}
              {section === "providers" && (
                <ProvidersPanel settings={settings} onSaved={handleSaved} />
              )}
              {section === "browser" && (
                <WebSearchPanel settings={settings} onSaved={handleSaved} />
              )}
              {section === "image" && (
                <div className="text-sm text-muted-foreground">
                  Image generation settings (provider, model) can be configured here.
                  <div className="mt-3 rounded-lg border border-border bg-muted/30 p-4 space-y-2 text-sm">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground text-xs">Enabled</span>
                      <span className="text-xs">{settings.image_generation.enabled ? "Yes" : "No"}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground text-xs">Provider</span>
                      <span className="text-xs font-mono">{settings.image_generation.provider}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground text-xs">Model</span>
                      <span className="text-xs font-mono">{settings.image_generation.model}</span>
                    </div>
                  </div>
                </div>
              )}
              {section === "runtime" && <RuntimePanel settings={settings} />}
              {section === "advanced" && (
                <AdvancedPanel settings={settings} onSaved={handleSaved} />
              )}
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
