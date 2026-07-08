import { Link } from "react-router-dom";
import { useDarkPatternMode } from "@/context/DarkPatternModeContext";
import { useCart } from "@/context/CartContext";

export function Header() {
  const { darkPatternsEnabled, toggle } = useDarkPatternMode();
  const { lines } = useCart();
  const itemCount = lines.reduce((sum, line) => sum + line.quantity, 0);

  return (
    <header className="sticky top-0 z-40 border-b border-brand-border bg-brand-paper/95 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 py-4">
        <Link to="/" className="flex items-center gap-2">
          <span className="text-xl font-semibold tracking-tight text-brand-ink">AURALIS</span>
        </Link>

        <nav className="hidden items-center gap-6 text-sm font-medium text-brand-ink/80 md:flex">
          <Link to="/" className="hover:text-brand-ink">
            Shop
          </Link>
          <Link to="/trial" className="hover:text-brand-ink">
            Auralis+ Membership
          </Link>
          <Link to="/account" className="hover:text-brand-ink">
            Account
          </Link>
        </nav>

        <div className="flex items-center gap-4">
          <button
            type="button"
            onClick={toggle}
            aria-pressed={darkPatternsEnabled}
            className={`group flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors ${
              darkPatternsEnabled
                ? "border-brand-danger/30 bg-brand-danger/10 text-brand-danger-dark"
                : "border-brand-success/30 bg-brand-success/10 text-brand-success"
            }`}
            title="Toggle dark patterns for this demo"
          >
            <span
              className={`h-2 w-2 rounded-full ${
                darkPatternsEnabled ? "bg-brand-danger" : "bg-brand-success"
              }`}
            />
            Dark Patterns: {darkPatternsEnabled ? "ON" : "OFF"}
          </button>

          <Link
            to="/cart"
            className="relative flex items-center gap-2 rounded-full border border-brand-border bg-brand-card px-3 py-1.5 text-sm font-medium text-brand-ink hover:border-brand-accent"
          >
            Cart
            {itemCount > 0 && (
              <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-brand-ink px-1 text-xs font-semibold text-white">
                {itemCount}
              </span>
            )}
          </Link>
        </div>
      </div>
    </header>
  );
}
