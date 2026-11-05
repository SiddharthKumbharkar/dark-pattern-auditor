"use client";

import { createContext, useContext, useEffect, useState } from "react";

export type SubscriptionStatus = "none" | "trial_active" | "active" | "cancelled";

type AccountContextValue = {
  status: SubscriptionStatus;
  startFreeTrial: () => void;
  cancelSubscription: () => void;
  resetDemo: () => void;
};

const AccountContext = createContext<AccountContextValue | null>(null);
const STORAGE_KEY = "auralis-demo-account-v1";

export function AccountProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<SubscriptionStatus>("none");
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    const stored = window.sessionStorage.getItem(STORAGE_KEY) as SubscriptionStatus | null;
    // Deliberately deferred to an effect, not a lazy useState initializer
    // -- see the identical note in DarkPatternModeContext.tsx.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (stored) setStatus(stored);
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    window.sessionStorage.setItem(STORAGE_KEY, status);
  }, [hydrated, status]);

  return (
    <AccountContext.Provider
      value={{
        status,
        startFreeTrial: () => setStatus("trial_active"),
        cancelSubscription: () => setStatus("cancelled"),
        resetDemo: () => setStatus("none"),
      }}
    >
      {children}
    </AccountContext.Provider>
  );
}

export function useAccount(): AccountContextValue {
  const ctx = useContext(AccountContext);
  if (!ctx) {
    throw new Error("useAccount must be used within AccountProvider");
  }
  return ctx;
}
