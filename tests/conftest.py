from pathlib import Path

import pytest

from spack_ai.config import REPO_ROOT, PathsConfig, Settings
from spack_ai.skills.base import SkillContext

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Real knowledge base (for the structured tables), throwaway data and output dirs."""
    return Settings(
        paths=PathsConfig(
            knowledge_base=REPO_ROOT / "knowledge_base",
            data_dir=tmp_path / "data",
            output_dir=tmp_path / "output",
        )
    )


@pytest.fixture
def ctx(settings: Settings, tmp_path: Path) -> SkillContext:
    return SkillContext(settings, workspace=tmp_path / "workspace", allowed_roots=[FIXTURES])


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES
