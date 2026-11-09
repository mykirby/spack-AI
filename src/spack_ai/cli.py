"""Command-line interface: `spack-ai <command>` (or `python -m spack_ai`)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from spack_ai.config import Settings, load_settings


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "handler", None):
        parser.print_help()
        return 1
    settings = load_settings(args.config)
    return args.handler(args, settings) or 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="spack-ai", description=__doc__)
    parser.add_argument("--config", help="Site config YAML layered over config/default.yaml.")
    sub = parser.add_subparsers(metavar="command")

    p = sub.add_parser("chat", help="Interactive session with the agent.")
    p.add_argument("--path", action="append", default=[], help="Source tree the agent may read.")
    p.add_argument("--yes", action="store_true",
                   help="Approve state-changing actions without asking.")
    p.set_defaults(handler=cmd_chat)

    p = sub.add_parser("run", help="One-shot task for the agent.")
    p.add_argument("task")
    p.add_argument("--path", action="append", default=[])
    p.add_argument("--yes", action="store_true")
    p.set_defaults(handler=cmd_run)

    p = sub.add_parser("analyze", help="Analyze a source tree or build file (no LLM).")
    p.add_argument("path")
    p.add_argument("--json", action="store_true", help="Print the full BuildSpec as JSON.")
    p.set_defaults(handler=cmd_analyze)

    p = sub.add_parser("generate", help="Deterministic recipe + environment + script (no LLM).")
    p.add_argument("path")
    p.add_argument("--name")
    p.add_argument("--url")
    p.add_argument("--git")
    p.add_argument("--version", dest="version_", help="Version to add (with --sha256 or --git).")
    p.add_argument("--sha256")
    p.add_argument("--out", help="Output directory (default: output/generated/<name>).")
    p.add_argument("--no-env", action="store_true")
    p.set_defaults(handler=cmd_generate)

    p = sub.add_parser("skills", help="List the agent's skills.")
    p.set_defaults(handler=cmd_skills)

    p = sub.add_parser("kb", help="Knowledge base tools.")
    kb = p.add_subparsers(metavar="action")
    q = kb.add_parser("stats", help="Documents and chunks per section.")
    q.set_defaults(handler=cmd_kb_stats)
    q = kb.add_parser("search", help="Search the knowledge base.")
    q.add_argument("query")
    q.add_argument("--section")
    q.add_argument("-k", type=int, default=5)
    q.set_defaults(handler=cmd_kb_search)

    p = sub.add_parser("feedback", help="Label a session's outcome (feeds ML training data).")
    p.add_argument("session")
    p.add_argument("--outcome", choices=["success", "failure"], required=True)
    p.add_argument("--note")
    p.set_defaults(handler=cmd_feedback)

    p = sub.add_parser("eval", help="Score generated recipes against evals/cases.")
    p.add_argument("--cases", default="evals/cases")
    p.add_argument("--agent", action="store_true", help="Evaluate the LLM agent (costs tokens).")
    p.add_argument("--json", action="store_true")
    p.set_defaults(handler=cmd_eval)

    p = sub.add_parser("ml", help="Machine-learning pipeline.")
    ml = p.add_subparsers(metavar="action")
    q = ml.add_parser("collect", help="Build a training dataset from sessions (and a Spack repo).")
    q.add_argument("--out", default="data/datasets/sessions.jsonl")
    q.add_argument("--spack-repo", help="Path to a Spack repository's packages/ directory.")
    q.add_argument("--limit", type=int)
    q.set_defaults(handler=cmd_ml_collect)
    q = ml.add_parser("train", help="Train a model from a training config YAML.")
    q.add_argument("config_file")
    q.set_defaults(handler=cmd_ml_train)
    q = ml.add_parser("models", help="List registered models.")
    q.set_defaults(handler=cmd_ml_models)
    return parser


# ----------------------------------------------------------------------------- agent


def _make_agent(args, settings: Settings):
    from spack_ai.agent import Agent

    if args.yes:
        settings.agent.auto_approve = True
    sources = [Path(p).expanduser().resolve() for p in args.path]
    for source in sources:
        if not source.exists():
            raise SystemExit(f"--path {source} does not exist")
    state = {"last_text": None}

    def on_event(kind: str, data: dict) -> None:
        if kind == "text":
            print(f"\n{data['text']}\n", flush=True)
            state["last_text"] = data["text"]
        elif kind == "tool_start":
            brief = json.dumps(data["input"], default=str)
            print(f"  -> {data['name']} {brief[:120]}{'...' if len(brief) > 120 else ''}",
                  flush=True)
        elif kind == "tool_end" and data["is_error"]:
            print(f"     ! {data['content'][:300]}", flush=True)

    def confirm(prompt: str) -> bool:
        try:
            return input(f"\n{prompt} [y/N] ").strip().lower() in ("y", "yes")
        except EOFError:
            return False

    agent = Agent(settings, sources=sources, confirm=confirm, on_event=on_event)
    print(f"session {agent.session.id}  (workspace: {agent.session.workspace})")
    return agent, state


def _send(agent, state, text: str) -> None:
    import anthropic

    try:
        reply = agent.send(text)
    except anthropic.AuthenticationError:
        raise SystemExit(
            "Claude API credentials not found or invalid. Run `ant auth login` or set "
            "ANTHROPIC_API_KEY (see .env.example)."
        ) from None
    except anthropic.RateLimitError:
        print("Rate limited by the API; wait a moment and resend.", file=sys.stderr)
        return
    except (anthropic.APIConnectionError, anthropic.APIStatusError) as exc:
        print(f"API error: {exc}", file=sys.stderr)
        return
    if reply and reply != state["last_text"]:
        print(f"\n{reply}\n")


def cmd_chat(args, settings: Settings) -> int:
    agent, state = _make_agent(args, settings)
    print("Type your request (Ctrl-D or 'exit' to quit).")
    while True:
        try:
            text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if text in ("exit", "quit"):
            break
        if text:
            _send(agent, state, text)
    print(f"Rate this session: spack-ai feedback {agent.session.id} --outcome success|failure")
    return 0


def cmd_run(args, settings: Settings) -> int:
    agent, state = _make_agent(args, settings)
    _send(agent, state, args.task)
    print(f"Rate this session: spack-ai feedback {agent.session.id} --outcome success|failure")
    return 0


# ----------------------------------------------------------------------------- offline tools


def cmd_analyze(args, settings: Settings) -> int:
    from spack_ai.skills.base import SkillContext
    from spack_ai.skills.build_analysis import analyze_path
    from spack_ai.skills.dependency_mapping.skill import build_mapper

    path = Path(args.path).expanduser().resolve()
    spec = analyze_path(path)
    ctx = SkillContext(settings, workspace=settings.output_dir / "analyze")
    mapper = build_mapper(ctx)
    spec.dependencies = [mapper.resolve(d) for d in spec.dependencies]
    if args.json:
        print(spec.model_dump_json(indent=2, exclude_none=True))
        return 0
    print(f"build system : {spec.build_system.value}")
    print(f"project      : {spec.project_name or '?'} {spec.version or ''}")
    print(f"languages    : {', '.join(spec.languages) or '?'}")
    print(f"files        : {', '.join(spec.files_analyzed[:8])}"
          + (" ..." if len(spec.files_analyzed) > 8 else ""))
    print(f"dependencies : {len(spec.dependencies)}")
    for d in spec.dependencies:
        flag = " " if d.resolved else "?"
        target = d.spack_spec or "(none needed)"
        cond = f"  [if {d.condition}]" if d.condition else ""
        print(f"  {flag} {d.name:<22} {d.source:<18} -> {target}{cond}")
    if spec.options:
        print(f"options      : {len(spec.options)}")
        for o in spec.options:
            print(f"    {o.name:<28} default={o.default!s:<6} variant={o.variant}")
    for note in spec.notes:
        print(f"note: {note}")
    return 0


def cmd_generate(args, settings: Settings) -> int:
    from spack_ai.pipeline import generate
    from spack_ai.schemas import VersionEntry

    versions = [VersionEntry(version=args.version_, sha256=args.sha256)] if args.version_ else []
    result = generate(
        Path(args.path).expanduser(), settings, name=args.name, url=args.url, git=args.git,
        versions=versions, workspace=Path(args.out).resolve() if args.out else None,
        environment=not args.no_env,
    )
    print(f"workspace: {result.workspace}")
    for path in result.files:
        print(f"  wrote {path}")
    for err in result.errors:
        print(f"  error: {err}")
    for warning in result.warnings:
        print(f"  warning: {warning}")
    print("\nNext: review the FIXMEs, or refine interactively with "
          f"`spack-ai chat --path {args.path}`.")
    return 1 if result.errors else 0


def cmd_skills(args, settings: Settings) -> int:
    from spack_ai.skills import all_skills

    for name, skill in all_skills().items():
        gate = " (asks first)" if skill.requires_confirmation else ""
        print(f"{name:<24} [{skill.category}]{gate}\n    {skill.description}\n")
    return 0


def cmd_kb_stats(args, settings: Settings) -> int:
    from spack_ai.knowledge import KnowledgeBase

    kb = KnowledgeBase(settings.knowledge_dir, settings.knowledge.chunk_size,
                       settings.knowledge.chunk_overlap)
    print(f"knowledge base: {kb.root}")
    for section, count in kb.sections().items():
        chunks = sum(1 for c in kb.chunks if c.section == section)
        print(f"  {section:<22} {count:>4} docs  {chunks:>5} chunks")
    return 0


def cmd_kb_search(args, settings: Settings) -> int:
    from spack_ai.knowledge import KnowledgeBase

    kb = KnowledgeBase(settings.knowledge_dir, settings.knowledge.chunk_size,
                       settings.knowledge.chunk_overlap)
    hits = kb.search(args.query, k=args.k, section=args.section)
    if not hits:
        print("no matches")
    for hit in hits:
        print(f"[{hit.score:.2f}] {hit.chunk.path} :: {hit.chunk.heading}")
        print("    " + hit.chunk.text[:300].replace("\n", "\n    ") + "\n")
    return 0


def cmd_feedback(args, settings: Settings) -> int:
    from spack_ai.agent.session import Session

    path = Session.record_feedback(settings, args.session, args.outcome, args.note)
    print(f"recorded {args.outcome} in {path}")
    return 0


def cmd_eval(args, settings: Settings) -> int:
    from spack_ai.evals import load_cases, run_case, summarize_results

    cases = load_cases(settings.resolve(args.cases))
    mode = "agent" if args.agent else "pipeline"
    results = [run_case(name, d, c, settings, mode) for name, d, c in cases]
    summary = summarize_results(results)
    if args.json:
        print(json.dumps({"summary": summary, "cases": [r.__dict__ for r in results]}, indent=2))
        return 0
    for r in results:
        if r.error:
            print(f"✗ {r.name}: {r.error.splitlines()[0]}")
            continue
        deps = r.scores.get("dependencies", {})
        print(f"✓ {r.name}: build_system_ok={r.scores.get('build_system_ok')} "
              f"base_ok={r.scores.get('base_class_ok')} dep_f1={deps.get('f1')} "
              f"fixmes={r.scores.get('fixmes')}")
    print(f"\n{mode}: {json.dumps(summary)}")
    return 0


def cmd_ml_collect(args, settings: Settings) -> int:
    from spack_ai.ml.data import Dataset, SessionCollector, SpackRepoCollector

    examples = list(SessionCollector(settings.sessions_dir).collect())
    if args.spack_repo:
        examples += SpackRepoCollector(Path(args.spack_repo).expanduser(), args.limit).collect()
    dataset = Dataset(examples).deduplicate()
    path = dataset.save(settings.resolve(args.out))
    print(f"{len(dataset)} examples -> {path}")
    print(json.dumps(dataset.stats(), indent=2))
    return 0


def cmd_ml_train(args, settings: Settings) -> int:
    from spack_ai.ml.training import TrainingConfig, train

    run = train(TrainingConfig.from_yaml(Path(args.config_file)), settings)
    print(f"run: {run.directory}")
    print(json.dumps(run.metrics, indent=2))
    print(f"Use it: set ml.dependency_model: {run.directory} in your config.")
    return 0


def cmd_ml_models(args, settings: Settings) -> int:
    from spack_ai.ml.models import all_models

    for name, model in all_models().items():
        print(f"{name:<24} task={model.task}")
    return 0
