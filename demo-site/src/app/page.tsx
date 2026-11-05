import Link from "next/link";
import { PRODUCTS, HERO_PRODUCT } from "@/data/products";
import { ProductCard } from "@/components/ProductCard";
import { ProductVisual } from "@/components/ProductVisual";
import { formatInr } from "@/lib/format";

export default function HomePage() {
  return (
    <div>
      <section className="mx-auto flex max-w-6xl flex-col items-center gap-10 px-6 py-14 md:flex-row md:py-20">
        <div className="flex-1">
          <span className="text-xs font-semibold uppercase tracking-widest text-brand-accent-dark">
            New — Pro X Series
          </span>
          <h1 className="mt-3 text-4xl font-semibold tracking-tight text-brand-ink md:text-5xl">
            Sound that disappears into the moment.
          </h1>
          <p className="mt-4 max-w-md text-brand-muted">
            {HERO_PRODUCT.tagline}. Adaptive noise cancellation, 38-hour battery, and a fit you
            forget you&apos;re wearing.
          </p>
          <div className="mt-7 flex items-center gap-3">
            <Link
              href={`/product/${HERO_PRODUCT.slug}`}
              className="rounded-full bg-brand-ink px-6 py-3 text-sm font-semibold text-white hover:bg-black"
            >
              Shop {HERO_PRODUCT.shortName}
            </Link>
            <span className="text-sm font-medium text-brand-muted">
              {formatInr(HERO_PRODUCT.price)}
            </span>
          </div>
        </div>
        <div className="w-full max-w-sm flex-1">
          <ProductVisual kind={HERO_PRODUCT.visual} className="aspect-square w-full" />
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-6 py-10">
        <div className="mb-6 flex items-end justify-between">
          <h2 className="text-xl font-semibold text-brand-ink">Shop the collection</h2>
        </div>
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {PRODUCTS.map((product) => (
            <ProductCard key={product.slug} product={product} />
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-6 py-14">
        <div className="rounded-2xl border border-brand-border bg-brand-card p-8 md:p-10">
          <h2 className="text-lg font-semibold text-brand-ink">Auralis+ Membership</h2>
          <p className="mt-2 max-w-xl text-sm text-brand-muted">
            Free 30-day trial: priority support, extended warranty, and member pricing on every
            future order.
          </p>
          <Link
            href="/trial"
            className="mt-5 inline-block rounded-full border border-brand-ink px-5 py-2.5 text-sm font-semibold text-brand-ink hover:bg-brand-ink hover:text-white"
          >
            Start free trial
          </Link>
        </div>
      </section>
    </div>
  );
}
