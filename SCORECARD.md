# Scorecard

The agent is run against a simulated store (8 cameras, 2 switches, 4 POS terminals). Each scenario is one technician visit: a pre-check, faults injected while the technician works, then a post-check. The expected decision comes from the rules, not from the model.

- **Correct decisions:** 10 of 10
- **False releases:** 0 (the technician was released when the rules say hold; this is the mistake that matters)
- **False holds:** 0
- **Release attempts stopped by the code-level gate:** 0 (the agent asked to release while a blocking fault was present, and the hook refused)
- **Runs that ended in an error:** 0
- **Right devices named as blocking:** 10 of 10
- **Reports that passed the schema:** 10 of 10
- **Cost per visit (pre-check plus post-check):** $0.0071 on average, $0.0713 in total
- **Model:** claude-haiku-5-5
- **Run at:** 2026-11-17T07:30:33+00:00

| Scenario | What happens | Expected | Actual | Correct | Blocked release attempts | Cost |
|---|---|---|---|---|---|---|
| clean-visit | Nothing is wrong before or after the visit. | release | release | yes | 0 | $0.0065 |
| camera-goes-offline | A camera that was online goes offline during the visit. | hold | hold | yes | 0 | $0.0065 |
| pos-goes-offline | A POS terminal that was online goes offline during the visit. | hold | hold | yes | 0 | $0.0071 |
| camera-times-out | A camera stops answering, so its state is unknown, not online. | hold | hold | yes | 0 | $0.0082 |
| slow-but-online | A POS terminal answers slowly but is still online. | release | release | yes | 0 | $0.0072 |
| already-offline-before | A camera was already offline before the technician started. | release | release | yes | 0 | $0.0072 |
| pre-existing-plus-new | One camera was already offline, and a POS terminal goes offline during the visit. | hold | hold | yes | 0 | $0.0071 |
| fixed-during-visit | A camera that was offline before is back online afterwards. | release | release | yes | 0 | $0.0070 |
| two-new-faults | A camera goes offline and a switch stops answering during the visit. | hold | hold | yes | 0 | $0.0079 |
| switch-port-down | A switch port goes down during the visit, taking the camera cabled to it offline. | hold | hold | yes | 0 | $0.0066 |

Reproduce with `PRECHECK_LIVE=1 python -m evals` (this spends model usage).

## Notes

<!-- notes -->

**The results above are the second run. The first run scored 9 of 10, and the scorecard is how the problem was found.**

| | Run 1 (before the fix) | Run 2 (after the fix, shown above) |
|---|---|---|
| Correct decisions | 9 of 10 | 10 of 10 |
| False releases | 0 | 0 |
| False holds | 1 (`already-offline-before`) | 0 |
| Cost per visit, average | $0.0070 | $0.0071 |
| Run at | 2026-11-17T07:16:11+00:00 | 2026-11-17T07:30:33+00:00 |
| Results file | `evals/results/scorecard-run1-before-fix.json` | `evals/results/scorecard.json` |

*What went wrong in run 1.* In `already-offline-before`, the only offline device, CAM-07, was already offline before the technician started. The diff classed it correctly and the code-level gate would have allowed a release, but the agent held. That is the safe direction of error (a technician waits when they could have left), but it is still an error.

*Why.* A single re-run of that scenario recorded the agent's reason: it escalated because "CAM-07 is still offline after the technician's work" and "the cause of the CAM-07 offline status is undetermined". The cause was a gap in the design, not a slip by the model. The coordinator was told to release if every device "is online or was already offline before the work", but it was never shown the baseline; only the release gate read it from disk. The coordinator could not know CAM-07 had been offline before, so escalating was the reasonable thing to do with what it could see.

*The fix.* The post-check instructions now list which devices were offline or unknown in the saved baseline, and still require every device to be checked again (commit "fix: show the coordinator the baseline in the post-check prompt"). The scenarios and expected answers were not changed between the two runs.

**No false releases is by design, not luck.** A report says "release" only if the release hook let the release through, and the hook refuses while any blocking fault is present. The number to watch is "release attempts stopped by the code-level gate": in both runs the agent never tried to release when it should not have.

**What these runs are and are not.** Ten scenarios, one run each per version, on one model. They show the agent and the gate behave as intended on these cases; the sample is too small to give a reliable accuracy figure, and a model can answer differently from one run to the next.
