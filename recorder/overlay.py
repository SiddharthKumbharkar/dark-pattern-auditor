"""Builds the init-script injected into every document of an interactive-v2
recording session (Layer 1): the always-visible overlay UI, the
click/input-commit/submit/scroll trigger listeners, and the command queue
the overlay's buttons write to.

This is handed to Page.add_init_script(), which Playwright re-runs before
any page script on every new document -- including full navigations and
SPA route changes -- so the listeners and overlay survive without any
Python-side re-attachment logic. See recorder/interactive_v2.py for how the
two JS-side queues this script creates are drained.

Queues/channels this script creates on `window`:
  window.name              -- JSON of the single most recent trigger,
                               overwritten each time. Browser tabs keep
                               window.name across a same-tab navigation
                               (unlike ordinary JS globals), so a trigger
                               that leads directly to a navigation survives
                               into the new document as that navigation's
                               step action.
  window.__dpaTriggers__   -- array of every trigger since the last drain,
                               for triggers that do NOT lead to a
                               navigation (each becomes its own step).
  window.__dpaCommands__   -- array of overlay button commands
                               (mark_goal_achieved/abandon/add_note/
                               end_session) since the last drain.

Debouncing: click/input/submit triggers are inherently one-shot (one JS
event -> one pushAction call, then drained-and-cleared by Python, so
nothing can be captured twice). Scroll is the one interaction type that
needs an actual time-based debounce (a scroll gesture fires dozens of
'scroll' events), implemented below with a 500ms settle timer plus a
significance threshold (>50% of viewport height moved).
"""

import json

from recorder.redaction import SENSITIVE_FIELD_TYPES, SENSITIVE_PATTERNS

