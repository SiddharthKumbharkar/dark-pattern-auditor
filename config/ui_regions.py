"""The ui_region vocabulary and the deterministic classification rules
signals/ui_regions.py applies (Part A of the mechanism-attribute pipeline:
region tagging happens once, in the evidence extractor, BEFORE any
attribute agent runs -- agents and the coordinator only ever READ a
region off an evidence_pointer, they never invent one).

Config-driven and extensible by design: adding a new region means adding
an id to REGION_IDS and a keyword list to REGION_KEYWORDS here -- nothing
in signals/ui_regions.py, attribute_agents/base.py, or llm/payload_builder.py
needs to change. "unclassified" is a first-class, always-valid outcome,
not a placeholder for a rule that was never written -- see
signals/ui_regions.py's docstring for why forcing every element into a
named region would be worse than an honest miss.

Kept as a plain module (not YAML) because, unlike config.yaml's runtime
settings, this vocabulary is versioned test fixture material -- schema
files (schema/episode.v2.schema.json's EvidencePointer.ui_region enum) and
tests import REGION_IDS directly so the two can never drift silently.
"""

from typing import Dict, List, Tuple

REGION_IDS: Tuple[str, ...] = (
    "cookie_consent_banner",
    "checkout_price_summary",
    "cancellation_flow",
    "signup_form",
    "login_form",
    "newsletter_modal",
    "addon_upsell",
    "account_settings",
    "retention_offer",
    "unclassified",
)

# Ordered: the first region whose keyword list matches ANY of (selector,
# text, role, ancestor landmark/heading text) wins -- order matters when a
# page's copy could plausibly match more than one region (e.g. a
# retention offer inside a cancellation flow: "retention_offer" is
# checked before "cancellation_flow" so a keep-your-subscription upsell
# panel is tagged as the offer it is, not folded into the surrounding
# flow's region).
REGION_KEYWORDS: Dict[str, List[str]] = {
    "cookie_consent_banner": [
        "cookie", "consent", "gdpr", "ccpa-banner", "privacy-banner", "accept-cookies",
    ],
    "newsletter_modal": [
        "newsletter", "subscribe-modal", "email-capture", "signup-modal",
    ],
    "retention_offer": [
        "retention", "before-you-go", "special-offer", "stay-offer", "win-back", "discount-offer",
        "we'd hate to see you go", "one more chance",
    ],
    "cancellation_flow": [
        "cancel", "unsubscribe", "end-membership", "end-subscription", "terminate",
        # The "keep"/"stay subscribed" side of a keep-vs-cancel accept/reject
        # pair has no "cancel"-shaped text of its own, but it's structurally
        # part of the SAME cancellation decision point -- without this, a
        # single visual_asymmetry pair's two evidence_pointers (positive:
        # keep, negative: cancel) split across two different regions
        # (cancellation_flow + unclassified) purely because only one side's
        # selector happens to say "cancel".
        "keep-subscription", "keep-membership", "stay-subscribed", "stay-member",
    ],
    "addon_upsell": [
        "addon", "add-on", "upsell", "upgrade", "bundle", "cross-sell",
    ],
    "checkout_price_summary": [
        "checkout", "order-summary", "cart-total", "price-summary", "billing-summary", "payment-summary",
    ],
    "signup_form": [
        "signup", "sign-up", "register", "create-account", "join-now",
    ],
    "login_form": [
        "login", "sign-in", "signin", "log-in",
    ],
    "account_settings": [
        "account", "settings", "profile", "preferences",
    ],
}

# HTML landmark/role tags whose presence as an ANCESTOR of an element is a
# structural cue signals/ui_regions.py walks up to before falling back to
# keyword matching -- e.g. an element inside <nav aria-label="account
# settings"> is a stronger, more "deterministic" signal than a keyword hit
# on its own selector.
LANDMARK_TAGS: Tuple[str, ...] = ("header", "nav", "main", "footer", "aside", "section", "form", "dialog")
LANDMARK_ROLES: Tuple[str, ...] = ("banner", "navigation", "main", "contentinfo", "complementary", "dialog", "alertdialog", "form")

UNCLASSIFIED_REGION = "unclassified"

# Goal -> the single ui_region a FLOW-level/group-level finding for that
# goal belongs to (a finding whose own evidence_pointer has no single
# representative element to classify -- e.g. restriction's friction_ratio,
# complexity's total_actions_required, deception's dead-control check --
# see attribute_agents/base.py's _flow_region()). Only goals with an
# honest, unambiguous SINGLE region get an entry here -- a goal like
# purchase_cheapest genuinely spans several real regions across one
# episode (product page, cart, checkout_price_summary), so there is no
# single truthful answer for it; omitting it (rather than guessing) means
# its flow-level findings correctly stay "unclassified" -- the same
# "never invented" principle REGION_KEYWORDS above already follows.
# attribute_agents/base.py cross-checks a goal's candidate region against
# the episode's OWN real per-element ui_regions tags before trusting it --
# an entry here is necessary but not sufficient.
GOAL_TO_FLOW_REGION: Dict[str, str] = {
    "cancel_subscription": "cancellation_flow",
    "complete_signup": "signup_form",
    "reject_cookies": "cookie_consent_banner",
    "decline_addon": "addon_upsell",
}
