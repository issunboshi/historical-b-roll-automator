"""
Wikipedia disambiguation module for B-Roll automation.

This module provides intelligent disambiguation when Wikipedia searches return
multiple potential matches. Uses Claude structured outputs to select the
contextually correct article based on transcript context, with confidence
scoring to enable auto-acceptance of high-confidence matches.

Key Features:
1. Multi-candidate Wikipedia search (top 3 results per query)
2. Disambiguation page detection via MediaWiki pageprops API
3. LLM-powered candidate selection with confidence scoring (0-10)
4. Depth-limited disambiguation resolution (max 3 attempts)
5. Caching for Wikipedia lookups (7-day TTL)

Usage:
    from src.core.disambiguation import (
        disambiguate_search_results,
        DisambiguationDecision,
        CandidateInfo
    )

    decision = disambiguate_search_results(
        entity_name="Michael Jordan",
        entity_type="people",
        transcript_context="basketball player from the 1990s",
        video_topic="NBA History",
        search_results=[...],
        session=requests_session,
        client=anthropic_client,
        cache=diskcache_instance
    )
"""
from __future__ import annotations

import sys
from typing import List, Optional, Tuple

import requests
from anthropic import Anthropic
from diskcache import Cache
from tenacity import retry, stop_after_attempt, wait_exponential
import wikipediaapi

from src.models.disambiguation import (
    CandidateInfo,
    DisambiguationDecision,
    DisambiguationReviewEntry,
)

# =============================================================================
# Constants
# =============================================================================

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "B-Roll-Finder/1.0 (automated Wikipedia disambiguation)"


# =============================================================================
# Quality Tracking and Confidence Routing
# =============================================================================


def derive_match_quality(confidence: int, disambiguation_source: str = "") -> str:
    """Derive match_quality from confidence score and source.

    Per QUAL-01 through QUAL-05:
    - high: confidence >= 7 (clear disambiguation or single result)
    - medium: confidence 4-6 (successful with moderate confidence)
    - low: confidence 1-3 (uncertain but got some result)
    - none: confidence 0 (no match found)

    Args:
        confidence: Confidence score 0-10
        disambiguation_source: Source of disambiguation (for context, not used in logic)

    Returns:
        Match quality string: "high", "medium", "low", or "none"

    Example:
        >>> derive_match_quality(8)
        'high'
        >>> derive_match_quality(5)
        'medium'
        >>> derive_match_quality(2)
        'low'
        >>> derive_match_quality(0)
        'none'
    """
    if confidence >= 7:
        return "high"
    elif confidence >= 4:
        return "medium"
    elif confidence >= 1:
        return "low"
    else:
        return "none"


def apply_confidence_routing(
    decision: DisambiguationDecision,
    entity_name: str,
    entity_type: str,
    candidates: List[CandidateInfo],
    transcript_context: str,
    video_topic: str,
) -> Tuple[str, Optional[DisambiguationReviewEntry]]:
    """Route entity based on disambiguation confidence.

    Returns: (action, review_entry)
    - action is one of: "download", "flag_and_download", "skip"
    - review_entry is populated only for "flag_and_download"

    Per CONTEXT.md decisions:
    - Confidence 7+: auto-accept, proceed with download -> ("download", None)
    - Confidence 4-6: flag as "needs review" but still use -> ("flag_and_download", entry)
    - Confidence 0-3: skip entity, mark as "no match" -> ("skip", None)

    Args:
        decision: DisambiguationDecision from LLM
        entity_name: Original entity name
        entity_type: Entity type (people, events, places, organizations, concepts)
        candidates: List of CandidateInfo objects considered
        transcript_context: Context from transcript
        video_topic: Video topic for disambiguation

    Returns:
        Tuple of (action, review_entry or None)
    """
    if decision.confidence >= 7:
        # High confidence - auto-accept
        return ("download", None)

    elif decision.confidence >= 4:
        # Medium confidence - flag for review but still use
        review_entry = DisambiguationReviewEntry(
            entity_name=entity_name,
            entity_type=entity_type,
            candidates=[
                {"title": c.title, "summary": c.summary, "categories": c.categories}
                for c in candidates
            ],
            chosen_article=decision.chosen_article,
            confidence=decision.confidence,
            rationale=decision.rationale,
            transcript_context=transcript_context,
            video_topic=video_topic,
            match_quality=decision.match_quality,
        )
        return ("flag_and_download", review_entry)

    else:
        # Low confidence or no match - skip
        return ("skip", None)


