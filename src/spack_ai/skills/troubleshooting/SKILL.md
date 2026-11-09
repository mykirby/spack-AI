### Troubleshooting (`diagnose_build_failure`)

When the user pastes a failed build, run this first, then read the matched context
yourself. The first real error usually matters more than the last line. Propose a
concrete recipe change, apply it with `save_package_recipe`, and re-validate. Once a
new kind of failure is solved, suggest adding its signature to
`knowledge_base/structured/error_patterns.yaml` and a write-up to
`knowledge_base/troubleshooting/`.
