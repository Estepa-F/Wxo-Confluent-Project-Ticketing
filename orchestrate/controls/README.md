# Controls

Both controls are bound to `escalation_agent` and run before the model (`agent_pre_invoke`). They are imported by [`../rebuild_wxo.sh`](../rebuild_wxo.sh), which first removes an existing control with the same name.

| File | Control | What it does |
|---|---|---|
| [`pii_control.yaml`](pii_control.yaml) | `pii_escalation_input` | Masks emails, phones, card and bank account numbers, IP addresses, dates of birth, announced names, order numbers and French phone numbers with `[REDACTED]` |
| [`escalation_guardrails.yaml`](escalation_guardrails.yaml) | `escalation_guardrails` | Blocks jailbreak / prompt-injection attempts and harmful, violent, biased or sexual content, on input and output |

Import one by hand:

```bash
orchestrate controls import -f controls/escalation_guardrails.yaml
orchestrate agents deploy -n escalation_agent
```

"Policy binding ... already exists" means a control with this name is already on the instance: `orchestrate controls list`, then `orchestrate controls remove -n <name>`.

Details: [`docs/governance.md`](../../docs/governance.md).