def log_disambiguation_decision(
    entity_name: str, decision: DisambiguationDecision, action: str
) -> None:
    """Log disambiguation decision per QUAL-07.

    Logs: entity name, candidates considered, chosen article,
    confidence score, rationale, action taken.

    Args:
        entity_name: Entity being disambiguated
        decision: DisambiguationDecision from LLM
        action: Action taken (download, flag_and_download, skip)
    """
    print(
        f"[Disambiguation] {entity_name} -> {decision.chosen_article or 'NO MATCH'} "
        f"(confidence: {decision.confidence}, quality: {decision.match_quality}, action: {action})",
        file=sys.stderr,
    )
    if decision.candidates_considered:
        print(
            f"  Candidates: {', '.join(decision.candidates_considered)}", file=sys.stderr
        )
    if decision.rationale:
        print(f"  Rationale: {decision.rationale}", file=sys.stderr)


def process_disambiguation_result(
    decision: DisambiguationDecision,
    entity_name: str,
    entity_type: str,
    candidates: List[CandidateInfo],
    transcript_context: str,
    video_topic: str,
    review_entries: List[DisambiguationReviewEntry],
) -> dict:
    """Process disambiguation decision into entity metadata.

    Returns dict with:
    - wikipedia_title: Selected article or None
    - disambiguation_source: How article was selected
    - confidence: 0-10 score
    - match_quality: high/medium/low/none
    - rationale: LLM explanation
    - candidates_considered: All evaluated titles
    - action: download/flag_and_download/skip

    Also appends to review_entries if flagged for review.

    Args:
        decision: DisambiguationDecision from LLM
        entity_name: Original entity name
        entity_type: Entity type (people, events, places, organizations, concepts)
        candidates: List of CandidateInfo objects considered
        transcript_context: Context from transcript
        video_topic: Video topic for disambiguation
        review_entries: List to append review entry to (modified in place)

    Returns:
        Dict with disambiguation metadata for entity
    """
    # Apply confidence routing
    action, review_entry = apply_confidence_routing(
        decision,
        entity_name,
        entity_type,
        candidates,
        transcript_context,
        video_topic,
    )

    # If flagged for review, add to review entries list
    if review_entry is not None:
        review_entries.append(review_entry)

    # Log decision
    log_disambiguation_decision(entity_name, decision, action)

    # Build metadata dict
    metadata = {
        "wikipedia_title": decision.chosen_article if decision.chosen_article else None,
        "disambiguation_source": "llm_disambiguation",
        "confidence": decision.confidence,
        "match_quality": decision.match_quality,
        "rationale": decision.rationale,
        "candidates_considered": decision.candidates_considered,
        "action": action,
    }

    return metadata


# =============================================================================
# Wikipedia API Functions
# =============================================================================


