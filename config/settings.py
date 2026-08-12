"""Central typed configuration (Layer-agnostic).

Every entry point resolves paths and pipeline behavior from config.yaml
through load_config() instead of hardcoding them. See config.yaml for the
field documentation.
"""

import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

import yaml

PIPELINE_MODES = ("ccpa", "mechanism", "both")

TOOL_VERSION = "0.1.0"

# The one place a filesystem path is allowed to be a literal: locating this
# repo's own root, relative to this file, so config.yaml (and any relative
# output.root) can be found regardless of the caller's CWD.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_CONFIG_FILENAME = "config.yaml"


class ConfigError(ValueError):
    """Raised when config.yaml fails validation."""


@dataclass(frozen=True)
class PipelineConfig:
    mode: str = "both"


@dataclass(frozen=True)
class PrivacyConfig:
    enabled: bool = True
    strict: bool = False
    # If True, unmasked screenshots are kept in a temp dir after session
    # end instead of being deleted (see recorder/masking/). Never affects
    # the episode folder itself -- raw artifacts never land there either way.
    keep_raw_artifacts: bool = False
    # None means "use the built-in defaults" (recorder/redaction.py's
    # SENSITIVE_PATTERNS, recorder/masking/patterns.py's
    # DEFAULT_QUERY_PARAM_DENYLIST) -- an explicit list here fully replaces
    # the built-in one, it does not merge with it.
    field_denylist: Optional[List[str]] = None
    query_param_denylist: Optional[List[str]] = None


@dataclass(frozen=True)
class CaptureConfig:
    screenshot_full_page: bool = True
    capture_network: bool = False


@dataclass(frozen=True)
class Goal:
    id: str
    description: str


DEFAULT_GOALS: List[Goal] = [
    Goal(
        "purchase_cheapest",
        "Find and complete purchase of the lowest-priced option that satisfies "
        "the target product/service.",
    ),
    Goal("complete_signup", "Complete an account registration/signup flow end to end."),
    Goal(
        "cancel_subscription",
        "Cancel an active subscription through the site's own cancellation flow.",
    ),
    Goal("reject_cookies", "Reject or decline all non-essential cookies via the consent banner."),
    Goal(
        "unsubscribe_email",
        "Unsubscribe from marketing emails via the site's unsubscribe flow.",
    ),
    Goal(
        "decline_addon",
        "Decline an upsell, add-on, or bundled offer presented during checkout or signup.",
    ),
]


@dataclass(frozen=True)
class RevisitConfig:
    offsets_hours: List[int] = field(default_factory=lambda: [24, 72])


@dataclass(frozen=True)
class OutputConfig:
    root: str = "storage"


@dataclass(frozen=True)
class PayloadConfig:
    # Root directory build-payload (llm/payload_builder.py) writes
    # payload/<episode_id>/<role>/... under. Separate from output.root
    # (episode storage) since these are throwaway, human-facing artifacts,
    # not part of the episode record itself.
    root: str = "payload"


@dataclass(frozen=True)
class BrowserProfilesConfig:
    # Root directory record.py's --profile <name> resolves a persistent
    # Chromium user-data-dir under (browser_profiles/<name>/) -- see
    # recorder/interactive_v2.py's launch(). Opt-in: with no --profile, a
    # session still gets a fresh, throwaway context exactly as before.
    # Reusing a named profile across sessions carries over real cookies/
    # localStorage/site-permission state (e.g. a Cloudflare "verified
    # human" clearance already earned in a prior session driven by the
    # SAME human operator) -- this is the same thing a real returning
    # visitor's browser does on its own, not fingerprint spoofing. Never
    # committed: gitignored, since a profile directory holds real session
    # data.
    root: str = "browser_profiles"


@dataclass(frozen=True)
class CostConfig:
    log_enabled: bool = False


@dataclass(frozen=True)
class AttributesConfig:
    # None = every agent in attribute_agents/registry.py is enabled (the
    # default). An explicit list of agent_ids restricts the runner to
    # exactly those -- see run_attributes.py / attribute_agents/registry.py.
    enabled_agents: Optional[List[str]] = None


@dataclass(frozen=True)
class Config:
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    goals: List[Goal] = field(default_factory=lambda: list(DEFAULT_GOALS))
    revisit: RevisitConfig = field(default_factory=RevisitConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    cost: CostConfig = field(default_factory=CostConfig)
    attributes: AttributesConfig = field(default_factory=AttributesConfig)
    payload: PayloadConfig = field(default_factory=PayloadConfig)
    browser_profiles: BrowserProfilesConfig = field(default_factory=BrowserProfilesConfig)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def default_config_path() -> str:
    return os.environ.get("DARK_PATTERN_CONFIG") or os.path.join(
        PROJECT_ROOT, _DEFAULT_CONFIG_FILENAME
    )


def resolve_path(path: str) -> str:
    """Resolves a config-supplied path against the project root if relative.

    Keeps "storage" (the documented default) meaning the same absolute
    directory regardless of which directory a script is launched from.
    """
    return path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)


def _require_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{field_name} must be a boolean, got {value!r}")
    return value


def _build_pipeline(raw: Dict[str, Any]) -> PipelineConfig:
    mode = raw.get("mode", PipelineConfig.mode)
    if mode not in PIPELINE_MODES:
        raise ConfigError(f"pipeline.mode must be one of {PIPELINE_MODES}, got {mode!r}")
    return PipelineConfig(mode=mode)


