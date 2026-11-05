const STEPS = [
  { key: "shipping", label: "Shipping" },
  { key: "payment", label: "Payment" },
  { key: "review", label: "Review" },
] as const;

export function CheckoutSteps({ current }: { current: (typeof STEPS)[number]["key"] }) {
  const currentIndex = STEPS.findIndex((step) => step.key === current);

  return (
    <ol className="mb-8 flex items-center gap-3 text-sm">
      {STEPS.map((step, index) => {
        const isActive = index === currentIndex;
        const isDone = index < currentIndex;
        return (
          <li key={step.key} className="flex items-center gap-3">
            <span
              className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold ${
                isActive
                  ? "bg-brand-ink text-white"
                  : isDone
                    ? "bg-brand-accent/20 text-brand-accent-dark"
                    : "bg-brand-border text-brand-muted"
              }`}
            >
              {index + 1}
            </span>
            <span className={isActive ? "font-semibold text-brand-ink" : "text-brand-muted"}>
              {step.label}
            </span>
            {index < STEPS.length - 1 && <span className="ml-2 h-px w-8 bg-brand-border" />}
          </li>
        );
      })}
    </ol>
  );
}
