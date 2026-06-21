# Context Governor

Modes are `off`, `report`, and `active`; decisions are allow, warn, escalate, block, and replace. Exact duplicate calls, dangerous commands, repository boundaries, and large outputs are evaluated deterministically. An active decision is downgraded to a warning when the adapter lacks the needed pre-call, confirmation, or model-visible replacement capability. This is a policy decision layer, not a sandbox.