def _build_string_list(value: Any, field_name: str) -> Optional[List[str]]:
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise ConfigError(f"{field_name} must be a list of non-empty strings, got {value!r}")
    return list(value)


def _build_privacy(raw: Dict[str, Any]) -> PrivacyConfig:
    defaults = PrivacyConfig()
    return PrivacyConfig(
        enabled=_require_bool(raw.get("enabled", defaults.enabled), "privacy.enabled"),
        strict=_require_bool(raw.get("strict", defaults.strict), "privacy.strict"),
        keep_raw_artifacts=_require_bool(
            raw.get("keep_raw_artifacts", defaults.keep_raw_artifacts), "privacy.keep_raw_artifacts"
        ),
        field_denylist=_build_string_list(raw.get("field_denylist"), "privacy.field_denylist"),
        query_param_denylist=_build_string_list(
            raw.get("query_param_denylist"), "privacy.query_param_denylist"
        ),
    )


def _build_capture(raw: Dict[str, Any]) -> CaptureConfig:
    defaults = CaptureConfig()
    return CaptureConfig(
        screenshot_full_page=_require_bool(
            raw.get("screenshot_full_page", defaults.screenshot_full_page),
            "capture.screenshot_full_page",
        ),
        capture_network=_require_bool(
            raw.get("capture_network", defaults.capture_network), "capture.capture_network"
        ),
    )


def _build_goals(raw: Optional[List[Dict[str, Any]]]) -> List[Goal]:
    if raw is None:
        return list(DEFAULT_GOALS)

    goals: List[Goal] = []
    seen_ids = set()
    for entry in raw:
        goal_id = entry.get("id") if isinstance(entry, dict) else None
        description = entry.get("description") if isinstance(entry, dict) else None
        if not goal_id or not isinstance(goal_id, str):
            raise ConfigError(f"every goal needs a non-empty string id, got {entry!r}")
        if not description or not isinstance(description, str):
            raise ConfigError(f"goal {goal_id!r} needs a non-empty string description")
        if goal_id in seen_ids:
            raise ConfigError(f"duplicate goal id: {goal_id!r}")
        seen_ids.add(goal_id)
        goals.append(Goal(id=goal_id, description=description))
    return goals


def _build_revisit(raw: Dict[str, Any]) -> RevisitConfig:
    offsets = raw.get("offsets_hours", [24, 72])
    if not isinstance(offsets, list) or not offsets:
        raise ConfigError(f"revisit.offsets_hours must be a non-empty list, got {offsets!r}")
    for offset in offsets:
        if not isinstance(offset, int) or isinstance(offset, bool) or offset <= 0:
            raise ConfigError(
                f"revisit.offsets_hours entries must be positive integers, got {offset!r}"
            )
    return RevisitConfig(offsets_hours=list(offsets))


def _build_output(raw: Dict[str, Any]) -> OutputConfig:
    root = raw.get("root", OutputConfig.root)
    if not isinstance(root, str) or not root:
        raise ConfigError(f"output.root must be a non-empty string, got {root!r}")
    return OutputConfig(root=root)


def _build_payload(raw: Dict[str, Any]) -> PayloadConfig:
    root = raw.get("root", PayloadConfig.root)
    if not isinstance(root, str) or not root:
        raise ConfigError(f"payload.root must be a non-empty string, got {root!r}")
    return PayloadConfig(root=root)


def _build_browser_profiles(raw: Dict[str, Any]) -> BrowserProfilesConfig:
    root = raw.get("root", BrowserProfilesConfig.root)
    if not isinstance(root, str) or not root:
        raise ConfigError(f"browser_profiles.root must be a non-empty string, got {root!r}")
    return BrowserProfilesConfig(root=root)


def _build_cost(raw: Dict[str, Any]) -> CostConfig:
    defaults = CostConfig()
    return CostConfig(
        log_enabled=_require_bool(raw.get("log_enabled", defaults.log_enabled), "cost.log_enabled")
    )


def _build_attributes(raw: Dict[str, Any]) -> AttributesConfig:
    return AttributesConfig(
        enabled_agents=_build_string_list(raw.get("enabled_agents"), "attributes.enabled_agents")
    )


def load_config(path: Optional[str] = None) -> Config:
    """Loads and validates config.yaml into a typed, immutable Config.

    Resolution order for `path`: explicit argument > DARK_PATTERN_CONFIG env
    var > <project_root>/config.yaml. A missing file is not an error --
    every section falls back to its documented default, so the loader only
    ever hardcodes *where to look*, never a runtime value.
    """
    resolved_path = path or default_config_path()

    raw: Dict[str, Any] = {}
    if os.path.isfile(resolved_path):
        with open(resolved_path, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
        if loaded:
            if not isinstance(loaded, dict):
                raise ConfigError(f"{resolved_path} must contain a YAML mapping at the top level")
            raw = loaded

    return Config(
        pipeline=_build_pipeline(raw.get("pipeline") or {}),
        privacy=_build_privacy(raw.get("privacy") or {}),
        capture=_build_capture(raw.get("capture") or {}),
        goals=_build_goals(raw.get("goals")),
        revisit=_build_revisit(raw.get("revisit") or {}),
        output=_build_output(raw.get("output") or {}),
        cost=_build_cost(raw.get("cost") or {}),
        attributes=_build_attributes(raw.get("attributes") or {}),
        payload=_build_payload(raw.get("payload") or {}),
        browser_profiles=_build_browser_profiles(raw.get("browser_profiles") or {}),
    )
