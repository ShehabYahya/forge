# Lifecycle

Start creates `active` and returns prepared context. Review enters `reviewed` or `review_blocked`. A successful finish requires `reviewed` plus an unchanged Git digest and enters `completed`. A failed finish is always available from a nonterminal normal state and enters `failed`. Any edit after review makes that review stale. Degraded fallback enters `degraded` and is never lifecycle completion.

