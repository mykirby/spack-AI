"""End to end: transcripts -> dataset -> training -> serving inside map_dependencies."""

import json

from spack_ai.agent.session import Session
from spack_ai.ml.data import Dataset, SessionCollector, SpackRepoCollector, TrainingExample
from spack_ai.ml.evaluation import recipe_scores, set_prf
from spack_ai.ml.serving import load_model
from spack_ai.ml.training import TrainingConfig, train
from spack_ai.skills import get_skill

RECIPE = '''
from spack.package import *

class Foo(CMakePackage):
    homepage = "https://foo.org"
    url = "https://foo.org/foo-1.0.tar.gz"
    version("1.0", sha256="{sha}")
    variant("mpi", default=True, description="MPI")
    depends_on("c", type="build")
    depends_on("weird-lib")
    depends_on("mpi", when="+mpi")
'''.replace("{sha}", "b" * 64)


def write_session(settings, session_id, outcome):
    session = Session(settings, session_id)
    rows = [{"upstream": "WeirdLib", "source": "find_package", "spack": "weird-lib",
             "resolved": False},
            {"upstream": "MPI", "source": "find_package", "spack": "mpi", "resolved": True}]
    session.log("tool_call", id="a", name="map_dependencies", input={})
    session.log("tool_result", id="a", name="map_dependencies", is_error=False,
                content=json.dumps({"summary": "", "data": rows}))
    session.log("tool_call", id="b", name="analyze_build_system", input={"path": "."})
    session.log("tool_result", id="b", name="analyze_build_system", is_error=False,
                content=json.dumps({"summary": "", "data": {"build_system": "cmake"}}))
    session.log("tool_call", id="c", name="save_package_recipe", input={})
    session.log("tool_result", id="c", name="save_package_recipe", is_error=False,
                content=json.dumps({"summary": "", "data": {"source": RECIPE}}))
    Session.record_feedback(settings, session_id, outcome)


def test_collect_train_serve(settings, ctx):
    for i in range(12):
        write_session(settings, f"s{i:02d}", "success" if i % 4 else "failure")

    examples = list(SessionCollector(settings.sessions_dir).collect())
    tasks = {e.task for e in examples}
    assert tasks == {"dependency_mapping", "recipe_generation"}
    weird = next(e for e in examples if e.input["name"] == "WeirdLib")
    assert weird.target == "weird-lib" and weird.metadata["in_final_recipe"]

    dataset_path = Dataset(examples).save(settings.data_dir / "datasets" / "s.jsonl")
    reloaded = Dataset.load(dataset_path)
    assert len(reloaded) == len(examples)
    split = reloaded.split(val=0.2, test=0.2, seed=1)
    assert len(split.train) + len(split.val) + len(split.test) == len(examples)
    assert reloaded.split(val=0.2, test=0.2, seed=1).test == split.test  # deterministic

    config = TrainingConfig(model="dependency_lookup", dataset=dataset_path,
                            outcomes=["success"], val_fraction=0.0, test_fraction=0.0,
                            output_dir=settings.data_dir / "runs")
    run = train(config, settings)
    assert (run.directory / "run.json").exists() and run.metrics["counts"]["train"] > 0

    model = load_model(run.directory)
    assert model.predict([{"name": "weirdlib", "source": "find_package"}]) == ["weird-lib"]

    # Plug the trained run into the mapper via config.
    settings.ml.dependency_model = run.directory
    result = get_skill("map_dependencies")(ctx)(names=[{"name": "WeirdLib"}])
    row = result.data[0]
    assert row["spack"] == "weird-lib" and row["resolved"] and "trained" in row["note"]


def test_spack_repo_collector(tmp_path):
    pkg = tmp_path / "packages" / "foo"
    pkg.mkdir(parents=True)
    (pkg / "package.py").write_text(RECIPE)
    (examples,) = list(SpackRepoCollector(tmp_path / "packages").collect())
    assert isinstance(examples, TrainingExample)
    assert examples.metadata["dependencies"] == ["c", "mpi", "weird-lib"]
    assert examples.metadata["variants"] == ["mpi"]


def test_recipe_scores():
    scores = recipe_scores(RECIPE, {"base_class": "CMakePackage",
                                    "dependencies": ["mpi", "weird-lib", "zlib-api"],
                                    "variants": ["mpi"]})
    assert scores["syntax_ok"] and scores["base_class_ok"]
    assert scores["dependencies"]["precision"] == 1.0
    assert scores["dependencies"]["recall"] == round(2 / 3, 4)
    assert recipe_scores(RECIPE, {"reference": RECIPE})["dependencies"]["f1"] == 1.0
    assert set_prf(set(), set())["f1"] == 1.0
