"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAccount } from "@/context/AccountContext";
import { useDarkPatternMode } from "@/context/DarkPatternModeContext";

// CCPA category: Interface Interference (second confirmation screen)
export default function ConfirmCancelPage() {
  const router = useRouter();
  const { cancelSubscription } = useAccount();
  const { darkPatternsEnabled } = useDarkPatternMode();

  useEffect(() => {
    if (!darkPatternsEnabled) {
      router.replace("/account/subscription");
    }
  }, [darkPatternsEnabled, router]);

  const confirmCancel = () => {
    cancelSubscription();
    router.push("/account/subscription/cancelled");
  };

  if (!darkPatternsEnabled) return null;

  return (
    <div className="mx-auto max-w-lg px-6 py-14 text-center">
      <h1 className="text-2xl font-semibold text-brand-ink">Are you sure?</h1>
      <p className="mt-3 text-brand-muted">
        You&apos;ll lose priority support, extended warranty, and member pricing immediately.
      </p>

      <button
        type="button"
        onClick={() => router.push("/account")}
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
