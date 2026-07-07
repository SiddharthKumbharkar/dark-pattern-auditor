"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAccount } from "@/context/AccountContext";
import { useDarkPatternMode } from "@/context/DarkPatternModeContext";

// CCPA category: Subscription Trap
// Trigger: when a trial/subscription is active and dark patterns are ON,
// the cancellation entry point is a small, plain-text link buried at the
// bottom of the page ("Manage membership") rather than a clearly labeled
// "Cancel" button placed with the rest of the subscription details.
export default function AccountPage() {
  const { status } = useAccount();
  const { darkPatternsEnabled } = useDarkPatternMode();

  // Date.now() is impure to call during render (and would differ between
  // the server render and the client), so it's computed client-side after
  // mount instead.
  const [nextBillingDate, setNextBillingDate] = useState<string | null>(null);
  useEffect(() => {
    const formatted = new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toLocaleDateString("en-IN", {
      day: "numeric",
      month: "long",
      year: "numeric",
    });
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setNextBillingDate(formatted);
  }, []);

  return (
    <div className="mx-auto max-w-2xl px-6 py-14">
      <h1 className="text-2xl font-semibold text-brand-ink">Account</h1>

      <div className="mt-6 rounded-2xl border border-brand-border bg-brand-card p-6">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-brand-muted">
          Auralis+ Membership
        </h2>

        {status === "none" && (
          <div className="mt-3">
            <p className="text-sm text-brand-muted">You don&apos;t have an active membership.</p>
            <Link
              href="/trial"
              className="mt-4 inline-block rounded-full bg-brand-ink px-5 py-2.5 text-sm font-semibold text-white hover:bg-black"
            >
              Start free trial
            </Link>
          </div>
        )}

        {(status === "trial_active" || status === "active") && (
          <div className="mt-3">
            <p className="text-sm font-medium text-brand-success">
              {status === "trial_active" ? "Free trial active" : "Active"}
            </p>
            <p className="mt-1 text-sm text-brand-muted">
              Next billing date: {nextBillingDate ?? "—"} — ₹499/month
            </p>

            {!darkPatternsEnabled && (
              <Link
                href="/account/subscription"
                className="mt-4 inline-block rounded-full border border-brand-danger/40 px-5 py-2.5 text-sm font-semibold text-brand-danger-dark hover:bg-brand-danger/5"
              >
                Cancel membership
              </Link>
            )}
          </div>
        )}

        {status === "cancelled" && (
          <div className="mt-3">
            <p className="text-sm text-brand-muted">Your membership has been cancelled.</p>
            <Link href="/trial" className="mt-4 inline-block text-sm font-medium text-brand-accent-dark underline">
              Start a new trial
            </Link>
          </div>
        )}
      </div>

      {darkPatternsEnabled && (status === "trial_active" || status === "active") && (
        <div className="mt-10 text-center">
          <Link href="/account/subscription" className="text-xs text-brand-muted/70 underline">
            Manage membership
          </Link>
        </div>
      )}
    </div>
  );
}
