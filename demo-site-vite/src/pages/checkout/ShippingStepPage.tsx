import { Link, useNavigate } from "react-router-dom";
import { useCart } from "@/context/CartContext";
import { useDarkPatternMode } from "@/context/DarkPatternModeContext";
import { CheckoutSteps } from "@/components/CheckoutSteps";
import { computeItemsSubtotal } from "@/lib/cartTotals";
import { PAYMENT_PROCESSING_FEE, SERVICE_HANDLING_FEE } from "@/lib/constants";
import { formatInr } from "@/lib/format";

export default function ShippingStepPage() {
  const navigate = useNavigate();
  const { lines, protectionPlanSelected } = useCart();
  const { darkPatternsEnabled } = useDarkPatternMode();
  const itemsSubtotal = computeItemsSubtotal(lines, protectionPlanSelected);

  // CCPA category: Drip Pricing
  // With dark patterns OFF, every fee is disclosed from the first step.
  // With them ON, this step only shows itemsSubtotal -- both fees are
  // introduced later, at /checkout/payment and /checkout/review.
  const displayedTotal = darkPatternsEnabled
    ? itemsSubtotal
    : itemsSubtotal + PAYMENT_PROCESSING_FEE + SERVICE_HANDLING_FEE;

  return (
    <div className="mx-auto max-w-3xl px-6 py-10">
      <CheckoutSteps current="shipping" />
      <h1 className="text-2xl font-semibold text-brand-ink">Shipping details</h1>

      <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <input placeholder="Full name" className="rounded-lg border border-brand-border px-3 py-2 text-sm sm:col-span-2" />
        <input placeholder="Address line 1" className="rounded-lg border border-brand-border px-3 py-2 text-sm sm:col-span-2" />
        <input placeholder="City" className="rounded-lg border border-brand-border px-3 py-2 text-sm" />
        <input placeholder="PIN code" className="rounded-lg border border-brand-border px-3 py-2 text-sm" />
      </div>

      <div className="mt-8 rounded-2xl border border-brand-border bg-brand-card p-5">
        <div className="flex justify-between text-sm text-brand-muted">
          <span>Items subtotal</span>
          <span>{formatInr(itemsSubtotal)}</span>
        </div>
        {!darkPatternsEnabled && (
          <>
            <div className="mt-1 flex justify-between text-sm text-brand-muted">
              <span>Payment processing fee</span>
              <span>{formatInr(PAYMENT_PROCESSING_FEE)}</span>
            </div>
            <div className="mt-1 flex justify-between text-sm text-brand-muted">
              <span>Service &amp; handling fee</span>
              <span>{formatInr(SERVICE_HANDLING_FEE)}</span>
            </div>
          </>
        )}
        <div className="mt-3 flex justify-between border-t border-brand-border pt-3 text-base font-semibold text-brand-ink">
          <span>{darkPatternsEnabled ? "Total so far" : "Total"}</span>
          <span>{formatInr(displayedTotal)}</span>
        </div>
      </div>

      <div className="mt-8 flex items-center justify-between">
        <Link to="/cart" className="text-sm text-brand-muted hover:text-brand-ink">
          Back to cart
        </Link>
        <button
          type="button"
          onClick={() => navigate("/checkout/payment")}
          className="rounded-full bg-brand-ink px-8 py-3 text-sm font-semibold text-white hover:bg-black"
        >
          Continue to payment
        </button>
      </div>
    </div>
  );
}
