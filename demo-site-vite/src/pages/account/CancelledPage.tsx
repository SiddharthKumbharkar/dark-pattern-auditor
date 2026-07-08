import { Link } from "react-router-dom";

export default function CancelledPage() {
  return (
    <div className="mx-auto max-w-lg px-6 py-14 text-center">
      <h1 className="text-2xl font-semibold text-brand-ink">Membership cancelled</h1>
      <p className="mt-3 text-brand-muted">
        Your Auralis+ membership has been cancelled. You won't be charged again.
      </p>
      <Link
        to="/account"
        className="mt-8 inline-block rounded-full bg-brand-ink px-6 py-3 text-sm font-semibold text-white hover:bg-black"
      >
        Back to account
      </Link>
    </div>
  );
}
