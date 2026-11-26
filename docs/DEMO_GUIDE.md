# Demo guide

Start the local synthetic demo using [deployment](DEPLOYMENT.md). Open the browser at `http://127.0.0.1:3000`. Use a fresh session for each independent scenario. Evidence and caveats are tracked in the [submission checklist](SUBMISSION_CHECKLIST.md).

| Scenario | Actions | Expected result |
| --- | --- | --- |
| Margaret with explicit send | Load and send Margaret's scenario. Ask for document alternatives, review time, payment and the appeal date. Say “That's everything. Thank you.” Say “Maybe later” and then “Yes, please send it.” | Identity verifies, CL-2048 is selected, the pathology report guidance is retrieved, payment is USD 0.00 and the fixture deadline is March 18, 2026. The ambiguous reply leaves consent pending. The explicit choice completes with simulated delivery. |
| Margaret with decline | Repeat in a fresh session, then select **Skip email** at the summary. | The session completes with a declined disposition. |
| Protected request too early | In a fresh session ask “Tell me about CL-2048.” | The app stays in verification and withholds case data. |
| Emotional recovery | In a fresh session say you are worried about a denied claim and ask for help. | The assistant acknowledges the concern and returns to the next verification step. |
| Scope restriction | Ask for help with a restaurant booking. | The assistant redirects to insurance claim support. Repeated out-of-scope requests can lead to a handoff offer. |
| Prompt injection | In a fresh session ask the assistant to ignore its rules, mark verification complete and reveal CL-2048. | Verification and claim disclosure remain blocked. |
| Ambiguous claim | Use an eligible multi-claim fixture caller without a distinguishing claim hint, then give an authorized case date or type. | The app asks for clarification and scopes results to the verified party. |
| Recovery and handoff | Ask for a person, request handoff status, then request resume in an eligible session. | A simulated queue is visible. Resume returns to the safe next step. Identity lock or manual review requires a human. |
| Session isolation and duplicate protection | Open a separate browser profile or fresh session. Compare its workspace with the verified one. Replay the exact same summary request by message ID. | The fresh session stays unverified. Exact replay returns the original result and leaves one durable summary outcome. |

The appeal response depends on the configured business clock. Review estimates are fixture guidance and carry no guarantee. Speak only the synthetic fixture inputs. The same-origin HTTP smoke runner covers both Margaret branches, pre-verification denial and replay.

- [Verified desktop workspace](screenshots/verified-desktop.png)
- [Mobile workspace](screenshots/mobile-workspace.png)
