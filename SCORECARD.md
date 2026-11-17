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
