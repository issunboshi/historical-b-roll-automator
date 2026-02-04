"""Pipeline executor - runs pipeline steps via subprocess."""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

# Pipeline step definitions
STEPS = ["extract", "enrich", "strategies", "disambiguate", "download", "xml"]


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
        """Build subprocess command for a step."""
        script = self._resolve_script(step)
        entities_path = self.output_dir / "entities_map.json"

        cmd = [sys.executable, str(script)]

        if step == "extract":
            cmd.extend([
                "--srt", str(self.srt_path),
                "--out", str(entities_path),
            ])
        elif step in ("enrich", "strategies", "disambiguate", "download"):
            cmd.extend(["--map", str(entities_path)])
        elif step == "xml":
            cmd.extend([
                "--map", str(entities_path),
                "--output", str(self.output_dir / "broll_timeline.xml"),
            ])

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
