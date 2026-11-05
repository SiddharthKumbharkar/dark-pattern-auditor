// CCPA category: Drip Pricing
// These two fees are only added to the visible total at later checkout
// steps when dark patterns are enabled (see checkout/payment and
// checkout/review pages) -- never disclosed at /cart or /checkout/shipping.
export const PAYMENT_PROCESSING_FEE = 149;
export const SERVICE_HANDLING_FEE = 199;
