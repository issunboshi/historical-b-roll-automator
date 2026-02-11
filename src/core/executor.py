"""Pipeline executor - runs pipeline steps via subprocess."""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Tuple

# Pipeline step definitions
STEPS = ["extract", "enrich", "strategies", "disambiguate", "download", "xml"]

# Roles that require Anthropic (they use client.beta.messages.parse)
_PROVIDER_CONSTRAINTS = {
    "summarize": "anthropic",
    "strategies": "anthropic",
    "disambiguate": "anthropic",
}

# Map pipeline steps to their LLM role names
_STEP_ROLE_MAP = {
    "extract": "extract",
    "strategies": "strategies",
    "disambiguate": "disambiguate",
}


def _resolve_llm_for_role(config: dict, role: str) -> Tuple[str, str]:
    """Resolve (provider, model) for a pipeline role."""
    llm = config.get("llm", {})
    global_provider = llm.get("provider", "openai")
    global_model = llm.get("model", "gpt-4o-mini")

    role_cfg = llm.get("roles", {}).get(role, {})
    provider = role_cfg.get("provider") or global_provider
    model = role_cfg.get("model") or global_model

    constraint = _PROVIDER_CONSTRAINTS.get(role)
    if constraint and provider != constraint:
        provider = constraint
        if not role_cfg.get("model"):
            model = "claude-sonnet-4-5-20250929"

    return provider, model


@dataclass
class StepResult:
    """Result of a pipeline step execution."""
    step: str
    success: bool
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    error: Optional[str] = None


@dataclass
class PipelineExecutor:
    """Executes pipeline steps via subprocess."""

    srt_path: Path
    output_dir: Path
    config: dict = field(default_factory=dict)

    # Callbacks for progress reporting
    on_step_start: Optional[Callable[[str], None]] = None
    on_step_complete: Optional[Callable[[StepResult], None]] = None

    def __post_init__(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_script(self, name: str) -> Path:
        """Resolve path to tool script."""
        base = Path(__file__).parent.parent.parent  # src/core -> project root
        tools_path = base / "tools" / f"{name}.py"
        if tools_path.exists():
            return tools_path
        # Map step names to script names
        script_map = {
            "extract": "srt_entities.py",
            "enrich": "enrich_entities.py",
            "strategies": "generate_search_strategies.py",
            "disambiguate": "disambiguate_entities.py",
            "download": "download_entities.py",
            "xml": "generate_xml.py",
        }
        script_name = script_map.get(name, f"{name}.py")
        return base / "tools" / script_name

    def _build_command(self, step: str) -> list[str]:
        """Build subprocess command for a step.

        Mirrors the argument wiring in broll.py's cmd_* functions so that
        API-launched pipelines pass the same flags as CLI runs.
        """
        script = self._resolve_script(step)
        entities_path = self.output_dir / "entities_map.json"
        llm = self.config.get("llm", {})

        cmd = [sys.executable, str(script)]

        if step == "extract":
            provider, model = _resolve_llm_for_role(self.config, "extract")
            fps = self.config.get("fps", 25.0)
            cmd.extend([
                "--srt", str(self.srt_path),
                "--out", str(entities_path),
                "--provider", provider,
                "--model", model,
                "--fps", str(fps),
            ])
            subject = self.config.get("subject")
            if subject:
                cmd.extend(["--subject", subject])

        elif step == "enrich":
            cmd.extend([
                "--map", str(entities_path),
                "--srt", str(self.srt_path),
                "--out", str(self.output_dir / "enriched_entities.json"),
            ])

        elif step == "strategies":
            _, model = _resolve_llm_for_role(self.config, "strategies")
            cmd.extend([
                "--map", str(entities_path),
                "--out", str(self.output_dir / "strategies_entities.json"),
                "--model", model,
            ])

        elif step == "disambiguate":
            _, model = _resolve_llm_for_role(self.config, "disambiguate")
            parallel = self.config.get("disambig_parallel", 10)
            min_priority = self.config.get("min_priority", 0.5)
            cmd.extend([
                "--map", str(entities_path),
                "--parallel", str(parallel),
                "--min-priority", str(min_priority),
                "--model", model,
            ])

        elif step == "download":
            images_per_entity = self.config.get("images_per_entity", 3)
            parallel = self.config.get("parallel_downloads", 4)
            cmd.extend([
                "--map", str(entities_path),
                "--images-per-entity", str(images_per_entity),
                "--parallel", str(parallel),
            ])

        elif step == "xml":
            fps = self.config.get("fps", 25.0)
            duration = self.config.get("image_duration_seconds", 4.0)
            gap = self.config.get("min_gap_seconds", 2.0)
            tracks = self.config.get("broll_track_count", 4)
            timeline_name = self.config.get("timeline_name", "B-Roll Timeline")
            min_match_quality = self.config.get("min_match_quality", "high")
            cmd.extend([
                str(entities_path),
                "--output", str(self.output_dir / "broll_timeline.xml"),
                "--fps", str(fps),
                "--duration", str(duration),
                "--gap", str(gap),
                "--tracks", str(tracks),
                "--timeline-name", timeline_name,
                "--min-match-quality", min_match_quality,
            ])
            if self.config.get("allow_non_pd"):
                cmd.append("--allow-non-pd")

        return cmd

    async def run_step(self, step: str) -> StepResult:
        """Run a single pipeline step.

        Uses asyncio.create_subprocess_exec which is safe from shell injection
        as it does not invoke a shell - arguments are passed directly to the
        executable without shell interpretation.
        """
        if step not in STEPS:
            raise ValueError(f"Unknown step '{step}'. Valid steps: {STEPS}")

        if self.on_step_start:
            self.on_step_start(step)

        cmd = self._build_command(step)

        try:
            # create_subprocess_exec is safe - no shell interpretation
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            result = StepResult(
                step=step,
                success=process.returncode == 0,
                returncode=process.returncode or 0,
                stdout=stdout.decode() if stdout else "",
                stderr=stderr.decode() if stderr else "",
            )
        except Exception as e:
            result = StepResult(
                step=step,
                success=False,
                error=str(e),
            )

        if self.on_step_complete:
            self.on_step_complete(result)

        return result

    async def run_pipeline(
        self,
        from_step: Optional[str] = None,
        to_step: Optional[str] = None,
    ) -> list[StepResult]:
        """Run full pipeline or subset of steps."""
        if from_step and from_step not in STEPS:
            raise ValueError(f"Unknown step '{from_step}'. Valid steps: {STEPS}")
        if to_step and to_step not in STEPS:
            raise ValueError(f"Unknown step '{to_step}'. Valid steps: {STEPS}")

        results = []

        steps = STEPS.copy()
        if from_step:
            start_idx = steps.index(from_step)
            steps = steps[start_idx:]
        if to_step:
            end_idx = steps.index(to_step) + 1
            steps = steps[:end_idx]

        for step in steps:
            result = await self.run_step(step)
            results.append(result)
            if not result.success:
                break  # Stop on failure

        return results
