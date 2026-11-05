# Auralis — Dark Pattern Demo Storefront

A polished, realistic e-commerce demo site (premium wireless headphones brand
"Auralis") built specifically to be audited live by the Python dark-pattern
auditing pipeline in the parent `dark-pattern-project/` repo. It contains 8
deliberately-implemented dark patterns, each mapped to one of the tool's 13
CCPA categories, plus a header toggle that switches the whole site between
its manipulative and clean behavior for a live before/after demo.

## Running it

```bash
cd demo-site
npm install
npm run dev
```

Open `http://localhost:3000`. `npm run build && npm run start` for a
production build if you want lower latency while screen-sharing.

No database, no real payment processing, no external API keys — every
"payment"/"card" field is decorative, and cart/subscription state lives in
`sessionStorage` (survives an accidental refresh mid-demo, resets when the
tab closes).

## The "Dark Patterns: ON/OFF" toggle

Top-right of the header on every page. It's a `DarkPatternModeProvider`
(`src/context/DarkPatternModeContext.tsx`) backed by `localStorage`, so it
persists across navigations and reloads until you flip it again. Every
pattern below reads this flag directly and swaps to a clean equivalent when
it's OFF — flip it live on stage, re-run your recorder, and the same URL
should produce a clean audit instead of 8 findings.

## Pattern cheat sheet

| # | Pattern | CCPA category | Where it lives | Trigger / detectable signal |
|---|---|---|---|---|
| 1 | Countdown timer that resets on refresh | **False Urgency** | `src/components/CountdownTimer.tsx` (used on `src/app/product/[slug]/page.tsx` via `ProductDetailClient.tsx`) | Recomputes `Date.now() + 15min` on every mount. Rendered as `<div class="countdown-timer" data-countdown="true">` — matches `_TIMER_KEYWORDS` and the `data-countdown` check in `signals/urgency.py::extract_timers`. Visible text also contains "Hurry", matching `extract_urgency_claims`. |
| 2 | Guilt-copy popup | **Confirm Shaming** | `src/components/ConfirmShamePopup.tsx` (mounted globally in `src/app/layout.tsx`) | Appears ~1.4s after first load, once per session. Decline button reads *"No thanks, I don't like saving money"* when ON, *"No thanks"* when OFF. |
| 3 | Fees revealed only at later checkout steps | **Drip Pricing** | `src/app/checkout/shipping/page.tsx` → `payment/page.tsx` → `review/page.tsx`, fee amounts in `src/lib/constants.ts` | `/cart` and the shipping step only ever show the items subtotal. The ₹149 "Payment processing fee" first appears at `/checkout/payment`; the ₹199 "Service & handling fee" first appears at `/checkout/review`. Both are plain visible text, picked up by `signals/price.py`. |
| 4 | Free trial that auto-enrolls in a paid subscription | **Subscription Trap** | `src/app/trial/page.tsx`, subscription state in `src/context/AccountContext.tsx` | CTA reads "Start My Free Trial" (not "Subscribe"); the ₹499/month auto-renewal disclosure is real text but shrunk to a low-contrast `text-[11px]` fine-print line. The cancellation entry point on `src/app/account/page.tsx` is also demoted to a small "Manage membership" text link at the very bottom of the page instead of a normal button. |
| 5 | Pre-checked "Protection Plan" add-on | **Basket Sneaking** | `src/context/CartContext.tsx` (`addToCart(..., { withProtectionPlan: true })`), rendered in `src/app/cart/page.tsx` | Adding any product also silently sets `protectionPlanSelected = true` with `protectionPlanAddedVia: "auto_added"`. The cart page renders this as a real `<table class="cart-table">` row (name/qty/price cells) with a grey `(auto-added)` subtext — same convention as `test_sites/shopdemo/cart.html`, so `signals/cart.py::extract_cart_items` / `compute_cart_diff` parse it identically. The checkbox itself is normal-sized (not a size trick) — the isolated signal here is purely "pre-selected without a click", not a compounded Interface Interference effect. |
| 6 | Fake incrementing "people viewing / bought" counters | **False Urgency** (2nd instance) | `src/components/SocialProofCounter.tsx` (on the product page) | Two counters tick on a `setInterval` with pure `Math.random()` steps, no real data behind them. Feeds the pipeline's dedicated `signals/urgency.py::extract_social_proof_claims` (`social_proof_claims` field), while the CCPA-category verdict for this instance is still False Urgency — the same category as the countdown timer, since a fabricated demand signal is the same category of deception, just a second, separately-located instance. See `journey/schema.py::ExtractedSignals.social_proof_claims`. |
| 7 | Convoluted subscription cancellation flow | **Interface Interference** | `src/app/account/subscription/page.tsx` → `retention-offer/page.tsx` → `confirm-cancel/page.tsx` → `cancelled/page.tsx` | Two consecutive screens each pair a large, high-contrast, shadowed "keep" button (`.btn-keep-subscription`) against a tiny, low-contrast underlined "actually cancel" link (`.btn-cancel-link`) — the same `.btn-keep` / `.btn-remove` visual convention already used for the warranty upsell in `test_sites/shopdemo/cart.html`. This pattern currently depends on the LLM judge reading screenshots (`signals/ui_measurements.py` is still an unimplemented stub in the pipeline), so make sure screenshots are captured on these two intermediate screens during the demo, not just the start/end states. |
| 8 | Notification-permission modal that reappears | **Nagging** | `src/components/NaggingModal.tsx` (mounted globally in `src/app/layout.tsx`) | First appears 5s after load; if dismissed with "Not now", reappears every ~22s, up to 5 times. Fully suppressed when the toggle is OFF. |

