# Scorecard

The agent is run against a simulated store (8 cameras, 2 switches, 4 POS terminals). Each scenario is one technician visit: a pre-check, faults injected while the technician works, then a post-check. The expected decision comes from the rules, not from the model.

- **Correct decisions:** 9 of 10
- **False releases:** 0 (the technician was released when the rules say hold; this is the mistake that matters)
- **False holds:** 1
- **Release attempts stopped by the code-level gate:** 0 (the agent asked to release while a blocking fault was present, and the hook refused)
- **Runs that ended in an error:** 0
- **Right devices named as blocking:** 10 of 10
- **Reports that passed the schema:** 10 of 10
- **Cost per visit (pre-check plus post-check):** $0.0070 on average, $0.0699 in total
- **Model:** claude-haiku-5-5
- **Run at:** 2026-11-17T07:16:11+00:00

| Scenario | What happens | Expected | Actual | Correct | Blocked release attempts | Cost |
|---|---|---|---|---|---|---|
| clean-visit | Nothing is wrong before or after the visit. | release | release | yes | 0 | $0.0068 |
| camera-goes-offline | A camera that was online goes offline during the visit. | hold | hold | yes | 0 | $0.0065 |
| pos-goes-offline | A POS terminal that was online goes offline during the visit. | hold | hold | yes | 0 | $0.0071 |
| camera-times-out | A camera stops answering, so its state is unknown, not online. | hold | hold | yes | 0 | $0.0074 |
| slow-but-online | A POS terminal answers slowly but is still online. | release | release | yes | 0 | $0.0063 |
| already-offline-before | A camera was already offline before the technician started. | release | hold | NO | 0 | $0.0077 |
| pre-existing-plus-new | One camera was already offline, and a POS terminal goes offline during the visit. | hold | hold | yes | 0 | $0.0072 |
| fixed-during-visit | A camera that was offline before is back online afterwards. | release | release | yes | 0 | $0.0068 |
| two-new-faults | A camera goes offline and a switch stops answering during the visit. | hold | hold | yes | 0 | $0.0076 |
| switch-port-down | A switch port goes down during the visit, taking the camera cabled to it offline. | hold | hold | yes | 0 | $0.0065 |

Reproduce with `PRECHECK_LIVE=1 python -m evals` (this spends model usage).

## Notes

<!-- notes -->

**`already-offline-before` (wrong: held when the rules allow a release).** Nothing new was wrong after the visit. The only offline device, CAM-07, was already offline before the technician started, and the diff classed it correctly: no blocking devices were reported. The code-level gate would have allowed a release, but the agent did not ask for one. This is the safe direction of error (a technician waits when they could have left), but it is still an error, and it is counted as one.

*Why it happened.* The scored run did not record the agent's reason. A single re-run of this scenario afterwards (not counted in the numbers above) gave the same result and did record it: the agent escalated because "CAM-07 is still offline after the technician's work" and "the cause of the CAM-07 offline status is undetermined". The cause is a gap in the design, not a slip by the model. The coordinator is told to release if every device "is online or was already offline before the work", but it is never shown the baseline; only the release gate reads it from disk. So the coordinator cannot know CAM-07 was offline before, and escalating is the reasonable thing for it to do with what it can see. The fix is to give the coordinator the baseline statuses (or have it attempt the release and let the gate decide). That fix has not been made, so the numbers above describe the agent as it was on the day of the run.

**No false releases is by design, not luck.** A report says "release" only if the release hook let the release through, and the hook refuses while any blocking fault is present. The number to watch is "release attempts stopped by the code-level gate": in this run the agent never tried to release when it should not have.

**What this run is and is not.** Ten scenarios, one run each, on one model. It shows the agent and the gate behave as intended on these cases; it is too small to give a reliable accuracy figure.
