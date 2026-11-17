# Independent review: Agent Gate Bench rebuilt 0.2.0 local effects

Reviewed final effects implementation, inherited trusted POSIX runner/checker, package entry point, six synthetic fixtures, tests, README and LOCAL_TOOL_EFFECTS.md. This is a new extension of public 0.1, not a recovered earlier RC2.

## Corrected blocker
A valid deeply nested tool-return override originally produced a passing real run whose receipt exceeded the parser depth bound and failed offline verification. Independently reproduced with ten nested objects. Final load rejects overrides deeper than four containers before executing; serialized receipts are parsed and regraded before publication. New depth-10 rejection and depth-4 actual run/verify regressions passed. Network claims now distinguish the non-network built-in outbox tool from arbitrary trusted adapter behavior.

A second strict-schema issue was confirmed: nested process.case_id was silently overwritten by the v1 checker wrapper. Final code validates the exact eight process fields before wrapping; the new regression passes. All final tests and the wheel were rebuilt and re-executed after this fix. Earlier wheels in wheels/ are superseded and must not be delivered as final.

## Independent validation
- Final Linux/Python 3.12 regression suite: 57 tests passed, zero skips.
- Fresh wheel build, installation into a new temporary venv and execution outside the source checkout completed. Confirmed effects module loaded from venv site-packages.
- Reference adapter: 6 pass, 0 fail, 0 error; offline verification reproduced the same report.
- Vulnerable adapter: 4 pass, 2 fail, 0 error; both run and offline verify exited 3, so internally consistent failing evidence was not turned green.
- Observed injected unauthorized-recipient case: outbox remained empty.
- Observed single-use send case: local final outbox was exactly [{'body':'42','to':'friend.invalid'}] for both fixtures, with no second effect. Denied events retained equal before/after state hashes.
- Both evidence directories had mode 0700. git diff --check passed.

## Identities and retained evidence
Final effects.py SHA-256: c14a4f230f1a3e9b39912070bfaa0ed88c4a80011da58b166cc003ddfefc9c32
Wheel SHA-256: 79517c27dd27cc9194feddcd34fdaeda463a85a64003a4f92dd86cb8c2bb9923
Wheel: final-wheels/agent_gate_bench-0.2.0-py3-none-any.whl
Evidence: final-reference/ and final-vulnerable/ in this audit directory; matching *-result.json and *-verify.json are retained.

## Conclusion and limits
No remaining release-blocking defect established in reviewed scope. Actual synthetic tool dispatch, exact-use grants, state transitions, multi-turn history and independent final-state/call checks work for the declared cases. The harness distinguishes safety, utility and incomplete/error outcomes and validates offline replay without executing the adapter.

This is not a sandbox, provider integration, real-LLM safety benchmark, execution attestation or universal injection defense. Trusted adapters retain OS privileges and may independently access networks/files; only built-in send_message uses the local JSON outbox. Transformed leaks, unreported side effects, detached descendants, production data, Windows execution, GUI and comparative superiority are outside tested claims. No external publication was performed by this reviewer.
