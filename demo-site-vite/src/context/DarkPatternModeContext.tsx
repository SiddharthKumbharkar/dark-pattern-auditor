
import { createContext, useContext, useEffect, useState } from "react";

type DarkPatternModeContextValue = {
  darkPatternsEnabled: boolean;
  toggle: () => void;
  setDarkPatternsEnabled: (value: boolean) => void;
};

const DarkPatternModeContext = createContext<DarkPatternModeContextValue | null>(null);
const STORAGE_KEY = "auralis-demo-dark-patterns-enabled";

// Defaults ON so the dark-pattern flow is what a fresh recorder session sees
// unless the presenter has already flipped the toggle.
export function DarkPatternModeProvider({ children }: { children: React.ReactNode }) {
  const [darkPatternsEnabled, setDarkPatternsEnabledState] = useState(true);

  useEffect(() => {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored !== null) {
      // Deliberately deferred to an effect (not a lazy useState initializer):
      // this value affects server-rendered markup, and the server has no
      // localStorage, so the first client render must match the server's
      // default before upgrading -- doing this synchronously would cause a
      // hydration mismatch instead.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setDarkPatternsEnabledState(stored === "true");
    }
  }, []);

  const setDarkPatternsEnabled = (value: boolean) => {
    setDarkPatternsEnabledState(value);
    window.localStorage.setItem(STORAGE_KEY, String(value));
  };

  return (
    <DarkPatternModeContext.Provider
      value={{
        darkPatternsEnabled,
        toggle: () => setDarkPatternsEnabled(!darkPatternsEnabled),
        setDarkPatternsEnabled,
      }}
    >
      {children}
    </DarkPatternModeContext.Provider>
  );
}

export function useDarkPatternMode(): DarkPatternModeContextValue {
  const ctx = useContext(DarkPatternModeContext);
  if (!ctx) {
    throw new Error("useDarkPatternMode must be used within DarkPatternModeProvider");
  }
  return ctx;
}
