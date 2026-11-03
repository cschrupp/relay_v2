# Lessons

What the first attempt ([`cschrupp/relay`](https://github.com/cschrupp/relay),
22 September – 31 October 2026) taught. Keep this file current; add to it when
something new is learned.

## The headline

The first Relay drifted in exactly the ways it was built to prevent. It had a
1,202-line simplicity policy, a rule that product work should be at least
two-thirds of effort, and 407 review records. None of them stopped the drift,
because every one was prose that someone had to remember and apply.

| Its own rule | What happened |
| --- | --- |
| Foundations independent of database, GitHub and UI | The persistence layer came to import feature packages, forming a 12-package import cycle that included the UI. |
| The runtime owns the loop; Relay governs | The runtime adapter and the role contracts imported each other. |
| Small, direct functions | 31 functions ran 150+ lines; two ran about 850–900. |
| Product work at least two-thirds of effort | 955 of 1,038 commits (92%) touched no source code. |
| Catch drift (the original vision) | The UI printed "architectural-drift assessment: NOT REPRESENTED". |
| Route models by role for token efficiency | Planned as a slice, then renamed away; model choice became an identity to audit. |

A one-line import contract in CI would have failed the first commit that broke
layering. **Drift is caught by executable checks in short loops, not by more
records.**

### When the checks would have fired

`relay drift history` replayed the first repository's 671 first-parent commits
(22 September – 28 October 2026) against this repository's two day-one checks:

| Day | Date | Commit | What first fired |
| --- | --- | --- | --- |
| 2 | 23 Sep | `babd0980` | First function over 80 lines (`_evaluate_one`, 150 lines; the package was 2,393 lines) |
| 7 | 28 Sep | `9456b313` | First import cycle: `integrations → persistence → repository_sync`, the seed of the 12-package cycle |
| 14 | 5 Oct | | The cycle reaches 7 packages |
| 20 | 11 Oct | | 9 packages, including the UI (`board`) |
| 30 | 21 Oct | | 12 packages |
| 37 | 28 Oct | `375b599c` | A second cycle, `agent_runtime ↔ role_contracts`, arrives in one PR merge; 88 functions over 80 lines |

Both checks would have stopped the drift in the first week, while the cycle was
three packages and one commit old. Instead it grew for a month, long before it
was felt. Reproduce with
`relay drift history ../relay --rev 375b599c --root src/relay_engine`.

**First steered run** (2 November 2026): issue #21 (`relay --version`) through
`relay run`: 1 attempt, card clean, accepted; openrouter/deepseek/deepseek-v4.1-flash,
23,056 tokens in and 1,826 out, US$0.0037.

## Governance

1. Govern consequential boundaries, not keystrokes. Reversible work proceeds; scope, risk, cost or external effects need a human decision.
2. Two normal human gates are enough: direction (HA-1) and acceptance (HA-2). HA-X is only for irreversible effects.
3. Rework requested by a reviewer stays inside the existing approval.
4. Human decisions are not commits, and recording one should not need another approval.
5. Governance must fit the project's maturity. A product's future self-governance is a release milestone, not a way to build the product.
6. Do not reconstruct history nobody recorded. For an existing project, the past is context; the future is what gets governed.

## Execution and decomposition

7. One work packet is one meaningful outcome, not a file, function or checklist item.
8. The agent owns its internal plan, tests, repair and self-review, and continues until done, blocked or out of budget.
9. New work found along the way is proposed, not silently absorbed.
10. Exploration and canonical work are different modes. Cheap, disposable experiments come before frozen ones.
11. Escalate decisions, not ordinary problems.
12. Choose task size from measurements, not doctrine.

## Architecture and quality

13. Every abstraction, service or workflow component needs a present need. Plausible is not necessary.
14. Clarity matters more than compression.
15. Make ownership explicit: contracts, dependency direction, state ownership, side effects, failure behaviour.
16. Do not rebuild an existing engine. The coding agent owns its loop; Relay steers it.
17. Fix failures at their owning layer; do not weaken a contract to make a check pass.

## Review and agent behaviour

18. Agents should challenge weak requirements and say so plainly, separating advice from hard limits.
19. No self-acceptance: an implementer's tests are evidence, not acceptance.
20. Reviewers inspect evidence (diffs, behaviour, negative tests), not narratives.
21. Batch real questions; decide reversible details locally.
22. Agents optimize the task over the intent: given tests that contradict the spec, strong models often edit the tests. Keep tests and rules read-only to the implementer during a run.
23. Reviewers favour output from their own model family; review with a different family.

## Evidence and science

24. Separate exploratory diagnostics from canonical evidence runs.
25. Fail closed at the consequential boundary, not at every repair step.
26. Keep complete evidence of the first divergence: requests, responses, identities, transformations.
27. Distinct claims need distinct proof: mathematical validity, numerical correctness, empirical validation and production acceptance are not the same.

## Memory, docs and Git

28. One living memory per piece of work, not one per subtask or review.
29. Memory is not authority; current constraints come from the repository's source of truth.
30. One developer needs `main` plus short-lived PR branches, not a branch per role or approval. The first attempt reached 188 branches.
31. File equivalence is not Git ancestry; check a pull request's full diff and history.
32. Status lives in issues and pull requests. Status text in long-lived docs goes stale within days.

## Cost and focus

33. Governance is only worth its friction when it catches real problems. Measure it: human "proceed" turns, rework, context reloads, tokens, escaped defects.
34. Report cost per accepted change, not cost per token. Cheaper models only save money if retries and re-steering do not eat the savings.
35. Agents underestimate task size consistently. Across PRs #12–#29, actual net source lines ran 1.3–1.7× Claude Code's own estimate at the start of each issue: calibration, not bloat. Apply about 1.5× to a raw estimate. This is the first measured data point on task size.
