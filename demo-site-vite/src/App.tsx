import { Route, Routes } from "react-router-dom";
import { DarkPatternModeProvider } from "@/context/DarkPatternModeContext";
import { CartProvider } from "@/context/CartContext";
import { AccountProvider } from "@/context/AccountContext";
import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";
import { ConfirmShamePopup } from "@/components/ConfirmShamePopup";
import { NaggingModal } from "@/components/NaggingModal";

import HomePage from "@/pages/HomePage";
import ProductPage from "@/pages/ProductPage";
import CartPage from "@/pages/CartPage";
import ShippingStepPage from "@/pages/checkout/ShippingStepPage";
import PaymentStepPage from "@/pages/checkout/PaymentStepPage";
import ReviewStepPage from "@/pages/checkout/ReviewStepPage";
import ConfirmationPage from "@/pages/checkout/ConfirmationPage";
import TrialPage from "@/pages/TrialPage";
import AccountPage from "@/pages/account/AccountPage";
import SubscriptionPage from "@/pages/account/SubscriptionPage";
import RetentionOfferPage from "@/pages/account/RetentionOfferPage";
import ConfirmCancelPage from "@/pages/account/ConfirmCancelPage";
import CancelledPage from "@/pages/account/CancelledPage";

export default function App() {
  return (
    <DarkPatternModeProvider>
      <AccountProvider>
        <CartProvider>
          <Header />
          <main className="flex-1">
            <Routes>
              <Route path="/" element={<HomePage />} />
              <Route path="/product/:slug" element={<ProductPage />} />
              <Route path="/cart" element={<CartPage />} />
              <Route path="/checkout/shipping" element={<ShippingStepPage />} />
              <Route path="/checkout/payment" element={<PaymentStepPage />} />
              <Route path="/checkout/review" element={<ReviewStepPage />} />
              <Route path="/checkout/confirmation" element={<ConfirmationPage />} />
              <Route path="/trial" element={<TrialPage />} />
              <Route path="/account" element={<AccountPage />} />
              <Route path="/account/subscription" element={<SubscriptionPage />} />
              <Route path="/account/subscription/retention-offer" element={<RetentionOfferPage />} />
              <Route path="/account/subscription/confirm-cancel" element={<ConfirmCancelPage />} />
              <Route path="/account/subscription/cancelled" element={<CancelledPage />} />
            </Routes>
          </main>
          <Footer />
          <ConfirmShamePopup />
          <NaggingModal />
        </CartProvider>
      </AccountProvider>
    </DarkPatternModeProvider>
  );
}
