# Attribute-Detection Test Package — Auralis demo site

This package is for manually testing Stage-2 "attribute" judging: given one
recorded episode (a user journey through the demo site) and the evidence
extracted from it, judge whether each of 7 mechanism attributes is present.

Site under test: **Auralis** (`demo-site/`), a synthetic ecommerce storefront
built specifically to exercise dark-pattern detection. No real payments or
real personal data are involved anywhere in this package.

## What's in here

Two flows, each recorded twice — once with the site's dark-pattern toggle
**ON**, once **OFF** — so you can compare how the judge responds to the same
flow with the manipulative UI either present or switched off:

| Folder | Flow | Dark patterns |
|---|---|---|
| `payload/cancel_subscription_ON/` | Cancel an active Auralis+ subscription | ON |
| `payload/cancel_subscription_OFF/` | Same cancellation flow | OFF |
| `payload/product_checkout_ON/` | Browse → add to cart → checkout | ON |
| `payload/product_checkout_OFF/` | Same checkout flow | OFF |

Each of those 4 folders contains one subfolder per attribute:

```
asymmetry/  complexity/  covertness/  deception/
disparate_treatment/  information_hiding/  restriction/
```

...and each attribute folder is a complete, self-contained unit:

- **`llm_input.txt`** — ⭐ **the one file you need.** The full prompt +
  the evidence_summary.json payload already embedded inline (the response
  schema is inlined too, inside the prompt). Paste this as your message to
  the LLM (or upload it), attach the images from `screenshots/` alongside
  it, and you're done — no copy-pasting multiple files together.
- `screenshots/` — masked screenshots for the steps relevant to this
  attribute (filenames map to step_id). May be empty for an attribute with
  no step-anchored evidence in this episode.
- `prompt.txt` / `evidence_summary.json` / `response_schema.json` — the
  same content as `llm_input.txt`, as separate files, in case your LLM
  interface wants them attached individually instead of combined.
- `manifest.json` — metadata about how this payload was built
- `INSTRUCTIONS.txt` — step-by-step usage (repeated per-folder so it
  travels with the files if unzipped separately)

28 attribute folders total (4 episodes × 7 attributes).

There's also a `journey/` folder alongside `payload/`, one subfolder per
flow (`cancel_subscription_ON`, `cancel_subscription_OFF`,
`product_checkout_ON`, `product_checkout_OFF`), each with the **full**
episode record (`episode.json` — every step, the full click-through, not
scoped to one attribute) and **every** screenshot from that run (not just
the ones a given attribute's payload pulled in). Use this if you want to
see the whole journey end-to-end before or instead of judging one
attribute at a time.

## How to test

For each attribute folder you want to test:

1. Open `llm_input.txt` and send its full contents as your message to the
   LLM (paste it in, or upload the file — whichever your interface
   supports).
2. Attach every image under that folder's `screenshots/` (there may be
   none for some attributes — that's expected, not an error).
3. The reply must be ONLY the JSON object `llm_input.txt` describes at the
   end (matching `response_schema.json`'s shape) — no prose, no markdown
   fences.
4. Save the reply as `response.json` in that same folder if you want a
   record of it.

That's it — one file + its screenshots per test, nothing to manually
assemble.

The verdict must be exactly one of: `fires`, `unsure`, `no`,
`not_assessable` — see `prompt.txt` for the full rules (evidence pointers
required for fires/unsure, severity required only for fires, etc).

## What to expect (code-agent baseline, for sanity-checking results)

This repo also runs a pure-code "attribute agent" per attribute as a
baseline (no LLM). Here's what it currently returns for these same 4
episodes — useful as a rough sanity check, not a ground truth:

**cancel_subscription_ON** — fires: `asymmetry`, `complexity`, `deception`
· not_assessable: `covertness`, `disparate_treatment`, `information_hiding`,
`restriction`

**cancel_subscription_OFF** — no: `complexity`, `deception` · not_assessable:
`asymmetry`, `covertness`, `disparate_treatment`, `information_hiding`,
`restriction`

**product_checkout_ON** — unsure: `asymmetry`, `complexity` ·
not_assessable: `covertness`, `deception`, `disparate_treatment`,
`information_hiding`, `restriction`

**product_checkout_OFF** — unsure: `asymmetry`, `complexity` ·
not_assessable: `covertness`, `deception`, `disparate_treatment`,
`information_hiding`, `restriction`

A good LLM judge should generally track or improve on this — e.g. the ON
checkout flow has real drip-pricing evidence (a "Payment processing fee
(new)" and "Service & handling fee (new)" that appear only after you've
already committed to checkout, absent in OFF) and a sneaked-in "Protection
Plan" cart line item (ON only) that the code agent currently can't resolve
past `not_assessable` for several attributes — those are good cases to
check an LLM judge handles correctly.

## Notes on what's visible in the screenshots

- A black "Dark Pattern Recorder" control panel (goal, step count, "Mark
  goal achieved" / "Abandon" / "Add note" / "End session" buttons) appears
  in the bottom-right of every screenshot. That's the *auditing tool's own*
  operator HUD, not part of the site being tested — ignore it when judging
  attributes (this is a known, accepted artifact of this recorder, not a
  bug in these recordings).
- The header's "Dark Patterns: ON/OFF" pill is part of the real site (a
  demo-mode toggle) and is legitimate evidence.

## Source

Recorded with this repo's `recorder/interactive_v2.py` (scripted — see
`scripts/record_checkout_pair.py` for the product-checkout pair; the
cancel-subscription pair was recorded separately as
`episode_auralis_cancel_on_v2` / `episode_auralis_cancel_off_v2`).
Evidence extracted with `extract_evidence.py`, payloads assembled with
`build_payload.py` against `prompts/attribute_prompt.v1.txt`. Nothing in
this package was produced by an LLM — it's all offline, pure-code
extraction and prompt assembly, ready for a human (or a different model)
to judge.
