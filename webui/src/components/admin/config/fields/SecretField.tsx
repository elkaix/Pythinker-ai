import { Button } from "@/components/ui/button";

export type SecretFieldProps = {
  label: string;
  canonicalPath: string;
  hint?: string;
  onReplaceSecret: (canonicalPath: string) => void;
};

export function SecretField({ label, canonicalPath, hint, onReplaceSecret }: SecretFieldProps) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-border p-3">
      <div className="min-w-0">
        <div className="text-sm font-medium text-foreground">{label}</div>
        {hint ? (
          <div
            className="font-mono text-xs text-muted-foreground"
            data-testid="secret-hint"
            title="Masked preview of the live secret"
          >
            {hint}
          </div>
        ) : (
          <div className="text-xs text-muted-foreground">Secret value hidden</div>
        )}
      </div>
      <Button onClick={() => onReplaceSecret(canonicalPath)} type="button" variant="secondary">
        Replace secret
      </Button>
    </div>
  );
}
