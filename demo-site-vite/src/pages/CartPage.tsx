import { Link } from "react-router-dom";
import { useCart, PROTECTION_PLAN_NAME, PROTECTION_PLAN_PRICE } from "@/context/CartContext";
import { getProductBySlug } from "@/data/products";
import { formatInr } from "@/lib/format";

// CCPA category: Basket Sneaking
// Trigger: PROTECTION_PLAN_PRICE / protectionPlanSelected is set to `true`
// automatically by CartContext.addToCart() (see withProtectionPlan) whenever
// dark patterns are enabled -- the user never explicitly clicked to add it.
// Rendered here as a plain, normal-sized checkbox (not a size/visibility
// trick) so the isolated signal is purely "pre-selected without consent".
export default function CartPage() {
  const { lines, protectionPlanSelected, protectionPlanAddedVia, removeLine, setProtectionPlanSelected } =
    useCart();

  const productLines = lines
    .map((line) => ({ line, product: getProductBySlug(line.slug) }))
    .filter(
      (entry): entry is { line: typeof entry.line; product: NonNullable<typeof entry.product> } =>
        Boolean(entry.product)
    );

  const itemsSubtotal = productLines.reduce(
    (sum, { line, product }) => sum + product.price * line.quantity,
    0
  );
  const protectionTotal = protectionPlanSelected ? PROTECTION_PLAN_PRICE : 0;
  const subtotal = itemsSubtotal + protectionTotal;
  const isEmpty = productLines.length === 0;

  return (
    <div className="mx-auto max-w-4xl px-6 py-10">
      <h1 className="text-2xl font-semibold text-brand-ink">Your Cart</h1>

      {isEmpty ? (
        <div className="mt-8 rounded-2xl border border-brand-border bg-brand-card p-10 text-center text-brand-muted">
          <p>Your cart is empty.</p>
          <Link
            to="/"
            className="mt-4 inline-block rounded-full bg-brand-ink px-5 py-2.5 text-sm font-semibold text-white hover:bg-black"
          >
            Continue shopping
          </Link>
        </div>
      ) : (
        <>
          <table className="cart-table mt-8 w-full border-collapse overflow-hidden rounded-2xl border border-brand-border bg-brand-card text-sm">
            <thead>
              <tr className="border-b border-brand-border text-left text-xs uppercase tracking-wide text-brand-muted">
                <th className="px-5 py-3">Item</th>
                <th className="px-5 py-3">Qty</th>
                <th className="px-5 py-3">Price</th>
                <th className="px-5 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {productLines.map(({ line, product }) => (
                <tr key={line.slug} className="border-b border-brand-border">
                  <td className="px-5 py-4 font-medium text-brand-ink">{product.name}</td>
                  <td className="px-5 py-4">{line.quantity}</td>
                  <td className="px-5 py-4">{formatInr(product.price * line.quantity)}</td>
                  <td className="px-5 py-4 text-right">
                    <button
                      type="button"
                      onClick={() => removeLine(line.slug)}
                      className="text-xs font-medium text-brand-muted underline hover:text-brand-ink"
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}

              {protectionPlanSelected && (
                <tr className="border-b border-brand-border bg-brand-accent/5">
                  <td className="px-5 py-4 font-medium text-brand-ink">
                    {PROTECTION_PLAN_NAME}
                    {protectionPlanAddedVia === "auto_added" && (
                      <span className="mt-0.5 block text-xs font-normal text-brand-muted">
                        (auto-added)
                      </span>
                    )}
                  </td>
                  <td className="px-5 py-4">1</td>
                  <td className="px-5 py-4">{formatInr(PROTECTION_PLAN_PRICE)}</td>
                  <td className="px-5 py-4 text-right">
                    <label className="inline-flex items-center gap-2 text-xs font-medium text-brand-muted">
                      <input
                        type="checkbox"
                        checked={protectionPlanSelected}
                        onChange={(e) => setProtectionPlanSelected(e.target.checked, "explicit")}
                      />
                      Keep plan
                    </label>
                  </td>
                </tr>
              )}

              <tr>
                <td className="px-5 py-4 font-semibold text-brand-ink">Subtotal</td>
                <td className="px-5 py-4"></td>
                <td className="px-5 py-4 font-semibold text-brand-ink">{formatInr(subtotal)}</td>
                <td className="px-5 py-4"></td>
              </tr>
            </tbody>
          </table>

          {!protectionPlanSelected && (
            <label className="mt-4 flex items-center gap-2 text-sm text-brand-muted">
              <input
                type="checkbox"
                checked={false}
                onChange={(e) => setProtectionPlanSelected(e.target.checked, "explicit")}
              />
              Add {PROTECTION_PLAN_NAME} ({formatInr(PROTECTION_PLAN_PRICE)})
            </label>
          )}

          <div className="mt-8 flex justify-end">
            <Link
              to="/checkout/shipping"
              className="rounded-full bg-brand-ink px-8 py-3 text-sm font-semibold text-white hover:bg-black"
            >
              Proceed to checkout
            </Link>
          </div>
        </>
      )}
    </div>
  );
}