## Known pipeline-coverage gaps (as of this build)

A few of the patterns above rely on the LLM judge's reading of screenshots
and visible text rather than a dedicated Python signal extractor, because
those extractors are still empty stubs in the parent project:

- `signals/popups.py` (patterns #2 and #8) — not yet implemented, so the
  popup/modal text is only visible to the judge via `visible_text_summary`,
  not a structured `popups` signal.
- `signals/ui_measurements.py` (pattern #7) — not yet implemented, so the
  keep/cancel size disparity is only visible via screenshots, not a
  structured measurement.

Everything else (countdown timer, prices, cart items, urgency/social-proof
text, `page_type`) is picked up by the existing implemented extractors —
confirmed by running `python audit.py --urls "http://localhost:3000/,http://localhost:3000/product/auralis-pro-x" --audit-id demo_check --domain auralis-demo.local --industry ecommerce` against a live `npm run dev` instance of this site.

## Product catalog reference

Defined in `src/data/products.ts`, all prices in INR:

| Slug | Name | Price | Was |
|---|---|---|---|
| `auralis-pro-x` | Auralis Pro X Wireless Headphones (hero product — carries all 8 patterns) | ₹8,999 | ₹12,999 |
| `auralis-air-buds` | Auralis Air Wireless Earbuds | ₹4,499 | ₹5,999 |
| `auralis-studio-case` | Auralis Studio Travel Case | ₹1,299 | — |

Protection Plan add-on (Basket Sneaking): ₹399, defined in
`src/context/CartContext.tsx` (`PROTECTION_PLAN_NAME`, `PROTECTION_PLAN_PRICE`).

Checkout drip-pricing fees: `PAYMENT_PROCESSING_FEE` (₹149) and
`SERVICE_HANDLING_FEE` (₹199) in `src/lib/constants.ts`.

## Suggested live demo path

1. `/` — point out the toggle is ON, dismiss the Confirm Shaming popup.
2. `/product/auralis-pro-x` — countdown timer + incrementing social proof counters.
3. Add to cart → `/cart` — Protection Plan pre-checked, `(auto-added)`.
4. `/checkout/shipping` → `/checkout/payment` → `/checkout/review` — watch the total grow with each step.
5. `/trial` — start the free trial, note the fine print.
6. `/account` → "Manage membership" (small link at the bottom) → cancel → retention offer → confirm screen — point out the button size disparity on both screens.
7. Flip the header toggle to OFF, repeat steps 2–6 to show the clean contrast.
