export function Header() {
  return (
    <header className="flex items-center justify-between rounded-2xl border border-[var(--panel-border)] bg-[var(--panel)] px-5 py-4">
      <div className="flex items-center gap-2">
        <span className="h-2.5 w-2.5 rounded-full bg-[var(--accent)]" />
        <h1 className="text-lg">Góndola Inteligente</h1>
      </div>
      <span className="flex items-center gap-1.5 rounded-full border border-[var(--panel-border)] px-3 py-1 text-xs text-[var(--ink-muted)]">
        <span className="h-1.5 w-1.5 rounded-full bg-[var(--accent)]" /> live
      </span>
    </header>
  );
}