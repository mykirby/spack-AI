from __future__ import annotations

from pydantic import BaseModel, Field

from spack_ai.schemas import SkillResult
from spack_ai.skills import register
from spack_ai.skills.base import Skill


class SearchInput(BaseModel):
    query: str = Field(description="What you need, e.g. 'MakefilePackage edit FileFilter'.")
    section: str | None = Field(
        default=None,
        description="Restrict to one section: spack_fundamentals, build_systems, "
        "package_recipes, environments, hpc_sites, troubleshooting.",
    )
    k: int = Field(default=0, ge=0, le=20, description="Number of results (0 = config default).")


@register
class SearchKnowledge(Skill):
    name = "search_knowledge"
    category = "knowledge"
    description = (
        "Search the curated knowledge base (Spack fundamentals, build-system guides, example "
        "recipes, environment patterns, HPC site notes, troubleshooting cases). Cite the "
        "returned paths when you rely on them."
    )
    Input = SearchInput

    def run(self, params: SearchInput) -> SkillResult:
        kb = self.ctx.knowledge
        k = params.k or self.ctx.settings.knowledge.top_k
        hits = kb.search(params.query, k=k, section=params.section)
        if not hits:
            sections = ", ".join(f"{s} ({n})" for s, n in kb.sections().items())
            return SkillResult(
                summary="No matches in the knowledge base.",
                data={"sections": sections or "knowledge base is empty"},
            )
        return SkillResult(
            summary=f"{len(hits)} result(s) for {params.query!r}.",
            data=[
                {
                    "source": f"knowledge_base/{h.chunk.path}",
                    "heading": h.chunk.heading,
                    "score": round(h.score, 2),
                    "text": h.chunk.text,
                }
                for h in hits
            ],
        )
