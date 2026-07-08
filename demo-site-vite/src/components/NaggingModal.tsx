
import { useEffect, useRef, useState } from "react";
import { useDarkPatternMode } from "@/context/DarkPatternModeContext";

// CCPA category: Nagging
// Trigger: a permission-request modal that reappears repeatedly after being
// dismissed with "Not now", rather than respecting the user's choice.
const INITIAL_DELAY_MS = 5000;
const REAPPEAR_MS = 22000;
const MAX_APPEARANCES = 5;

export function NaggingModal() {
  const { darkPatternsEnabled } = useDarkPatternMode();
  const [visible, setVisible] = useState(false);
  const appearances = useRef(0);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);

    if (!darkPatternsEnabled) {
      // Resetting visibility in response to the toggle changing, not
      // hydrating from storage, but the same "external system" (a pending
      // setTimeout) makes an effect the right place for this.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setVisible(false);
      return;
    }

    appearances.current = 0;
    timeoutRef.current = setTimeout(() => {
      appearances.current += 1;
      setVisible(true);
    }, INITIAL_DELAY_MS);

    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, [darkPatternsEnabled]);

  const dismiss = () => {
    setVisible(false);
    if (appearances.current < MAX_APPEARANCES) {
      timeoutRef.current = setTimeout(() => {
        appearances.current += 1;
        setVisible(true);
      }, REAPPEAR_MS);
    }
  };

  if (!visible || !darkPatternsEnabled) return null;

  return (
    <div
      className="nagging-modal fixed bottom-6 right-6 z-50 w-full max-w-sm rounded-2xl border border-brand-border bg-brand-card p-5 shadow-2xl"
      data-pattern="nagging"
    >
      <h3 className="text-sm font-semibold text-brand-ink">Turn on notifications?</h3>
      <p className="mt-1.5 text-sm text-brand-muted">
        Get notified about order updates, restocks, and price drops.
      </p>
      <div className="mt-4 flex gap-2">
        <button
          type="button"
          onClick={dismiss}
          className="flex-1 rounded-lg bg-brand-ink px-3 py-2 text-sm font-semibold text-white hover:bg-black"
        >
          Enable
        </button>
        <button
          type="button"
          onClick={dismiss}
          className="flex-1 rounded-lg border border-brand-border px-3 py-2 text-sm font-medium text-brand-muted hover:border-brand-ink"
        >
          Not now
        </button>
      </div>
    </div>
  );
}
