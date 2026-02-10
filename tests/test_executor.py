"""Tests for pipeline executor."""
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock

from src.core.executor import PipelineExecutor, StepResult


@pytest.mark.asyncio
async def test_executor_runs_extract_step(tmp_path):
    """Executor should run extract step via subprocess."""
    executor = PipelineExecutor(
        srt_path=tmp_path / "video.srt",
        output_dir=tmp_path / "output",
    )

    with patch("src.core.executor.asyncio.create_subprocess_exec") as mock_exec:
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate.return_value = (b"", b"")
        mock_exec.return_value = mock_process

        result = await executor.run_step("extract")

        assert result.success is True
        assert result.step == "extract"
        assert mock_exec.called
