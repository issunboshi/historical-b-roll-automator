"""
Core business logic for B-Roll Finder.

This module contains the main business logic, separated from CLI and API concerns.
"""

from src.core.disambiguation import (
    WIKIPEDIA_API,
    USER_AGENT,
    disambiguate_search_results,
    disambiguate_entity,
    search_wikipedia_candidates,
    is_disambiguation_page,
    extract_disambiguation_links,
    fetch_candidate_info,
    resolve_disambiguation,
    derive_match_quality,
    apply_confidence_routing,
    log_disambiguation_decision,
    process_disambiguation_result,
)
from src.core.executor import (
    STEPS,
    PipelineExecutor,
    StepResult,
)
from src.core.review import (
    write_review_file,
    load_overrides,
    get_override,
    create_override_entry,
)

__all__ = [
    # Constants
    "WIKIPEDIA_API",
    "USER_AGENT",
    "STEPS",
    # Main disambiguation functions
    "disambiguate_search_results",
    "disambiguate_entity",
    "search_wikipedia_candidates",
    "is_disambiguation_page",
    "extract_disambiguation_links",
    "fetch_candidate_info",
    "resolve_disambiguation",
    # Quality and routing
    "derive_match_quality",
    "apply_confidence_routing",
    "log_disambiguation_decision",
    "process_disambiguation_result",
    # Pipeline executor
    "PipelineExecutor",
    "StepResult",
    # Review and override
    "write_review_file",
    "load_overrides",
    "get_override",
    "create_override_entry",
]
