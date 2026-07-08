import type { ProductVisualKind } from "@/data/products";

function HeadphonesArt() {
  return (
    <svg viewBox="0 0 200 200" className="h-full w-full" aria-hidden="true">
      <path
        d="M46 96 V80 a54 54 0 0 1 108 0 V96"
        fill="none"
        stroke="currentColor"
        strokeWidth="6"
        strokeLinecap="round"
      />
      <rect x="30" y="92" width="24" height="46" rx="12" fill="currentColor" opacity="0.14" />
      <rect
        x="30"
        y="92"
        width="24"
        height="46"
        rx="12"
        fill="none"
        stroke="currentColor"
        strokeWidth="5"
      />
      <rect x="146" y="92" width="24" height="46" rx="12" fill="currentColor" opacity="0.14" />
      <rect
        x="146"
        y="92"
        width="24"
        height="46"
        rx="12"
        fill="none"
        stroke="currentColor"
        strokeWidth="5"
      />
    </svg>
  );
}

function EarbudsArt() {
  return (
    <svg viewBox="0 0 200 200" className="h-full w-full" aria-hidden="true">
      {/* charging case */}
      <rect x="60" y="122" width="80" height="42" rx="16" fill="currentColor" opacity="0.12" />
      <rect
        x="60"
        y="122"
        width="80"
        height="42"
        rx="16"
        fill="none"
        stroke="currentColor"
        strokeWidth="5"
      />
      <line x1="100" y1="122" x2="100" y2="164" stroke="currentColor" strokeWidth="3" opacity="0.4" />

      {/* two standalone earbuds (head + stem), not connected to each other */}
      <g transform="translate(72, 46) rotate(-8)">
        <ellipse cx="0" cy="0" rx="16" ry="19" fill="currentColor" opacity="0.14" />
        <ellipse cx="0" cy="0" rx="16" ry="19" fill="none" stroke="currentColor" strokeWidth="5" />
        <rect x="-4" y="16" width="8" height="26" rx="4" fill="currentColor" opacity="0.14" />
        <rect x="-4" y="16" width="8" height="26" rx="4" fill="none" stroke="currentColor" strokeWidth="4" />
      </g>
      <g transform="translate(128, 46) rotate(8)">
        <ellipse cx="0" cy="0" rx="16" ry="19" fill="currentColor" opacity="0.14" />
        <ellipse cx="0" cy="0" rx="16" ry="19" fill="none" stroke="currentColor" strokeWidth="5" />
        <rect x="-4" y="16" width="8" height="26" rx="4" fill="currentColor" opacity="0.14" />
        <rect x="-4" y="16" width="8" height="26" rx="4" fill="none" stroke="currentColor" strokeWidth="4" />
      </g>
    </svg>
  );
}

function CaseArt() {
  return (
    <svg viewBox="0 0 200 200" className="h-full w-full" aria-hidden="true">
      <rect x="52" y="46" width="96" height="108" rx="18" fill="currentColor" opacity="0.12" />
      <rect
        x="52"
        y="46"
        width="96"
        height="108"
        rx="18"
        fill="none"
        stroke="currentColor"
        strokeWidth="5"
      />
      <line x1="52" y1="96" x2="148" y2="96" stroke="currentColor" strokeWidth="4" opacity="0.5" />
      <path
        d="M84 46 v-8 a16 16 0 0 1 32 0 v8"
        fill="none"
        stroke="currentColor"
        strokeWidth="5"
        strokeLinecap="round"
      />
    </svg>
  );
}

const ART: Record<ProductVisualKind, () => React.JSX.Element> = {
  headphones: HeadphonesArt,
  earbuds: EarbudsArt,
  case: CaseArt,
};

export function ProductVisual({
  kind,
  className = "",
}: {
  kind: ProductVisualKind;
  className?: string;
}) {
  const Art = ART[kind];
  return (
    <div
      className={`relative flex items-center justify-center overflow-hidden rounded-2xl bg-gradient-to-br from-[#f2ede3] via-[#faf9f6] to-[#ece5d6] text-brand-accent ${className}`}
    >
      <div className="absolute inset-x-8 bottom-6 h-6 rounded-full bg-black/10 blur-lg" />
      <div className="relative h-2/3 w-2/3">
        <Art />
      </div>
    </div>
  );
}
