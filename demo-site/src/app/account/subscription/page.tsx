"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAccount } from "@/context/AccountContext";
import { useDarkPatternMode } from "@/context/DarkPatternModeContext";

export default function SubscriptionPage() {
  const router = useRouter();
  const { status, cancelSubscription } = useAccount();
  const { darkPatternsEnabled } = useDarkPatternMode();

  const handleCancelClean = () => {
    cancelSubscription();
    router.push("/account/subscription/cancelled");
  };

  return (
    <div className="mx-auto max-w-lg px-6 py-14">
      <h1 className="text-2xl font-semibold text-brand-ink">Manage membership</h1>
      <p className="mt-2 text-sm text-brand-muted">
        Auralis+ Membership — {status === "trial_active" ? "Free trial active" : "Active"}
      </p>

      <div className="mt-8 flex flex-col gap-3">
        {darkPatternsEnabled ? (
          <Link
            href="/account/subscription/retention-offer"
            className="rounded-full border border-brand-danger/40 px-5 py-2.5 text-center text-sm font-semibold text-brand-danger-dark hover:bg-brand-danger/5"
          >
            Cancel membership
          </Link>
        ) : (
          <button
            type="button"
            onClick={handleCancelClean}
            className="rounded-full border border-brand-danger/40 px-5 py-2.5 text-sm font-semibold text-brand-danger-dark hover:bg-brand-danger/5"
          >
            Cancel membership
          </button>
        )}
        <Link href="/account" className="text-center text-sm text-brand-muted hover:text-brand-ink">
          Back to account
        </Link>
      </div>
    </div>
  );
}
