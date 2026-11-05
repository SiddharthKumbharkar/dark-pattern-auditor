import { getProductBySlug } from "@/data/products";
import { PROTECTION_PLAN_PRICE, type CartLine } from "@/context/CartContext";

export function computeItemsSubtotal(lines: CartLine[], protectionPlanSelected: boolean): number {
  const itemsTotal = lines.reduce((sum, line) => {
    const product = getProductBySlug(line.slug);
    return product ? sum + product.price * line.quantity : sum;
  }, 0);
  return itemsTotal + (protectionPlanSelected ? PROTECTION_PLAN_PRICE : 0);
}
