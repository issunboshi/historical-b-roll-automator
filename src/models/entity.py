"""
Entity models for B-Roll Finder.

These models represent the core data structures for entities extracted from transcripts.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class EntityType(str, Enum):
    """Types of entities that can be extracted from transcripts."""

    PEOPLE = "people"
    PLACES = "places"
    EVENTS = "events"
    CONCEPTS = "concepts"
    ORGANIZATIONS = "organizations"


class MatchQuality(str, Enum):
    """Quality assessment of disambiguation match."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class Occurrence(BaseModel):
    """A single occurrence of an entity in the transcript.

    Tracks where and when an entity appears in the source transcript.
    """

    timecode: str = Field(
        description="SRT-format timecode (HH:MM:SS,mmm) of the occurrence"
    )
    cue_idx: int = Field(description="Index of the SRT cue containing this occurrence")
    context: Optional[str] = Field(
        default=None, description="Surrounding text context from the transcript"
    )


class ImageMetadata(BaseModel):
    """Metadata for a downloaded image.

    Contains all information needed for attribution and timeline placement.
    """

    path: str = Field(description="Absolute filesystem path to the image")
    filename: str = Field(description="Image filename")
    category: str = Field(
        description="License category (public_domain, cc_by, cc_by_sa, etc.)"
    )
    license_short: str = Field(default="", description="Short license identifier")
    license_url: str = Field(default="", description="URL to license text")
    source_url: str = Field(default="", description="Wikipedia source URL")
    title: str = Field(default="", description="Image title from Wikipedia")
    author: str = Field(default="", description="Image author/creator")
    usage_terms: str = Field(default="", description="Usage terms from license")
    suggested_attribution: str = Field(
        default="", description="Suggested attribution text"
    )


class ValidatedQuery(BaseModel):
    """A search query that has been validated against Wikipedia."""

    query: str = Field(description="The search query string")
    valid: bool = Field(description="Whether the query returned valid Wikipedia results")
    result_count: int = Field(default=0, description="Number of results found")


class SearchStrategies(BaseModel):
    """LLM-generated search strategies for finding Wikipedia content.

    Contains the best title and fallback queries for an entity.
    """

    best_title: Optional[str] = Field(
        default=None, description="Most likely Wikipedia article title"
    )
    best_title_valid: bool = Field(
        default=False, description="Whether best_title points to a valid article"
    )
    queries: List[str] = Field(
        default_factory=list, description="Alternative search queries"
    )
    validated_queries: List[ValidatedQuery] = Field(
        default_factory=list, description="Queries that have been validated"
    )
    rationale: str = Field(
        default="", description="LLM explanation of the search strategy"
    )


class DisambiguationMetadata(BaseModel):
    """Metadata from the disambiguation process.

    Tracks how an entity was resolved to a specific Wikipedia article.
    """

    source: Optional[str] = Field(
        default=None,
        description="How disambiguation was performed (llm_disambiguation, manual_override, pre_computed)",
    )
    confidence: int = Field(
        default=0, ge=0, le=10, description="Confidence score 0-10"
    )
    match_quality: MatchQuality = Field(
        default=MatchQuality.NONE, description="Match quality assessment"
    )
    rationale: str = Field(default="", description="Explanation of disambiguation choice")
    candidates_considered: List[str] = Field(
        default_factory=list, description="Wikipedia titles that were evaluated"
    )
    chosen_article: Optional[str] = Field(
        default=None, description="Selected Wikipedia article title"
    )
    action: str = Field(
        default="download",
        description="Action taken (download, flag_and_download, skip)",
    )


class Entity(BaseModel):
    """A named entity extracted from a transcript.

    This is the core data structure for entities, containing all metadata
    needed for Wikipedia image lookup and timeline generation.
    """

    name: str = Field(description="Canonical entity name")
    entity_type: EntityType = Field(description="Type of entity")
    aliases: List[str] = Field(
        default_factory=list,
        description="Alternative surface forms from the transcript",
    )
    occurrences: List[Occurrence] = Field(
        default_factory=list, description="Where this entity appears in the transcript"
    )
    images: List[ImageMetadata] = Field(
        default_factory=list, description="Downloaded images for this entity"
    )
    priority: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Priority score for filtering"
    )
    context: str = Field(
        default="", description="Aggregated context from all occurrences"
    )
    search_strategies: Optional[SearchStrategies] = Field(
        default=None, description="LLM-generated search strategies"
    )
    disambiguation: Optional[DisambiguationMetadata] = Field(
        default=None, description="Disambiguation results"
    )
    matched_strategy: Optional[str] = Field(
        default=None, description="Which search strategy succeeded"
    )
    download_status: Optional[str] = Field(
        default=None, description="Download result (success, failed, no_images)"
    )
    is_montage: bool = Field(
        default=False, description="Whether this entity is part of a montage sequence"
    )
    montage_image_count: Optional[int] = Field(
        default=None, description="Number of images to use in montage"
    )

    @property
    def mention_count(self) -> int:
        """Number of times this entity is mentioned in the transcript."""
        return len(self.occurrences)

    @property
    def first_timecode(self) -> Optional[str]:
        """Timecode of the first occurrence."""
        if self.occurrences:
            return self.occurrences[0].timecode
        return None


class EntitiesMap(BaseModel):
    """The complete entities map structure.

    This is the top-level structure for the entities_map.json file.
    """

    entities: dict[str, Entity] = Field(
        default_factory=dict, description="Map of entity name to Entity object"
    )
    source_srt: str = Field(default="", description="Path to source SRT file")
    video_context: str = Field(
        default="", description="Video topic/context for disambiguation"
    )
    metadata: dict = Field(
        default_factory=dict, description="Additional pipeline metadata"
    )
    skipped: List[dict] = Field(
        default_factory=list, description="Entities that were skipped during processing"
    )