def search_wikipedia_candidates(
    session: requests.Session, query: str, limit: int = 3
) -> List[dict]:
    """Search Wikipedia and return top N candidates.

    Uses MediaWiki API with srlimit parameter to fetch multiple search results.

    Args:
        session: requests.Session for connection pooling
        query: Search query (entity name or search strategy)
        limit: Maximum number of candidates to return (default 3)

    Returns:
        List of dicts with keys: pageid, title, snippet

    Raises:
        requests.HTTPError: On API failures
    """
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": limit,
        "srprop": "snippet",
        "format": "json",
        "formatversion": 2,
        "utf8": 1,
        "maxlag": 5,
    }

    resp = session.get(
        WIKIPEDIA_API,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    results = data.get("query", {}).get("search", [])
    return [
        {
            "pageid": r.get("pageid"),
            "title": r.get("title"),
            "snippet": r.get("snippet", ""),
        }
        for r in results
    ]


def is_disambiguation_page(session: requests.Session, title: str) -> bool:
    """Check if page is a disambiguation page using pageprops API.

    CRITICAL: The 'disambiguation' property is an EMPTY STRING when present.
    Must check key existence ("disambiguation" in pageprops), NOT value truthiness.

    Args:
        session: requests.Session for connection pooling
        title: Wikipedia article title to check

    Returns:
        True if page is a disambiguation page, False otherwise
    """
    params = {
        "action": "query",
        "titles": title,
        "prop": "pageprops",
        "ppprop": "disambiguation",
        "format": "json",
        "formatversion": 2,
    }

    resp = session.get(
        WIKIPEDIA_API,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    pages = data.get("query", {}).get("pages", [])
    if not pages:
        return False

    page = pages[0]
    pageprops = page.get("pageprops", {})

    # Key insight: disambiguation prop is EMPTY STRING when present
    # Must check key existence, not value truthiness
    return "disambiguation" in pageprops


def extract_disambiguation_links(
    session: requests.Session, title: str, limit: int = 5
) -> List[str]:
    """Extract article links from a disambiguation page.

    Uses prop=links with plnamespace=0 (main namespace only) to get
    article links from a disambiguation page.

    Args:
        session: requests.Session for connection pooling
        title: Disambiguation page title
        limit: Maximum number of links to extract (default 5)

    Returns:
        List of article titles linked from the disambiguation page
    """
    params = {
        "action": "query",
        "titles": title,
        "prop": "links",
        "pllimit": limit * 2,  # Fetch extra to allow filtering
        "plnamespace": 0,  # Main namespace only (articles)
        "format": "json",
        "formatversion": 2,
    }

    resp = session.get(
        WIKIPEDIA_API,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    pages = data.get("query", {}).get("pages", [])
    if not pages:
        return []

    links = pages[0].get("links", [])
    return [link["title"] for link in links[:limit]]


def fetch_candidate_info(
    titles: List[str], cache: Cache, cache_ttl: int = 7 * 24 * 3600
) -> List[CandidateInfo]:
    """Fetch summaries and categories for Wikipedia candidates.

    Uses Wikipedia-API library for summaries and categories.
    Caches results with 7-day TTL to reduce API load.

    Args:
        titles: List of Wikipedia article titles
        cache: DiskCache instance for persistent caching
        cache_ttl: Cache time-to-live in seconds (default 7 days)

    Returns:
        List of CandidateInfo objects with summary and categories
    """
    wiki = wikipediaapi.Wikipedia(user_agent=USER_AGENT, language="en")

    candidates = []
    for title in titles:
        # Check cache first
        cache_key = f"candidate:{title}"
        cached = cache.get(cache_key)
        if cached is not None:
            candidates.append(CandidateInfo(**cached))
            continue

        # Fetch from Wikipedia
        page = wiki.page(title)
        if not page.exists():
            continue

        info = CandidateInfo(
            title=page.title,
            summary=page.summary[:500],  # First 500 chars
            categories=list(page.categories.keys())[:5],
        )

        # Cache result
        cache.set(cache_key, info.model_dump(), expire=cache_ttl)
        candidates.append(info)

    return candidates


# =============================================================================
# LLM Disambiguation with Structured Outputs
# =============================================================================


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
def disambiguate_entity(
    entity_name: str,
    entity_type: str,
    transcript_context: str,
    candidates: List[CandidateInfo],
    video_topic: str,
    client: Anthropic,
) -> DisambiguationDecision:
    """Use Claude to select best Wikipedia candidate.

    Uses Claude Sonnet 4.5 with structured outputs (beta) to select the
    best matching Wikipedia article from multiple candidates. Includes
    explicit confidence rubric in prompt for reliable scoring.

    Args:
        entity_name: Original entity name from transcript
        entity_type: Entity type (people, events, places, organizations, concepts)
        transcript_context: Context from transcript where entity appears
        candidates: List of CandidateInfo objects to choose from
        video_topic: Video topic/title for disambiguation hints
        client: Anthropic API client instance

    Returns:
        DisambiguationDecision with chosen article and confidence score

    Raises:
        anthropic.APIError: On API failures (retried 3x with exponential backoff)
    """
    # Format candidates for prompt
    candidate_text = "\n\n".join(
        [
            f"Candidate {i+1}: {c.title}\n"
            f"Summary: {c.summary}\n"
            f"Categories: {', '.join(c.categories[:5])}"
            for i, c in enumerate(candidates)
        ]
    )

    prompt = f"""Video topic: {video_topic}

Entity to disambiguate: {entity_name} (type: {entity_type})

Transcript context where entity appears:
"{transcript_context}"

Wikipedia candidates:
{candidate_text}

Select the best matching Wikipedia article for this entity.

Confidence rubric:
- 8-10: Clear match, article directly about the entity in this context
- 5-7: Likely match but some ambiguity remains
- 2-4: Uncertain, multiple candidates could fit
- 0-1: No good match found

Match quality guidelines:
- high: Single obvious match or confident disambiguation (confidence >= 7)
- medium: Successful disambiguation with moderate confidence (4-6)
- low: All strategies uncertain but got some result (confidence 1-3)
- none: No match found (confidence 0)

Consider:
1. Does the candidate summary match the transcript context?
2. Is the entity type consistent (person mentioned in transcript should match person article)?
3. Does the video topic provide disambiguation hints?"""

    response = client.beta.messages.parse(
        model="claude-sonnet-4-5-20250929",
        max_tokens=1024,
        betas=["structured-outputs-2025-11-13"],
        messages=[{"role": "user", "content": prompt}],
        output_format=DisambiguationDecision,
    )

    return response.parsed_output


# =============================================================================
# Depth-Limited Disambiguation Resolution
# =============================================================================


def resolve_disambiguation(
    session: requests.Session,
    entity_name: str,
    entity_type: str,
    initial_title: str,
    transcript_context: str,
    video_topic: str,
    client: Anthropic,
    cache: Cache,
    max_depth: int = 3,
    current_depth: int = 0,
) -> Optional[DisambiguationDecision]:
    """Resolve disambiguation page with depth limit.

    Recursively resolves disambiguation pages by extracting linked articles
    and running LLM disambiguation on them. Enforces max_depth to prevent
    infinite loops (CONTEXT.md: max 3 attempts).

    Args:
        session: requests.Session for Wikipedia API calls
        entity_name: Original entity name from transcript
        entity_type: Entity type (people, events, places, organizations, concepts)
        initial_title: Wikipedia article title to check/resolve
        transcript_context: Context from transcript where entity appears
        video_topic: Video topic/title for disambiguation hints
        client: Anthropic API client instance
        cache: DiskCache instance for caching
        max_depth: Maximum disambiguation attempts (default 3 per CONTEXT.md)
        current_depth: Current recursion depth (internal use)

    Returns:
        DisambiguationDecision or None if all attempts failed
    """
    if current_depth >= max_depth:
        print(f"Max disambiguation depth reached for {entity_name}", file=sys.stderr)
        return None

    # Check if this is a disambiguation page
    if not is_disambiguation_page(session, initial_title):
        # Not a disambiguation page - return as valid result
        return DisambiguationDecision(
            entity_name=entity_name,
            chosen_article=initial_title,
            confidence=7,  # Single result, moderate confidence
            rationale="Direct match, not a disambiguation page",
            match_quality="medium",
            candidates_considered=[initial_title],
        )

    # Extract links from disambiguation page
    linked_titles = extract_disambiguation_links(session, initial_title, limit=5)

    if not linked_titles:
        print(f"No links found on disambiguation page: {initial_title}", file=sys.stderr)
        return None

    # Filter out nested disambiguation pages
    valid_titles = []
    for title in linked_titles:
        if is_disambiguation_page(session, title):
            # Skip nested disambiguation pages
            print(f"Skipping nested disambiguation page: {title}", file=sys.stderr)
            continue
        valid_titles.append(title)

    if not valid_titles:
        print(
            f"All linked pages are disambiguation pages for: {entity_name}",
            file=sys.stderr,
        )
        return None

    # Fetch summaries for valid candidates
    candidates = fetch_candidate_info(valid_titles, cache)

    if not candidates:
        print(f"No valid candidates found for: {entity_name}", file=sys.stderr)
        return None

    # Use LLM to select best candidate
    decision = disambiguate_entity(
        entity_name=entity_name,
        entity_type=entity_type,
        transcript_context=transcript_context,
        candidates=candidates,
        video_topic=video_topic,
        client=client,
    )

    # Recursively check if chosen article is also a disambiguation page
    if is_disambiguation_page(session, decision.chosen_article):
        return resolve_disambiguation(
            session,
            entity_name,
            entity_type,
            decision.chosen_article,
            transcript_context,
            video_topic,
            client,
            cache,
            max_depth,
            current_depth + 1,
        )

    return decision


# =============================================================================
# Main Disambiguation Entry Point
# =============================================================================


def disambiguate_search_results(
    entity_name: str,
    entity_type: str,
    transcript_context: str,
    video_topic: str,
    search_results: List[dict],
    session: requests.Session,
    client: Anthropic,
    cache: Cache,
) -> DisambiguationDecision:
    """Main entry point for disambiguation.

    Handles three scenarios:
    1. Single result: check if disambiguation page, return moderate confidence
    2. Multiple results: run full LLM disambiguation
    3. Disambiguation page: resolve with depth limit

    Args:
        entity_name: Original entity name from transcript
        entity_type: Entity type (people, events, places, organizations, concepts)
        transcript_context: Context from transcript where entity appears
        video_topic: Video topic/title for disambiguation hints
        search_results: List of search results from search_wikipedia_candidates
        session: requests.Session for Wikipedia API calls
        client: Anthropic API client instance
        cache: DiskCache instance for caching

    Returns:
        DisambiguationDecision with chosen article and confidence
    """
    if not search_results:
        # No results found
        return DisambiguationDecision(
            entity_name=entity_name,
            chosen_article="",
            confidence=0,
            rationale="No Wikipedia search results found",
            match_quality="none",
            candidates_considered=[],
        )

    if len(search_results) == 1:
        # Single result - check if disambiguation page
        title = search_results[0]["title"]
        if is_disambiguation_page(session, title):
            # Resolve disambiguation page
            decision = resolve_disambiguation(
                session,
                entity_name,
                entity_type,
                title,
                transcript_context,
                video_topic,
                client,
                cache,
            )
            if decision:
                return decision
            else:
                # Disambiguation resolution failed
                return DisambiguationDecision(
                    entity_name=entity_name,
                    chosen_article="",
                    confidence=0,
                    rationale="Disambiguation page resolution failed",
                    match_quality="none",
                    candidates_considered=[title],
                )
        else:
            # Single non-disambiguation result
            return DisambiguationDecision(
                entity_name=entity_name,
                chosen_article=title,
                confidence=7,  # Moderate confidence for single result
                rationale="Single search result, not a disambiguation page",
                match_quality="medium",
                candidates_considered=[title],
            )

    # Multiple candidates - run disambiguation
    titles = [r["title"] for r in search_results]
    candidates = fetch_candidate_info(titles, cache)

    if not candidates:
        return DisambiguationDecision(
            entity_name=entity_name,
            chosen_article="",
            confidence=0,
            rationale="No valid candidates after fetching summaries",
            match_quality="none",
            candidates_considered=titles,
        )

    decision = disambiguate_entity(
        entity_name=entity_name,
        entity_type=entity_type,
        transcript_context=transcript_context,
        candidates=candidates,
        video_topic=video_topic,
        client=client,
    )

    return decision
