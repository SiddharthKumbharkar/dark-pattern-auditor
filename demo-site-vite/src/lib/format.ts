export function formatInr(amount: number): string {
  return `₹${amount.toLocaleString("en-IN")}`;
}
