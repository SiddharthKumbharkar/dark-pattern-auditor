# Dark Pattern Auditing Tool

## What This Project Is
A human-in-the-loop multimodal dark pattern auditing tool.
A human auditor browses a website while the tool records the journey,
extracts structured signals, and passes the evidence to a multimodal LLM
that classifies which of 13 dark patterns are present.

## Architecture — 4 Layers (do not add more layers or rename these)
- Layer 1 recorder/         Playwright-based session recorder. Captures URL,
                             screenshot, DOM, visible text, timestamps per step.
                             Includes redaction.py (sensitive field masking) and
                             exclusion.py (URL-pattern page skip).
- Layer 2 journey/          Assembles captured steps into an ordered journey
                             record matching the canonical schema. Handles
                             artifact storage and auto-revisit scheduling.
- Layer 3 signals/          One file per extractor function. Each takes a page
                             state and returns typed signal fields. Pure
                             functions, no LLM calls, no side effects.
- Layer 4 llm/              Builds the prompt, calls the API, parses output.
                             The ONLY layer that calls an LLM.

## Canonical Schema — Every Step Record Has These Fields
```json
{
  "step_id": 1,
  "timestamp": "ISO8601",
  "url": "string",
  "page_title": "string",
  "page_type": "product_page|cart_page|checkout_page|...",
  "user_action": {
    "action_type": "open_page|click|scroll|form_input",
    "target_text": "string or null",
    "target_role": "string or null",
    "input_value_masked": "string or null"
  },
  "capture_excluded": false,
  "exclusion_reason": null,
  "state_capture": {
    "screenshot_id": "step_001.png",
    "dom_snapshot_id": "step_001.html",
    "ocr_text_id": "step_001_ocr.txt or null",
    "accessibility_tree_id": null
  },
  "visible_text_summary": ["array", "of", "strings"],
  "extracted_signals": {
    "prices": [{"label": "string", "value": 0.0, "currency": "INR"}],
    "cart_items": [{"name": "string", "quantity": 1, "user_selected": true}],
    "urgency_claims": ["string"],
    "timers": [],
    "popups": [{"popup_id": "string", "type": "string", "occurrence_count_this_journey": 1}],
    "forms": [{"fields": ["string"], "required": ["string"]}]
  },
  "extraction_confidence": {
    "ocr_used": false,
    "dom_extraction_complete": true,
    "low_confidence_fields": []
  }
}
```

## The 13 Dark Patterns This Tool Detects
False Urgency, Basket Sneaking, Confirm Shaming, Forced Action,
Subscription Trap, Interface Interference, Bait & Switch, Drip Pricing,
Disguised Advertisements, Nagging, Trick Wording, SaaS Billing, Rogue Malware.

## Key Design Rules
- Signal extractors (Layer 3) are pure functions. No Playwright imports,
  no API calls, no file I/O inside signals/.
- Sensitive field redaction happens in recorder/redaction.py BEFORE any
  data is written to storage. Never write raw form values to disk.
- URL pattern exclusion happens in recorder/exclusion.py. Payment pages
  (*/payment*, */pay*, */razorpay*, */stripe*) are excluded by default.
- The prompt is loaded from prompts/ by filename. Always use the latest
  versioned file. Never hardcode prompt text in llm/prompt_builder.py.
- extraction_confidence.ocr_used and low_confidence_fields must be
  populated for every step. The LLM prompt depends on these fields.

## Tech Stack
- Python 3.10+
- playwright (browser automation)
- pytesseract (OCR, optional)
- anthropic (LLM API)
- pytest (tests)

## Storage Layout
- storage/screenshots/   PNG files named step_001.png etc.
- storage/dom/           HTML snapshots named step_001.html etc.
- storage/ocr/           OCR text files named step_001_ocr.txt etc.
- benchmark/examples/    Journey JSON input files (no ground truth)
- benchmark/ground_truth/ Ground truth label files
- benchmark/run_logs/    Raw LLM output from each benchmark run
- prompts/               Versioned prompt .txt files
## Interactive Recording Mode (being added in current session)

A new --interactive flag is being added to audit.py that lets a human
auditor browse freely while the tool records automatically.

Key design rules for this mode:
- The browser MUST launch in headed/visible mode (headless=False).
  Never launch headless in interactive mode — the auditor needs to
  see and control the browser.
- Click capture uses JS injection via page.evaluate() after each
  navigation, NOT playwright's built-in click interception.
  Do not use page.on("request") or route interception for clicks.
- Store the last detected click as pending_action on the recorder
  instance. The NEXT navigation capture picks it up as user_action
  and clears it.
- Step counter increments on navigation only, not on every click.
  A click followed by a navigation = one step (the navigation step
  has the click as its user_action).
- Ctrl+C is the only way to stop interactive recording.
  Handle KeyboardInterrupt cleanly: stop the browser, build the
  journey, save the JSON, then exit.
- The exclusion check still applies in interactive mode.
  If the auditor navigates to a payment page URL matching
  config/exclusion_rules.py patterns, capture_excluded=True
  and NO screenshot or DOM is taken, same as URL-list mode.
- DO NOT auto-navigate anywhere in interactive mode.
  The recorder is passive — it only observes, never drives.

## What NOT to change when implementing interactive mode
- Do not modify journey/builder.py or any signals/ files.
  Interactive mode feeds into the same builder.add_step() pipeline.
- Do not change the output JSON schema.
  The journey JSON produced by interactive mode must be identical
  in structure to the URL-list mode output.
- Do not add new dependencies. Playwright already handles everything
  needed for click detection and navigation events.