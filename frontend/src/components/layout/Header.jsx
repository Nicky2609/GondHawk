export function Header() {
  return (
    <header className="flex items-center justify-between rounded-2xl border border-[var(--panel-border)] bg-[var(--panel)] px-5 py-4">
      <div className="flex items-center gap-2">
        <span className="h-2.5 w-2.5 rounded-full bg-[var(--accent)]" />
        <h1 className="text-lg">GondHawk</h1>
      </div>
    </header>
  );
}