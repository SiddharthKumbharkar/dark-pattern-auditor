export type ProductVisualKind = "headphones" | "earbuds" | "case";

export interface Product {
  slug: string;
  name: string;
  shortName: string;
  tagline: string;
  price: number;
  originalPrice?: number;
  description: string;
  features: string[];
  visual: ProductVisualKind;
  colorway: string;
}

// All prices in INR to match the auditing pipeline's PRICE_PATTERNS (Rs. / INR / Crores).
export const PRODUCTS: Product[] = [
  {
    slug: "auralis-pro-x",
    name: "Auralis Pro X Wireless Headphones",
    shortName: "Auralis Pro X",
    tagline: "Studio-grade sound, all-day comfort",
    price: 8999,
    originalPrice: 12999,
    description:
      "Auralis Pro X pairs a 40mm titanium-coated driver with adaptive noise cancellation, tuned for daily commutes and long studio sessions alike. 38-hour battery life, multipoint Bluetooth 5.3, and a memory-foam headband that disappears after the first hour of wear.",
    features: [
      "Adaptive active noise cancellation",
      "38-hour battery, 10-minute fast charge for 6 hours",
      "Bluetooth 5.3 multipoint pairing",
      "Memory-foam ear cushions with breathable mesh",
    ],
    visual: "headphones",
    colorway: "Graphite / Brass",
  },
  {
    slug: "auralis-air-buds",
    name: "Auralis Air Wireless Earbuds",
    shortName: "Auralis Air",
    tagline: "Featherlight, all-day earbuds",
    price: 4499,
    originalPrice: 5999,
    description:
      "A true-wireless companion built for movement — sweat resistant, secure-fit ear tips, and a pocketable charging case good for three extra charges.",
    features: [
      "IPX5 sweat and splash resistance",
      "7-hour playback, 28 hours with case",
      "Touch controls with customizable gestures",
    ],
    visual: "earbuds",
    colorway: "Warm White",
  },
  {
    slug: "auralis-studio-case",
    name: "Auralis Studio Travel Case",
    shortName: "Studio Case",
    tagline: "Hard-shell protection for the road",
    price: 1299,
    description:
      "A molded hard-shell case with a soft microfiber lining, cable pouch, and carabiner loop — sized to fit any Auralis over-ear headphone.",
    features: [
      "Impact-resistant molded shell",
      "Microfiber-lined interior",
      "Included cable and adapter pouch",
    ],
    visual: "case",
    colorway: "Charcoal",
  },
];

export function getProductBySlug(slug: string): Product | undefined {
  return PRODUCTS.find((product) => product.slug === slug);
}

export const HERO_PRODUCT = PRODUCTS[0];
