"use client";

import Link from "next/link";
import { useState } from "react";
import type { Product } from "@/data/products";
import { ProductVisual } from "@/components/ProductVisual";
import { CountdownTimer } from "@/components/CountdownTimer";
import { SocialProofCounter } from "@/components/SocialProofCounter";
import { formatInr } from "@/lib/format";
import { useCart } from "@/context/CartContext";
import { useDarkPatternMode } from "@/context/DarkPatternModeContext";

export function ProductDetailClient({ product }: { product: Product }) {
  const { addToCart } = useCart();
  const { darkPatternsEnabled } = useDarkPatternMode();
  const [added, setAdded] = useState(false);

  const handleAddToCart = () => {
    addToCart(product.slug, { withProtectionPlan: darkPatternsEnabled });
    setAdded(true);
    window.setTimeout(() => setAdded(false), 2500);
  };

  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      <nav className="mb-6 text-sm text-brand-muted">
        <Link href="/" className="hover:text-brand-ink">
          Home
        </Link>
        <span className="mx-2">/</span>
        <span className="text-brand-ink">{product.shortName}</span>
      </nav>

      <div className="grid grid-cols-1 gap-10 md:grid-cols-2">
        <ProductVisual kind={product.visual} className="aspect-square w-full" />

        <div>
          <span className="text-xs font-medium uppercase tracking-wide text-brand-muted">
            {product.colorway}
          </span>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight text-brand-ink">
            {product.name}
          </h1>
          <p className="mt-2 text-brand-muted">{product.tagline}</p>

          <div className="mt-4 flex items-baseline gap-3">
            <span className="text-2xl font-semibold text-brand-ink">
              {formatInr(product.price)}
            </span>
            {product.originalPrice && (
              <span className="text-base text-brand-muted line-through">
                {formatInr(product.originalPrice)}
              </span>
            )}
          </div>

          <div className="mt-4">
            <CountdownTimer />
          </div>

          <button
            type="button"
            onClick={handleAddToCart}
            className="mt-6 w-full rounded-full bg-brand-ink px-6 py-3 text-sm font-semibold text-white hover:bg-black sm:w-auto sm:px-10"
          >
            {added ? "Added to cart ✓" : "Add to cart"}
          </button>

          <div className="mt-4">
            <SocialProofCounter />
          </div>

          <p className="mt-6 text-sm leading-relaxed text-brand-muted">{product.description}</p>

          <ul className="mt-5 space-y-2 text-sm text-brand-ink">
            {product.features.map((feature) => (
              <li key={feature} className="flex gap-2">
                <span className="text-brand-accent">•</span>
                {feature}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
