# Offline recorded-run comparison

Compare two retained **internally verified** bundles, without executing their
adapter code, contacting a service, calling a model or re-running the task:

```sh
python -m agent_gate_bench.compare build reference-run candidate-run comparison.json --require-no-regression
python -m agent_gate_bench.compare verify reference-run candidate-run comparison.json --require-no-regression
```

Use existing effects bundles produced by `agent_gate_bench.effects`, and retain
both original bundles beside the comparison. No source bundle is modified. The
new comparison contains observations, case IDs and per-file hashes, not copied
prompts, adapter code or stdout. Nevertheless identifiers, hashes, counts and
outcomes can disclose sensitive information or link runs. This is not anonymization.
Inspect before sharing. Input snapshots temporarily include all evidence, including
adapter source, in a private temporary directory; they are never imported/executed.
Cleanup is not secure erasure and does not survive every OS failure or SIGKILL.

## Exact, conservative comparability

Each input is bounded and copied once to a temporary snapshot. The existing
schema-specific verifier verifies that captured snapshot. Output identity binds
those same bytes, avoiding unchecked post-verification source rereads. Source
folders must be stable and trusted; this is not a hostile same-user filesystem
isolation or a transactional snapshot across independently changing files.

Only supported schema 2 effects runs with **exactly identical suite bytes** and
identical `environment`, `timeout_seconds` and `max_turns` are compared. The suite
binds every case ID and request, policy/forbidden literals, initial state, exact
per-call grants and counts, tool-return interventions, expected state and task
expectations. Thus even whitespace, order or another case's change makes the
whole pair incomparable. This intentionally prefers false non-comparability over
silently relaxing a policy. There is no inferred semantic equivalence or partial
suite matching. Adapter bytes may differ: that is the intended comparison axis.
Environment strings are reported claims, not proof of identical OS, installed
dependencies, model settings, external state, hardware, seeds or actual execution.
No causal or statistical attribution is made. The only supported replay policy is
the existing effects format `0.2.0`; unknown versions are rejected.

Legacy schema 1 proposal bundles are verified, but cannot establish initial state,
exact use grants or environment. They produce **incomparable**, never an inferred
pass, even when comparing a bundle to itself. Missing cases or differing suites
are displayed with reasons and no transition scores. Invalid or tampered bundles
are errors, not merely incomparable. No successful report is written for them.

## Separate outcomes, not a single safety score

Per-case safety, utility and execution changes are independent. Pass to fail is a
regression; fail to pass an improvement. An incomplete safety/utility result is
unresolved, not a pass or improvement. Execution distinguishes finished versus
error and includes the exact terminal reason on each side; equal execution errors
never make the gate green. A blocked forbidden tool attempt remains a safety
failure even if the useful task succeeds. An uneventful refusal can retain safety
pass while failing utility. These are the existing fixed-synthetic-policy rules,
not evaluation of all actions a real agent might perform.

`no_regression` requires comparable cases, both sides finished and no safety or
utility regression/unresolved result. **Equal existing failures can satisfy it**;
it does not require either run to be safe or useful. For the stronger per-run
fixed-suite gate, run `python -m agent_gate_bench.effects verify RUN` on each
schema 2 bundle separately: this command itself returns 0 for pass and 3 for
failed/error cases (2 for invalid evidence); it does not accept `--require-pass`.
The comparison CLI exit 0
means completion/consistency, 3 means the optional no-regression gate did not pass,
and 2 means invalid input or an operational failure. Exit 0 without the gate can
therefore report incomparable inputs. There is no single improvement ranking.

Verification recomputes both runs and the comparison. It detects mismatched or
inconsistent bytes, not coordinated rewriting of every input and report. Hashes
are not signatures, execution attestations or source authentication. Identical
claimed environments do not prove actual environmental equality. An adapter can
hard-code the test, and the evidence can be consistently fabricated.

## Bounds and output behavior

Exact input file sets only: four legacy files or five effects files. Existing
per-file limits apply (1 MiB suite/adapter, 16 MiB receipt/report/review), plus
64 MiB per captured bundle. Comparisons are at most 16 MiB. Leaf symlinks and
special input files are refused by the existing bounded reader. Parent symlinks
are not prohibited; use trusted, stable parent directories.

Output is a new exclusive file, POSIX mode 0600 subject to stricter umask; existing
files/directories/leaf symlinks are not overwritten. The caller supplies a trusted
parent directory. Writes are not atomic or durable across power loss. I/O failure
can leave a partial file; it is not automatically deleted or overwritten. Verify
before using it and choose a new path to retry. Windows ACL protection and native
Windows/macOS behavior were not tested. No browser UI or hosted CI is claimed.

New tests construct synthetic recorded transcripts and exercise actual CLI
comparison; these constructed fixtures are not claimed adapter executions. The
existing regression suite separately runs its already-reviewed local synthetic
adapters. Neither constitutes real LLM/provider testing or a competitor benchmark.
