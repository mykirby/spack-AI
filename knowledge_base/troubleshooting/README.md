# troubleshooting

One file per failure: the error message (verbatim, so search matches it), the root
cause, and the fix. When a failure has a clear signature, also add a regex entry to
`structured/error_patterns.yaml` so `diagnose_build_failure` recognizes it instantly.
