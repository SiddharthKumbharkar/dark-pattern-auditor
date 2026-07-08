import { useNavigate } from "react-router-dom";
import { useAccount } from "@/context/AccountContext";
import { useDarkPatternMode } from "@/context/DarkPatternModeContext";

const MONTHLY_PRICE = 499;

// CCPA category: Subscription Trap (Forced Continuity)
// Trigger: the primary CTA is framed purely as "start a free trial", while
// the real action is enrolling in an auto-renewing paid subscription. The
// billing disclosure exists (it isn't fraudulent), but is pushed into small,
// low-contrast fine print when dark patterns are enabled.
export default function TrialPage() {
  const navigate = useNavigate();
  const { startFreeTrial } = useAccount();
  const { darkPatternsEnabled } = useDarkPatternMode();

  const handleStart = () => {
    startFreeTrial();
    navigate("/account");
  };

  return (
    <div className="mx-auto max-w-lg px-6 py-14">
      <h1 className="text-2xl font-semibold text-brand-ink">Auralis+ Membership</h1>
      <p className="mt-2 text-brand-muted">
        Priority support, extended warranty on every order, and member-only pricing.
      </p>

      <div className="mt-6 grid grid-cols-1 gap-4">
        <input placeholder="Email address" className="rounded-lg border border-brand-border px-3 py-2 text-sm" />
        <input placeholder="Card number" className="rounded-lg border border-brand-border px-3 py-2 text-sm" />
        <div className="grid grid-cols-2 gap-4">
          <input placeholder="MM / YY" className="rounded-lg border border-brand-border px-3 py-2 text-sm" />
          <input placeholder="CVV" className="rounded-lg border border-brand-border px-3 py-2 text-sm" />
        </div>
      </div>

      {!darkPatternsEnabled && (
        <label className="mt-4 flex items-start gap-2 text-sm text-brand-ink">
          <input type="checkbox" className="mt-1" />
          <span>
            I understand that after my 30-day free trial, I will be charged ₹{MONTHLY_PRICE}/month
            until I cancel.
          </span>
        </label>
      )}

      <button
        type="button"
        onClick={handleStart}
        className="mt-6 w-full rounded-full bg-brand-ink px-6 py-3 text-sm font-semibold text-white hover:bg-black"
      >
        {darkPatternsEnabled ? "Start My Free Trial" : `Start Free Trial — ₹${MONTHLY_PRICE}/month after 30 days`}
      </button>

      <p
        className={
          darkPatternsEnabled
            ? "mt-3 max-w-sm text-[11px] leading-snug text-brand-muted/70"
            : "mt-3 text-sm text-brand-muted"
        }
      >
        After your 30-day trial, your card will be automatically charged ₹{MONTHLY_PRICE}/month
        until you cancel. Cancel anytime from Account settings.
      </p>
    </div>
  );
}
