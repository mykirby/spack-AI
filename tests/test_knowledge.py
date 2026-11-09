from spack_ai.knowledge import KnowledgeBase
from spack_ai.knowledge.chunker import chunk_document
from spack_ai.knowledge.loader import Document


def make_kb(tmp_path):
    (tmp_path / "build_systems").mkdir()
    (tmp_path / "troubleshooting").mkdir()
    (tmp_path / "structured").mkdir()
    (tmp_path / "build_systems" / "README.md").write_text("# What goes here\nmakefile edit")
    (tmp_path / "build_systems" / "makefile.md").write_text(
        "# Makefile packages\n\n## edit()\n\nUse FileFilter in edit() to set CC = spack_cc.\n\n"
        "## install()\n\nCopy binaries into prefix.bin when there is no install target.\n"
    )
    (tmp_path / "troubleshooting" / "linking.md").write_text(
        "# Undefined references\n\nCheck the BLAS provider and Fortran name mangling.\n"
    )
    (tmp_path / "structured" / "table.yaml").write_text("a: 1\n")
    return KnowledgeBase(tmp_path, chunk_size=400, chunk_overlap=50)


def test_search_and_sections(tmp_path):
    kb = make_kb(tmp_path)
    assert kb.sections() == {"build_systems": 1, "troubleshooting": 1}  # README/structured skipped
    hits = kb.search("makefile FileFilter edit")
    assert hits and hits[0].chunk.path == "build_systems/makefile.md"
    assert hits[0].chunk.heading == "Makefile packages > edit()"
    assert kb.search("blas mangling", section="build_systems") == []
    assert kb.search("blas mangling")[0].chunk.section == "troubleshooting"
    assert kb.structured("table") == {"a": 1}
    assert kb.structured("missing") == {}


def test_chunker_windows_long_sections():
    text = "# Big\n\n" + "\n\n".join(f"paragraph {i} " + "word " * 40 for i in range(20))
    doc = Document(path="x.md", section="s", title="Big", text=text, kind="markdown")
    chunks = chunk_document(doc, size=500, overlap=50)
    assert len(chunks) > 3 and all(len(c.text) <= 600 for c in chunks)
    assert len({c.id for c in chunks}) == len(chunks)
