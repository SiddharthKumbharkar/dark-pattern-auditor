import { Link } from "react-router-dom";
import type { Product } from "@/data/products";
import { ProductVisual } from "@/components/ProductVisual";
import { formatInr } from "@/lib/format";

export function ProductCard({ product }: { product: Product }) {
  return (
    <Link
      to={`/product/${product.slug}`}
      className="group flex flex-col overflow-hidden rounded-2xl border border-brand-border bg-brand-card transition-shadow hover:shadow-lg"
    >
      <ProductVisual kind={product.visual} className="aspect-square" />
      <div className="flex flex-1 flex-col gap-1 p-5">
        <span className="text-xs font-medium uppercase tracking-wide text-brand-muted">
          {product.colorway}
        </span>
        <h3 className="text-base font-semibold text-brand-ink group-hover:text-brand-accent-dark">
          {product.shortName}
        </h3>
        <p className="text-sm text-brand-muted">{product.tagline}</p>
        <div className="mt-2 flex items-baseline gap-2">
          <span className="text-lg font-semibold text-brand-ink">{formatInr(product.price)}</span>
          {product.originalPrice && (
            <span className="text-sm text-brand-muted line-through">
              {formatInr(product.originalPrice)}
            </span>
          )}
        </div>
      </div>
    </Link>
  );
}
