"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCart } from "@/context/CartContext";
import { useDarkPatternMode } from "@/context/DarkPatternModeContext";
import { CheckoutSteps } from "@/components/CheckoutSteps";
import { computeItemsSubtotal } from "@/lib/cartTotals";
import { PAYMENT_PROCESSING_FEE, SERVICE_HANDLING_FEE } from "@/lib/constants";
import { formatInr } from "@/lib/format";
import { getProductBySlug } from "@/data/products";

export default function ReviewStepPage() {
  const router = useRouter();
  const { lines, protectionPlanSelected, clearCart } = useCart();
  const { darkPatternsEnabled } = useDarkPatternMode();
  const itemsSubtotal = computeItemsSubtotal(lines, protectionPlanSelected);

  // CCPA category: Drip Pricing
  // The service & handling fee appears here for the first time when dark
  // patterns are ON -- the final total is now itemsSubtotal + both fees,
  // neither of which was visible back at /cart.
  const displayedTotal = itemsSubtotal + PAYMENT_PROCESSING_FEE + SERVICE_HANDLING_FEE;

  const placeOrder = () => {
    clearCart();
    router.push("/checkout/confirmation");
  };

  return (
    <div className="mx-auto max-w-3xl px-6 py-10">
      <CheckoutSteps current="review" />
      <h1 className="text-2xl font-semibold text-brand-ink">Review your order</h1>

      <div className="mt-6 rounded-2xl border border-brand-border bg-brand-card p-5 text-sm">
        {lines.map((line) => {
          const product = getProductBySlug(line.slug);
          if (!product) return null;
          return (
            <div key={line.slug} className="flex justify-between py-1 text-brand-ink">
              <span>
                {product.name} × {line.quantity}
              </span>
              <span>{formatInr(product.price * line.quantity)}</span>
            </div>
          );
        })}
        {protectionPlanSelected && (
          <div className="flex justify-between py-1 text-brand-ink">
            <span>Auralis Protection Plan+</span>
            <span className="text-brand-muted">included</span>
          </div>
        )}
      </div>

      <div className="mt-6 rounded-2xl border border-brand-border bg-brand-card p-5">
        <div className="flex justify-between text-sm text-brand-muted">
          <span>Items subtotal</span>
          <span>{formatInr(itemsSubtotal)}</span>
        </div>
        <div className="mt-1 flex justify-between text-sm text-brand-muted">
          <span>Payment processing fee</span>
          <span>{formatInr(PAYMENT_PROCESSING_FEE)}</span>
        </div>
        <div className="mt-1 flex justify-between text-sm">
          <span className={darkPatternsEnabled ? "font-medium text-brand-danger-dark" : "text-brand-muted"}>
            Service &amp; handling fee{darkPatternsEnabled ? " (new)" : ""}
          </span>
          <span className={darkPatternsEnabled ? "font-medium text-brand-danger-dark" : "text-brand-muted"}>
            {formatInr(SERVICE_HANDLING_FEE)}
          </span>
        </div>
        <div className="mt-3 flex justify-between border-t border-brand-border pt-3 text-base font-semibold text-brand-ink">
          <span>Total</span>
          <span>{formatInr(displayedTotal)}</span>
        </div>
      </div>

      <div className="mt-8 flex items-center justify-between">
        <Link href="/checkout/payment" className="text-sm text-brand-muted hover:text-brand-ink">
          Back
        </Link>
        <button
          type="button"
          onClick={placeOrder}
          className="rounded-full bg-brand-ink px-8 py-3 text-sm font-semibold text-white hover:bg-black"
        >
          Place order
        </button>
      </div>
    </div>
  );
}
