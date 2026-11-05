"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCart } from "@/context/CartContext";
import { useDarkPatternMode } from "@/context/DarkPatternModeContext";
import { CheckoutSteps } from "@/components/CheckoutSteps";
import { computeItemsSubtotal } from "@/lib/cartTotals";
import { PAYMENT_PROCESSING_FEE, SERVICE_HANDLING_FEE } from "@/lib/constants";
import { formatInr } from "@/lib/format";

export default function PaymentStepPage() {
  const router = useRouter();
  const { lines, protectionPlanSelected } = useCart();
  const { darkPatternsEnabled } = useDarkPatternMode();
  const itemsSubtotal = computeItemsSubtotal(lines, protectionPlanSelected);

  // CCPA category: Drip Pricing
  // The payment processing fee appears here for the first time when dark
  // patterns are ON -- it was never shown on /cart or the shipping step.
  const displayedTotal = darkPatternsEnabled
    ? itemsSubtotal + PAYMENT_PROCESSING_FEE
    : itemsSubtotal + PAYMENT_PROCESSING_FEE + SERVICE_HANDLING_FEE;

  return (
    <div className="mx-auto max-w-3xl px-6 py-10">
      <CheckoutSteps current="payment" />
      <h1 className="text-2xl font-semibold text-brand-ink">Payment details</h1>

      <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <input placeholder="Card number" className="rounded-lg border border-brand-border px-3 py-2 text-sm sm:col-span-2" />
        <input placeholder="MM / YY" className="rounded-lg border border-brand-border px-3 py-2 text-sm" />
        <input placeholder="CVV" className="rounded-lg border border-brand-border px-3 py-2 text-sm" />
      </div>

      <div className="mt-8 rounded-2xl border border-brand-border bg-brand-card p-5">
        <div className="flex justify-between text-sm text-brand-muted">
          <span>Items subtotal</span>
          <span>{formatInr(itemsSubtotal)}</span>
        </div>
        <div className="mt-1 flex justify-between text-sm">
          <span className={darkPatternsEnabled ? "font-medium text-brand-danger-dark" : "text-brand-muted"}>
            Payment processing fee{darkPatternsEnabled ? " (new)" : ""}
          </span>
          <span className={darkPatternsEnabled ? "font-medium text-brand-danger-dark" : "text-brand-muted"}>
            {formatInr(PAYMENT_PROCESSING_FEE)}
          </span>
        </div>
        {!darkPatternsEnabled && (
          <div className="mt-1 flex justify-between text-sm text-brand-muted">
            <span>Service &amp; handling fee</span>
            <span>{formatInr(SERVICE_HANDLING_FEE)}</span>
          </div>
        )}
        <div className="mt-3 flex justify-between border-t border-brand-border pt-3 text-base font-semibold text-brand-ink">
          <span>{darkPatternsEnabled ? "Total so far" : "Total"}</span>
          <span>{formatInr(displayedTotal)}</span>
        </div>
      </div>

      <div className="mt-8 flex items-center justify-between">
        <Link href="/checkout/shipping" className="text-sm text-brand-muted hover:text-brand-ink">
          Back
        </Link>
        <button
          type="button"
          onClick={() => router.push("/checkout/review")}
          className="rounded-full bg-brand-ink px-8 py-3 text-sm font-semibold text-white hover:bg-black"
        >
          Continue to review
        </button>
      </div>
    </div>
  );
}
