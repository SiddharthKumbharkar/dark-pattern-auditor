import type { Metadata } from "next";
import { Geist } from "next/font/google";
import "./globals.css";
import { DarkPatternModeProvider } from "@/context/DarkPatternModeContext";
import { CartProvider } from "@/context/CartContext";
import { AccountProvider } from "@/context/AccountContext";
import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";
import { ConfirmShamePopup } from "@/components/ConfirmShamePopup";
import { NaggingModal } from "@/components/NaggingModal";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Auralis — Precision Wireless Audio",
  description: "Studio-grade wireless headphones and earbuds.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${geistSans.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col bg-brand-paper text-brand-ink">
        <DarkPatternModeProvider>
          <AccountProvider>
            <CartProvider>
              <Header />
              <main className="flex-1">{children}</main>
              <Footer />
              <ConfirmShamePopup />
              <NaggingModal />
            </CartProvider>
          </AccountProvider>
        </DarkPatternModeProvider>
      </body>
    </html>
  );
}
