import { Link } from "react-router-dom";

export default function ConfirmationPage() {
  return (
    <div className="mx-auto max-w-lg px-6 py-20 text-center">
      <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-brand-success/10 text-2xl text-brand-success">
        ✓
      </div>
      <h1 className="mt-6 text-2xl font-semibold text-brand-ink">Order confirmed</h1>
      <p className="mt-2 text-sm text-brand-muted">
        Thank you for your order. A confirmation email is on its way with your order number and
        estimated delivery date.
      </p>
      <Link
        to="/"
        className="mt-8 inline-block rounded-full bg-brand-ink px-6 py-3 text-sm font-semibold text-white hover:bg-black"
      >
        Continue shopping
      </Link>
    </div>
  );
}
