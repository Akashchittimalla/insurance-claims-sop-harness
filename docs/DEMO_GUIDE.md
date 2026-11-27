# Five-minute demo guide

Open the [hosted demo](https://insurance-claims-sop-harness-demo.onrender.com) or run the [local Docker demo](../README.md#run-locally-with-docker). Start each scenario with **New conversation**. Use the synthetic inputs below. The expected behavior is illustrative. Wording may vary by provider.

## Quick path: Margaret in one turn

Click **Load Margaret's claim scenario**, or paste the complete opening, then send it:

> I'm the policyholder. My name is Margaret Chen, policy POL-9921. I'm calling about my denied healthcare claim from January. DOB is 1985-03-15, SSN last four is 4472.

The phase indicators show verification and intent resolution complete. The app enters **Process claim** with **CL-2048** and explains the recorded denial. Name, DOB and SSN last four count as three matching fields. The policy number is a lookup hint.

## Split turn: show the verification gate

| Turn | Send | What to observe |
| --- | --- | --- |
| 1 | I'm the policyholder. My name is Margaret Chen, policy POL-9921. DOB is 1985-03-15. I'm calling about my denied healthcare claim from January. | The app stays in `VERIFY_ID`. Name and DOB count as two fields. The policy number contributes zero. The claim hint is kept for later. |
| 2 | Why was it denied? | The app stays in `VERIFY_ID` and withholds the denial reason, documents and claim details. |
| 3 | My email is margaret@email.com. | The app verifies the third factor, uses the earlier claim hint, and resolves **CL-2048** without asking you to restate the request. |

## Grounded answers and summary

After either opening, send these separately:

1. **What if I can't obtain the pathology report?** Look for fixture-backed guidance on requesting a replacement copy. A substitute remains subject to review.
2. **How much did insurance pay?** The recorded payment is **USD 0.00**.
3. **That's everything.** The summary preview shows **CL-2048**, its recorded **denied** status, the topics discussed, and the documents still needed. The main next step is gathering the pathology report and treating provider office note for review. The replacement-copy instructions are in the chat response. The preview lists the required documents rather than repeating the full guidance.

Click **Send email summary** to record a simulated delivery to the masked registered address. Start another conversation, repeat the quick path, say **That's everything**, then click **Skip email**. Both choices complete their own session. Skip records a decline.

## Recovery examples

- **Repeated out-of-scope questions.** In a fresh session, send **What is reinforcement learning?**, then **Explain RL.** The assistant keeps the conversation focused on claims and offers human help at the default threshold. Send **Yes please.** to accept the simulated representative handoff.
- **Frustrated caller declines SSN.** In a fresh session, send **I'm Margaret Chen. Tell me why my January healthcare claim was denied.** Then send **This is ridiculous. I've already told you who I am.** and **I'm not comfortable giving you my Social Security number.** The assistant acknowledges frustration and offers approved alternatives, such as phone or email. Send **My birthday is March 15, 1985.** and then **My email is margaret@email.com.** The app can verify with name, DOB and email, then use the saved claim hint.

[Verified desktop workspace](screenshots/verified-desktop.png) ? [Mobile workspace](screenshots/mobile-workspace.png)
