
import { createContext, useContext, useEffect, useState } from "react";

export const PROTECTION_PLAN_NAME = "Auralis Protection Plan+";
export const PROTECTION_PLAN_PRICE = 399;

export type AddedVia = "explicit" | "auto_added";

export type CartLine = {
  slug: string;
  quantity: number;
};

type CartContextValue = {
  lines: CartLine[];
  protectionPlanSelected: boolean;
  protectionPlanAddedVia: AddedVia | null;
  addToCart: (slug: string, opts?: { withProtectionPlan?: boolean }) => void;
  removeLine: (slug: string) => void;
  setProtectionPlanSelected: (value: boolean, via: AddedVia) => void;
  clearCart: () => void;
};

const CartContext = createContext<CartContextValue | null>(null);
const STORAGE_KEY = "auralis-demo-cart-v1";

export function CartProvider({ children }: { children: React.ReactNode }) {
  const [lines, setLines] = useState<CartLine[]>([]);
  const [protectionPlanSelected, setProtectionPlanSelectedState] = useState(false);
  const [protectionPlanAddedVia, setProtectionPlanAddedVia] = useState<AddedVia | null>(null);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (raw) {
      try {
        const parsed = JSON.parse(raw) as {
          lines?: CartLine[];
          protectionPlanSelected?: boolean;
          protectionPlanAddedVia?: AddedVia | null;
        };
        // Deliberately deferred to an effect, not a lazy useState initializer
        // -- see the identical note in DarkPatternModeContext.tsx.
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setLines(parsed.lines ?? []);
        setProtectionPlanSelectedState(parsed.protectionPlanSelected ?? false);
        setProtectionPlanAddedVia(parsed.protectionPlanAddedVia ?? null);
      } catch {
        // ignore malformed storage
      }
    }
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    window.sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ lines, protectionPlanSelected, protectionPlanAddedVia })
    );
  }, [hydrated, lines, protectionPlanSelected, protectionPlanAddedVia]);

  const addToCart: CartContextValue["addToCart"] = (slug, opts) => {
    setLines((prev) => {
      const existing = prev.find((line) => line.slug === slug);
      if (existing) {
        return prev.map((line) =>
          line.slug === slug ? { ...line, quantity: line.quantity + 1 } : line
        );
      }
      return [...prev, { slug, quantity: 1 }];
    });
    if (opts?.withProtectionPlan) {
      setProtectionPlanSelectedState(true);
      setProtectionPlanAddedVia("auto_added");
    }
  };

  const removeLine: CartContextValue["removeLine"] = (slug) => {
    setLines((prev) => prev.filter((line) => line.slug !== slug));
  };

  const setProtectionPlan: CartContextValue["setProtectionPlanSelected"] = (value, via) => {
    setProtectionPlanSelectedState(value);
    setProtectionPlanAddedVia(value ? via : null);
  };

  const clearCart = () => {
    setLines([]);
    setProtectionPlanSelectedState(false);
    setProtectionPlanAddedVia(null);
  };

  return (
    <CartContext.Provider
      value={{
        lines,
        protectionPlanSelected,
        protectionPlanAddedVia,
        addToCart,
        removeLine,
        setProtectionPlanSelected: setProtectionPlan,
        clearCart,
      }}
    >
      {children}
    </CartContext.Provider>
  );
}

export function useCart(): CartContextValue {
  const ctx = useContext(CartContext);
  if (!ctx) {
    throw new Error("useCart must be used within CartProvider");
  }
  return ctx;
}
