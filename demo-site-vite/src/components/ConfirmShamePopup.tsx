
import { useEffect, useState } from "react";
import { useDarkPatternMode } from "@/context/DarkPatternModeContext";

// CCPA category: Confirm Shaming
// Trigger: a newsletter popup appears shortly after the first page load. The
// decline action is worded to guilt the user for not accepting, rather than
// a neutral "no thanks". Shown once per session (a genuinely reappearing
// popup is the separate Nagging pattern in NaggingModal.tsx).
const SESSION_KEY = "auralis-demo-confirm-shame-dismissed";

export function ConfirmShamePopup() {
  const { darkPatternsEnabled } = useDarkPatternMode();
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (window.sessionStorage.getItem(SESSION_KEY) === "true") return;
    const timer = setTimeout(() => setVisible(true), 1400);
    return () => clearTimeout(timer);
  }, []);

  const dismiss = () => {
    setVisible(false);
    window.sessionStorage.setItem(SESSION_KEY, "true");
  };

  if (!visible) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-4 sm:items-center">
      <div
        className="newsletter-popup w-full max-w-md rounded-2xl border border-brand-border bg-brand-card p-6 shadow-2xl"
        data-pattern="confirm_shaming"
      >
        <h2 className="text-lg font-semibold text-brand-ink">Join the Auralis Inner Circle</h2>
        <p className="mt-2 text-sm text-brand-muted">
          Get 15% off your first order, plus early access to new drops and members-only pricing.
        </p>
        <input
          type="email"
          placeholder="you@example.com"
          className="mt-4 w-full rounded-lg border border-brand-border px-3 py-2 text-sm focus:border-brand-accent focus:outline-none"
        />
        <button
          type="button"
          onClick={dismiss}
          className="mt-3 w-full rounded-lg bg-brand-ink px-4 py-2.5 text-sm font-semibold text-white hover:bg-black"
        >
          Yes, sign me up
        </button>
        <button type="button" onClick={dismiss} className="mt-3 w-full text-center text-xs text-brand-muted underline">
          {darkPatternsEnabled ? "No thanks, I don't like saving money" : "No thanks"}
        </button>
      </div>
    </div>
  );
}
