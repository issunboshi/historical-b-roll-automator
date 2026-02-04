"""
Disambiguation API endpoints.

Provides REST access to the Wikipedia disambiguation functionality.
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.models.disambiguation import (
    CandidateInfo,
    DisambiguationDecision,
    DisambiguationRequest,
    DisambiguationResponse,
)

router = APIRouter()


class SearchCandidatesRequest(BaseModel):
    """Request to search for Wikipedia candidates."""

    query: str = Field(description="Search query")
    limit: int = Field(default=3, ge=1, le=10, description="Maximum results")


class SearchCandidatesResponse(BaseModel):
    """Response with Wikipedia search candidates."""

    query: str
    candidates: list[dict]
    count: int


@router.post("/disambiguate", response_model=DisambiguationResponse)
async def disambiguate_entity(request: DisambiguationRequest) -> DisambiguationResponse:
    """Disambiguate a single entity to find the best Wikipedia match.

    Uses LLM-powered disambiguation to select the most relevant Wikipedia
    article based on transcript context and video topic.

    Args:
        request: DisambiguationRequest with entity details

    Returns:
        DisambiguationResponse with decision and candidates

    Raises:
        HTTPException: If API key is not configured or disambiguation fails
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY not configured. Disambiguation requires Claude API access.",
        )

    try:
        import requests as req
        from anthropic import Anthropic
        from diskcache import Cache

        from src.core.disambiguation import (
            disambiguate_search_results,
            fetch_candidate_info,
            search_wikipedia_candidates,
        )

        # Initialize clients
        session = req.Session()
        session.headers.update({"User-Agent": "B-Roll-Finder-API/1.0"})
        client = Anthropic(api_key=api_key)
        cache = Cache("/tmp/broll_wikipedia_cache")

        # Search for candidates
        search_results = search_wikipedia_candidates(
            session, request.entity_name, limit=request.search_limit
        )

        if not search_results:
            return DisambiguationResponse(
                decision=DisambiguationDecision(
                    entity_name=request.entity_name,
                    chosen_article="",
                    confidence=0,
                    rationale="No Wikipedia search results found",
                    match_quality="none",
                    candidates_considered=[],
                ),
                action="skip",
                candidates=[],
            )

        # Run disambiguation
        decision = disambiguate_search_results(
            entity_name=request.entity_name,
            entity_type=request.entity_type,
            transcript_context=request.transcript_context,
            video_topic=request.video_topic,
            search_results=search_results,
            session=session,
            client=client,
            cache=cache,
        )

        # Fetch full candidate info for response
        titles = [r["title"] for r in search_results]
        candidates = fetch_candidate_info(titles, cache)

        # Determine action based on confidence
        if decision.confidence >= 7:
            action = "download"
        elif decision.confidence >= 4:
            action = "flag_and_download"
        else:
            action = "skip"

        return DisambiguationResponse(
            decision=decision, action=action, candidates=candidates
        )

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Disambiguation failed: {str(e)}"
        )


@router.post("/search-candidates", response_model=SearchCandidatesResponse)
async def search_candidates(request: SearchCandidatesRequest) -> SearchCandidatesResponse:
    """Search Wikipedia for candidate articles.

    Lower-level endpoint that just performs search without disambiguation.
    Useful for building custom UIs or debugging.

    Args:
        request: SearchCandidatesRequest with query

    Returns:
        SearchCandidatesResponse with candidate list
    """
    try:
        import requests as req

        from src.core.disambiguation import search_wikipedia_candidates

        session = req.Session()
        session.headers.update({"User-Agent": "B-Roll-Finder-API/1.0"})

        candidates = search_wikipedia_candidates(
            session, request.query, limit=request.limit
        )

        return SearchCandidatesResponse(
            query=request.query, candidates=candidates, count=len(candidates)
        )

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Search failed: {str(e)}"
        )


@router.get("/candidate/{title}", response_model=CandidateInfo)
async def get_candidate_info(title: str) -> CandidateInfo:
    """Get detailed information about a Wikipedia article.

    Fetches summary and categories for a specific article title.

    Args:
        title: Wikipedia article title

    Returns:
        CandidateInfo with article details

    Raises:
        HTTPException: If article not found or fetch fails
    """
    try:
        from diskcache import Cache

        from src.core.disambiguation import fetch_candidate_info

        cache = Cache("/tmp/broll_wikipedia_cache")
        candidates = fetch_candidate_info([title], cache)

        if not candidates:
            raise HTTPException(
                status_code=404, detail=f"Wikipedia article not found: {title}"
            )

        return candidates[0]

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch article info: {str(e)}"
        )
