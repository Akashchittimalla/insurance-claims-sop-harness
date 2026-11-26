# Architecture

The browser communicates with Next.js on one origin. Server-side gateway routes validate mutation origins, keep the session bearer in an HttpOnly cookie, and forward authorized requests to FastAPI. Compose binds only the frontend to host loopback. The backend listens on the Compose network, with a named volume for SQLite.

```mermaid
flowchart LR
    Browser -->|Same origin| Next[Next.js and gateway]
    Next -->|Session bearer| API[FastAPI]
    API --> Flow[LangGraph and SOP guards]
    Flow -->|Redacted input and typed proposals| LLM[Mock or configured adapter]
    Flow --> Tools[Tool authorization gateway]
    Tools --> Repos[Owner-scoped repositories]
    Repos --> DB[(SQLite demo volume)]
    Flow --> Summary[Consent and summary transaction]
    Summary --> DB
```

```mermaid
stateDiagram-v2
    [*] --> VERIFY_ID
    VERIFY_ID --> RESOLVE_INTENT: Deterministic identity and eligibility check
    RESOLVE_INTENT --> PROCESS_CASE: Resolve an authorized case
    PROCESS_CASE --> POST_PROCESS: Explicit end of claim discussion
    POST_PROCESS --> [*]: Explicit simulated send, skip, or guarded timeout
```

A message is bound to a session and an idempotency key. The verifier requires three distinct matching fields from the same eligible party. Policy and relationship only select or restrict the lookup. Local code authorizes transitions and disclosures. The claim gateway checks eligibility and the repository repeats owner scoping in SQL. The case read feeds a deterministic evidence and response layer. The summary offer has a current revision, a registered masked recipient, and a single durable disposition per session. See [SPEC](../SPEC.md) for recovery and exceptional states.

Mock reasoning, handoff, and email are the default. The backend alone receives provider credentials. The configured OpenAI transport is opt-in and has an offline HTTP contract test. Incomplete verification values live in process memory. Durable SQLite state includes session state, idempotency records, and summary dispositions. See [deployment](DEPLOYMENT.md) for runtime evidence and [security audit](SECURITY_AUDIT.md) for production limits.

```mermaid
sequenceDiagram
    participant B as Browser
    participant G as Next.js gateway
    participant A as FastAPI
    participant D as SQLite
    B->>G: Send chat turn or summary choice
    G->>G: Check origin and read session cookie
    G->>A: Forward turn with bearer
    A->>D: Load session and check replay
    A->>A: Apply SOP and consent rules
    A->>D: Store changes and result atomically
    A-->>G: Safe response
    G-->>B: Update workspace
```

```mermaid
flowchart LR
    Client[Host browser] -->|127.0.0.1 port 3000| Front[Frontend container]
    subgraph claims[Compose bridge]
        Front -->|backend port 8000| Backend[Backend container]
    end
    Backend --> Data[(insurance_data volume)]
```
