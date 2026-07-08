import { Link, useParams } from "react-router-dom";
import { getProductBySlug } from "@/data/products";
import { ProductDetailClient } from "@/components/ProductDetailClient";

export default function ProductPage() {
  const { slug } = useParams<{ slug: string }>();
  const product = slug ? getProductBySlug(slug) : undefined;

  if (!product) {
    return (
      <div className="mx-auto max-w-lg px-6 py-20 text-center">
        <h1 className="text-2xl font-semibold text-brand-ink">Product not found</h1>
        <Link
          to="/"
          className="mt-6 inline-block rounded-full bg-brand-ink px-6 py-3 text-sm font-semibold text-white hover:bg-black"
        >
          Back to shop
        </Link>
      </div>
    );
  }

  return <ProductDetailClient product={product} />;
}
