export function Footer() {
  return (
    <footer className="mt-24 border-t border-brand-border bg-brand-card">
      <div className="mx-auto flex max-w-6xl flex-col gap-2 px-6 py-10 text-sm text-brand-muted">
        <span className="text-base font-semibold text-brand-ink">AURALIS</span>
        <p>Precision audio, designed for everyday listening.</p>
        <p className="mt-4 text-xs text-brand-muted/80">
          This is a demonstration storefront built to showcase dark-pattern detection tooling. No
          real payments are processed.
        </p>
      </div>
    </footer>
  );
}
