import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAccount } from "@/context/AccountContext";
import { useDarkPatternMode } from "@/context/DarkPatternModeContext";

const CANCELLATION_FEE = 199;

// CCPA category: Interface Interference (forced interstitial #2 of the
// cancellation maze) + Information Hiding (the cancellation fee below is
// disclosed here for the FIRST time in the flow -- SubscriptionPage,
// RetentionOfferPage, ConfirmCancelPage, and ExitSurveyPage never mention
// it) + Deception (the "Unsubscribe from marketing emails" button below:
// clicking it fires no network request, no client-side route change, and
// no AccountContext state change -- only a local, cosmetic success message).
//
// role="dialog" makes this register as a second, independent
// forced_interstitial (see ExitSurveyPage.tsx's identical note) -- the
// intervening confirm-cancel screen (no dialog role) resets
// signals/path_deviation.py's previous_had_interstitial to false first, so
// this is a genuinely NEW blocking screen, not a continuation of the first.
export default function FinalConfirmPage() {
  const navigate = useNavigate();
  const { cancelSubscription } = useAccount();
  const { darkPatternsEnabled } = useDarkPatternMode();
  const [showFakeUnsubscribed, setShowFakeUnsubscribed] = useState(false);

  useEffect(() => {
    if (!darkPatternsEnabled) {
      navigate("/account/subscription", { replace: true });
    }
  }, [darkPatternsEnabled, navigate]);

  const confirmCancellation = () => {
    cancelSubscription();
    navigate("/account/subscription/cancelled");
  };

  // Deliberately dead: no network call, no navigate(), no AccountContext
  // mutation -- only a local, in-page cosmetic success message. This is
  // the control deception.py's stated_vs_actual check is meant to catch:
  // success shown, nothing actually happened.
  const handleFakeUnsubscribe = () => {
    setShowFakeUnsubscribed(true);
  };

  if (!darkPatternsEnabled) return null;

  return (
    <div role="dialog" aria-label="Final cancellation confirmation" className="mx-auto max-w-lg px-6 py-14 text-center">
      <h1 className="text-2xl font-semibold text-brand-ink">One last thing</h1>
      {/* data-disclosure: opts this element into signals/ui_regions.py's
          disclosure-tagging pass, since recorder/evidence_probe.py's
          interactive-elements-only capture never sees plain text -- see
          that module's docstring. Not a new fee, just making the
          already-rendered one referenceable by a real selector. */}
      <p className="mt-3 text-brand-muted" data-disclosure="cancellation-fee">
        Cancelling now will incur a ₹{CANCELLATION_FEE} early cancellation fee, charged to your card on
        file within 24 hours.
      </p>

      <div className="mt-8 rounded-xl border border-brand-border px-5 py-4 text-left">
        <p className="text-sm text-brand-ink">Also unsubscribe me from marketing emails</p>
        <button
          type="button"
          onClick={handleFakeUnsubscribe}
          className="fake-unsubscribe-btn mt-2 rounded-full border border-brand-border px-4 py-1.5 text-xs font-semibold text-brand-ink hover:bg-brand-paper"
        >
          Unsubscribe from marketing emails
        </button>
        {showFakeUnsubscribed && (
          <p className="mt-2 text-xs font-medium text-brand-accent-dark">
            You've been unsubscribed from marketing emails.
          </p>
        )}
      </div>

      <button
        type="button"
        onClick={confirmCancellation}
        className="mt-6 w-full rounded-full bg-brand-danger px-6 py-3 text-sm font-semibold text-white hover:bg-brand-danger-dark"
      >
        Confirm cancellation
      </button>
    </div>
  );
}