_TEMPLATE = r"""
(() => {
  if (window.__dpaInitialized__) return;
  window.__dpaInitialized__ = true;
  window.__dpaTriggers__ = [];
  window.__dpaCommands__ = [];
  window.name = window.name || '';

  const GOAL_TEXT = __GOAL_JSON__;
  const SENSITIVE_PATTERNS = __SENSITIVE_PATTERNS_JSON__;
  const SENSITIVE_FIELD_TYPES = __SENSITIVE_FIELD_TYPES_JSON__;
  const TEXT_LIKE_INPUT_TYPES = ['text', 'email', 'password', 'tel', 'number', 'url', 'search',
    'date', 'datetime-local', 'month', 'week', 'time', ''];

  function isSensitiveField(name, type, autocomplete, placeholder) {
    // placeholder matters because many real-world (esp. React-controlled)
    // inputs carry no name/id/autocomplete at all -- placeholder text
    // ("Full name", "PIN code") is often the only semantic signal there is.
    const n = (name || '').toLowerCase();
    const t = (type || '').toLowerCase();
    const a = (autocomplete || '').toLowerCase();
    const p = (placeholder || '').toLowerCase();
    if (SENSITIVE_FIELD_TYPES.indexOf(t) !== -1) return true;
    return SENSITIVE_PATTERNS.some((pat) => n.indexOf(pat) !== -1 || a.indexOf(pat) !== -1 || p.indexOf(pat) !== -1);
  }

  function cssSelector(el) {
    if (!el || el.nodeType !== 1) return null;
    if (el.id) return '#' + el.id;
    const parts = [];
    let node = el;
    let depth = 0;
    while (node && node.nodeType === 1 && depth < 4) {
      let part = node.tagName.toLowerCase();
      if (node.classList && node.classList.length) {
        part += '.' + Array.from(node.classList).slice(0, 2).join('.');
      } else if (node.parentElement) {
        const siblings = Array.from(node.parentElement.children).filter((c) => c.tagName === node.tagName);
        if (siblings.length > 1) part += ':nth-of-type(' + (siblings.indexOf(node) + 1) + ')';
      }
      parts.unshift(part);
      node = node.parentElement;
      depth += 1;
    }
    return parts.join(' > ');
  }

  function boundingBox(el) {
    try {
      const r = el.getBoundingClientRect();
      return { x: r.x, y: r.y, width: r.width, height: r.height };
    } catch (e) {
      return null;
    }
  }

  function isInsideOverlay(el) {
    return !!(el && el.closest && el.closest('[data-dpa-overlay]'));
  }

  function pushAction(action) {
    window.name = JSON.stringify(action);
    window.__dpaTriggers__.push(action);
  }

  // -- click --
  // A click landing directly on a text-entry field would otherwise expose
  // that field's current value via el.value (e.g. clicking to re-focus a
  // password/card field that already has characters typed into it) -- so
  // for a click on a sensitive field, targetText is withheld entirely
  // rather than captured and redacted after the fact.
  document.addEventListener('click', (event) => {
    const el = event.target;
    if (isInsideOverlay(el)) return;

    const isField = el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA');
    let text = '';
    let redacted = false;
    if (isField) {
      const name = el.getAttribute('name') || el.id || '';
      const type = el.getAttribute('type') || 'text';
      const autocomplete = el.getAttribute('autocomplete') || '';
      const placeholder = el.getAttribute('placeholder') || '';
      if (isSensitiveField(name, type, autocomplete, placeholder)) {
        redacted = true;
      } else {
        text = (el.value || '').trim().slice(0, 100);
      }
    } else {
      text = ((el && el.innerText) || '').trim().slice(0, 100);
    }
    const role = (el && (el.getAttribute('role') || el.tagName)) || '';
    pushAction({
      type: 'click',
      selector: cssSelector(el),
      boundingBox: boundingBox(el),
      targetText: text || null,
      targetRole: role || null,
      inputRedacted: redacted,
    });
  }, true);

  // -- input commit: on blur or Enter, never per-keystroke --
  function isFormField(el) {
    if (!el) return false;
    if (el.tagName === 'TEXTAREA' || el.tagName === 'SELECT') return true;
    if (el.tagName === 'INPUT') {
      const t = (el.getAttribute('type') || 'text').toLowerCase();
      return TEXT_LIKE_INPUT_TYPES.indexOf(t) !== -1;
    }
    return false;
  }

  function commitInput(el) {
    if (!el || isInsideOverlay(el)) return;
    const name = el.getAttribute('name') || el.id || '';
    const type = el.getAttribute('type') || el.tagName.toLowerCase();
    const autocomplete = el.getAttribute('autocomplete') || '';
    const placeholder = el.getAttribute('placeholder') || '';
    pushAction({
      type: 'input',
      selector: cssSelector(el),
      boundingBox: boundingBox(el),
      targetText: null,
      targetRole: type || null,
      inputRedacted: isSensitiveField(name, type, autocomplete, placeholder),
    });
  }

  document.addEventListener('focusout', (event) => {
    if (isFormField(event.target)) commitInput(event.target);
  }, true);

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && isFormField(event.target) && event.target.tagName !== 'TEXTAREA') {
      commitInput(event.target);
    }
  }, true);

  // -- form submit --
  document.addEventListener('submit', (event) => {
    const el = event.target;
    if (isInsideOverlay(el)) return;
    pushAction({
      type: 'submit',
      selector: cssSelector(el),
      boundingBox: boundingBox(el),
      targetText: null,
      targetRole: 'FORM',
      inputRedacted: false,
    });
  }, true);

  // -- significant, debounced scroll (>50% viewport height, 500ms settle) --
  let scrollBaseline = window.scrollY;
  let scrollTimer = null;
  window.addEventListener('scroll', () => {
    if (scrollTimer) clearTimeout(scrollTimer);
    scrollTimer = setTimeout(() => {
      const delta = Math.abs(window.scrollY - scrollBaseline);
      if (delta > window.innerHeight * 0.5) {
        pushAction({
          type: 'scroll',
          selector: null,
          boundingBox: null,
          targetText: null,
          targetRole: null,
          inputRedacted: false,
        });
        scrollBaseline = window.scrollY;
      }
    }, 500);
  }, true);

  // -- always-visible overlay --
  function buildOverlay() {
    if (document.getElementById('__dpa_overlay__')) return;
    const btnStyle = 'font:inherit;padding:4px 8px;border-radius:4px;border:1px solid #374151;' +
      'background:#1f2937;color:#e5e7eb;cursor:pointer;';
    const box = document.createElement('div');
    box.id = '__dpa_overlay__';
    box.setAttribute('data-dpa-overlay', 'true');
    box.style.cssText = 'position:fixed;bottom:12px;right:12px;z-index:2147483647;' +
      'background:#111827;color:#e5e7eb;font:12px/1.4 -apple-system,sans-serif;' +
      'padding:10px 12px;border-radius:8px;box-shadow:0 4px 16px rgba(0,0,0,.4);max-width:280px;' +
      'max-height:calc(100vh - 24px);overflow-y:auto;box-sizing:border-box;';
    box.innerHTML =
      '<div style="font-weight:600;margin-bottom:4px;">Dark Pattern Recorder</div>' +
      '<div>Goal: <span id="__dpa_goal__"></span></div>' +
      '<div>Steps: <span id="__dpa_step_count__">0</span></div>' +
      '<div id="__dpa_note_row__" style="display:none;margin-top:6px;">' +
      '<input id="__dpa_note_input__" type="text" placeholder="note... (Enter to save)" ' +
      'style="width:100%;box-sizing:border-box;font:inherit;padding:3px;border-radius:4px;' +
      'border:1px solid #374151;background:#1f2937;color:#e5e7eb;" /></div>' +
      '<div style="margin-top:6px;display:flex;gap:4px;flex-wrap:wrap;">' +
      '<button type="button" data-dpa-btn="achieved" style="' + btnStyle + '">Mark goal achieved</button>' +
      '<button type="button" data-dpa-btn="abandon" style="' + btnStyle + '">Abandon</button>' +
      '<button type="button" data-dpa-btn="note" style="' + btnStyle + '">Add note</button>' +
      '<button type="button" data-dpa-btn="end" style="' + btnStyle + '">End session</button>' +
      '</div>';
    document.documentElement.appendChild(box);
    document.getElementById('__dpa_goal__').textContent = GOAL_TEXT;

    box.querySelectorAll('[data-dpa-btn]').forEach((btn) => {
      btn.addEventListener('click', (event) => {
        event.stopPropagation();
        const kind = btn.getAttribute('data-dpa-btn');
        if (kind === 'note') {
          const row = document.getElementById('__dpa_note_row__');
          const showing = row.style.display !== 'none';
          row.style.display = showing ? 'none' : 'block';
          if (!showing) document.getElementById('__dpa_note_input__').focus();
          return;
        }
        if (kind === 'achieved') window.__dpaCommands__.push({ type: 'mark_goal_achieved', timestamp: Date.now() });
        if (kind === 'abandon') window.__dpaCommands__.push({ type: 'abandon', timestamp: Date.now() });
        if (kind === 'end') window.__dpaCommands__.push({ type: 'end_session', timestamp: Date.now() });
      });
    });

    document.getElementById('__dpa_note_input__').addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        const value = event.target.value.trim();
        if (value) window.__dpaCommands__.push({ type: 'add_note', note: value, timestamp: Date.now() });
        event.target.value = '';
        document.getElementById('__dpa_note_row__').style.display = 'none';
      }
    });
  }

  window.__dpaSetStepCount__ = function (n) {
    const el = document.getElementById('__dpa_step_count__');
    if (el) el.textContent = String(n);
  };

  if (document.body) {
    buildOverlay();
  } else {
    document.addEventListener('DOMContentLoaded', buildOverlay);
  }
})();
"""


def build_injection_script(goal_description: str) -> str:
    """Renders the init-script for one recording session. goal_description
    is baked in per-session (the overlay is static text, no live re-render
    of the goal itself is needed since it never changes mid-session)."""
    script = _TEMPLATE
    script = script.replace("__GOAL_JSON__", json.dumps(goal_description or ""))
    script = script.replace("__SENSITIVE_PATTERNS_JSON__", json.dumps(SENSITIVE_PATTERNS))
    script = script.replace("__SENSITIVE_FIELD_TYPES_JSON__", json.dumps(SENSITIVE_FIELD_TYPES))
    return script
