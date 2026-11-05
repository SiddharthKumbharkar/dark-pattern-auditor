"use client";

import { useEffect, useState } from "react";
import { useDarkPatternMode } from "@/context/DarkPatternModeContext";

// CCPA category: False Urgency
// Trigger: a countdown timer that always targets "now + fixed duration" on
// mount, so it silently resets to the same ~15 minutes on every page
// refresh instead of counting down to a real deadline.
const DURATION_MS = 15 * 60 * 1000;

function formatRemaining(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return [hours, minutes, seconds].map((n) => String(n).padStart(2, "0")).join(":");
}

export function CountdownTimer() {
  const { darkPatternsEnabled } = useDarkPatternMode();
  const [deadline] = useState(() => Date.now() + DURATION_MS);
  const [remainingMs, setRemainingMs] = useState(DURATION_MS);

  useEffect(() => {
    const interval = setInterval(() => {
      setRemainingMs(Math.max(0, deadline - Date.now()));
    }, 1000);
    return () => clearInterval(interval);
  }, [deadline]);

  if (!darkPatternsEnabled) {
    return <p className="text-sm text-brand-muted">Usually ships within 2 business days.</p>;
  }

  return (
    <div
      className="countdown-timer inline-flex items-center gap-2 rounded-lg bg-brand-danger/10 px-3 py-2 text-sm font-semibold text-brand-danger-dark"
      data-countdown="true"
    >
      <span>Hurry, this price ends in {formatRemaining(remainingMs)} — sale price reverts after that.</span>
    </div>
  );
}
