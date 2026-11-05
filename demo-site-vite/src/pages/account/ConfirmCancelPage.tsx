import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useDarkPatternMode } from "@/context/DarkPatternModeContext";

// CCPA category: Interface Interference (second confirmation screen)
//
// confirmCancel navigates to /account/subscription/final-confirm instead of
// cancelling directly -- the maze has a third screen now (the late fee
// disclosure + the dead unsubscribe control), so the actual
// cancelSubscription() call moved to FinalConfirmPage.tsx. The buttons
// below (class/text/data-pattern) are unchanged from before, so this stays
// exactly the same asymmetry pair asymmetry.py already scores correctly.
export default function ConfirmCancelPage() {
  const navigate = useNavigate();
  const { darkPatternsEnabled } = useDarkPatternMode();

  useEffect(() => {
    if (!darkPatternsEnabled) {
      navigate("/account/subscription", { replace: true });
    }
  }, [darkPatternsEnabled, navigate]);

  const confirmCancel = () => {
    navigate("/account/subscription/final-confirm");
  };

  if (!darkPatternsEnabled) return null;

  return (
    <div className="mx-auto max-w-lg px-6 py-14 text-center">
      <h1 className="text-2xl font-semibold text-brand-ink">Are you sure?</h1>
      <p className="mt-3 text-brand-muted">
        You'll lose priority support, extended warranty, and member pricing immediately.
      </p>

      <button
        type="button"
        onClick={() => navigate("/account")}
        className="btn-keep-subscription mt-8 w-full rounded-xl bg-brand-accent px-6 py-4 text-lg font-bold text-white shadow-lg shadow-brand-accent/30 hover:bg-brand-accent-dark"
        data-pattern="interface_interference"
      >
        Keep my membership
      </button>

      <button
        type="button"
        onClick={confirmCancel}
        className="btn-cancel-link mt-6 text-[11px] text-brand-muted/60 underline"
        data-pattern="interface_interference"
      >
        yes, cancel my membership
      </button>
    </div>
  );
}
