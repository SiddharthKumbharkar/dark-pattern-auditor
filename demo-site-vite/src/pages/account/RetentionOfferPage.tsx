import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useDarkPatternMode } from "@/context/DarkPatternModeContext";

// CCPA category: Interface Interference
// Trigger: the "keep" action is a large, high-contrast, shadowed button;
// the actual cancel action is a barely-visible small text link -- the same
// visual convention as .btn-keep / .btn-remove already used for the
// warranty upsell in test_sites/shopdemo/cart.html.
export default function RetentionOfferPage() {
  const navigate = useNavigate();
  const { darkPatternsEnabled } = useDarkPatternMode();

  useEffect(() => {
    if (!darkPatternsEnabled) {
      navigate("/account/subscription", { replace: true });
    }
  }, [darkPatternsEnabled, navigate]);

  if (!darkPatternsEnabled) return null;

  return (
    <div className="mx-auto max-w-lg px-6 py-14 text-center">
      <h1 className="text-2xl font-semibold text-brand-ink">Wait — before you go</h1>
      <p className="mt-3 text-brand-muted">
        Stay with Auralis+ and get 50% off your next 3 months. That's just ₹249.50/month.
      </p>

      <button
        type="button"
        onClick={() => navigate("/account")}
        className="btn-keep-subscription mt-8 w-full rounded-xl bg-brand-accent px-6 py-4 text-lg font-bold text-white shadow-lg shadow-brand-accent/30 hover:bg-brand-accent-dark"
        data-pattern="interface_interference"
      >
        Yes, keep my 50% off plan
      </button>

      <button
        type="button"
        onClick={() => navigate("/account/subscription/confirm-cancel")}
        className="btn-cancel-link mt-6 text-[11px] text-brand-muted/60 underline"
        data-pattern="interface_interference"
      >
        no thanks, cancel anyway
      </button>
    </div>
  );
}
