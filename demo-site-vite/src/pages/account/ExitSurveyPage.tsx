import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useDarkPatternMode } from "@/context/DarkPatternModeContext";

// CCPA category: Interface Interference (forced interstitial #1 of the
// cancellation maze) + Complexity (excessive option count / double-negative
// wording) + Covertness (the camouflaged, pre-checked win-back opt-in below).
//
// role="dialog" makes this register as a forced_interstitial in
// signals/path_deviation.py's has_interstitial() check -- a genuinely
// blocking screen between "no thanks, cancel anyway" and the next step,
// not a cosmetic label.
const REASONS = [
  "Too expensive",
  "I don't use it enough",
  "Missing features I need",
  "Found a better alternative",
  "Technical issues / bugs",
  "Poor customer support",
  "Moving or relocating",
  "Financial reasons",
  "Switching to a competitor",
  "No longer needed",
  "Privacy concerns",
  "Billing was confusing",
  "Difficult to use",
  "Other",
];

export default function ExitSurveyPage() {
  const navigate = useNavigate();
  const { darkPatternsEnabled } = useDarkPatternMode();
  const [winbackOptIn, setWinbackOptIn] = useState(true);

  useEffect(() => {
    if (!darkPatternsEnabled) {
      navigate("/account/subscription", { replace: true });
    }
  }, [darkPatternsEnabled, navigate]);

  if (!darkPatternsEnabled) return null;

  return (
    <div role="dialog" aria-label="Cancellation exit survey" className="mx-auto max-w-lg px-6 py-14">
      <h1 className="text-2xl font-semibold text-brand-ink">Before you finish — why are you leaving Auralis+?</h1>
      <p className="mt-2 text-sm text-brand-muted">Select every reason that applies to your subscription cancellation.</p>

      <div className="mt-6 grid grid-cols-1 gap-2">
        {REASONS.map((reason) => (
          <label key={reason} className="flex items-center gap-2 text-sm text-brand-ink">
            <input type="checkbox" className="exit-survey-reason" />
            {reason}
          </label>
        ))}
      </div>

      <label className="mt-6 flex items-start gap-2 text-[11px] leading-snug text-gray-300">
        <input
          type="checkbox"
          checked={winbackOptIn}
          onChange={(e) => setWinbackOptIn(e.target.checked)}
          className="winback-optin mt-0.5"
        />
        <span>
          Uncheck this box if you do not want to not receive occasional win-back offers and account
          updates after your subscription ends.
        </span>
      </label>

      <button
        type="button"
        onClick={() => navigate("/account/subscription/confirm-cancel")}
        className="mt-8 w-full rounded-full bg-brand-ink px-6 py-3 text-sm font-semibold text-white hover:bg-black"
      >
        Continue
      </button>
    </div>
  );
}
