import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path
from main import create_chief, run_command


@pytest.fixture
def tmp_dirs(tmp_path):
    return {
        "data_dir": tmp_path / "data",
        "configs_dir": tmp_path / "agent_configs",
    }


class TestCLI:
    def test_create_chief(self, tmp_dirs):
        with patch("main.app_config") as mock_config:
            mock_config.DATA_DIR = tmp_dirs["data_dir"]
            mock_config.MEMORY_DB_PATH = tmp_dirs["data_dir"] / "memory.db"
            mock_config.CHROMA_PERSIST_DIR = tmp_dirs["data_dir"] / "chroma"
            mock_config.AGENT_CONFIGS_DIR = tmp_dirs["configs_dir"]
            chief = create_chief()
            assert chief is not None

    @pytest.mark.asyncio
    async def test_run_agents_command(self, tmp_dirs):
        with patch("main.app_config") as mock_config:
            mock_config.DATA_DIR = tmp_dirs["data_dir"]
            mock_config.MEMORY_DB_PATH = tmp_dirs["data_dir"] / "memory.db"
            mock_config.CHROMA_PERSIST_DIR = tmp_dirs["data_dir"] / "chroma"
            mock_config.AGENT_CONFIGS_DIR = tmp_dirs["configs_dir"]
            chief = create_chief()
            result = await run_command("agents", chief)
            assert result is not None
            assert "agent" in result.lower() or "no" in result.lower()

    @pytest.mark.asyncio
    async def test_run_memory_command(self, tmp_dirs):
        with patch("main.app_config") as mock_config:
            mock_config.DATA_DIR = tmp_dirs["data_dir"]
            mock_config.MEMORY_DB_PATH = tmp_dirs["data_dir"] / "memory.db"
            mock_config.CHROMA_PERSIST_DIR = tmp_dirs["data_dir"] / "chroma"
            mock_config.AGENT_CONFIGS_DIR = tmp_dirs["configs_dir"]
            chief = create_chief()
            result = await run_command("memory", chief)
            assert result is not None
