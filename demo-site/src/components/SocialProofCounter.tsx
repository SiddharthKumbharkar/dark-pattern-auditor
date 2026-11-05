"use client";

import { useEffect, useState } from "react";
import { useDarkPatternMode } from "@/context/DarkPatternModeContext";

// CCPA category: False Urgency (fabricated demand signal)
// Also feeds the pipeline's dedicated extract_social_proof_claims() signal.
// Trigger: two "live activity" counters that tick up on a timer with no
// backing data at all -- purely random increments to simulate demand.
function randomStep(min: number, max: number) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

export function SocialProofCounter() {
  const { darkPatternsEnabled } = useDarkPatternMode();
  const [viewing, setViewing] = useState(38);
  const [boughtThisWeek, setBoughtThisWeek] = useState(213);

  useEffect(() => {
    if (!darkPatternsEnabled) return;

    const viewingInterval = setInterval(() => {
      setViewing((prev) => {
        const next = prev + randomStep(-3, 4);
        return Math.min(89, Math.max(14, next));
      });
    }, 4000);

    const boughtInterval = setInterval(() => {
      setBoughtThisWeek((prev) => prev + randomStep(1, 3));
    }, 12000);

    return () => {
      clearInterval(viewingInterval);
      clearInterval(boughtInterval);
    };
  }, [darkPatternsEnabled]);

  if (!darkPatternsEnabled) return null;

  return (
    <div className="social-proof-counter flex flex-col gap-1 text-sm text-brand-muted" data-pattern="false_urgency_social_proof">
      <p>{viewing} people are viewing this right now</p>
      <p>{boughtThisWeek} people bought this in the last 7 days</p>
    </div>
  );
}
