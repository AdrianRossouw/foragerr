## MODIFIED Requirements

### Requirement: FRG-NFR-006 — bounded, verified outbound requests

Every outbound HTTP request SHALL have explicit connect and read timeouts, TLS certificate verification enabled by default (any per-host override is explicit, logged, and security-documented), a bounded redirect count, and bounded response size where the response is parsed.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §4 (no timeout in cv.pulldetails; CV_VERIFY global disable); mylar-ddl.md §4 (verify=False to FlareSolverr, blind redirect following, SSRF).
- **Notes**: Enforce by funnelling all outbound traffic through one shared client factory — makes the acceptance testable and gives NFR redaction and politeness a single choke point.

#### Scenario: All outbound traffic flows through the shared client factory with timeouts and TLS verify

- **WHEN** the codebase is checked for outbound HTTP call sites (static check plus client-construction test)
- **THEN** every outbound request is issued via the single shared `httpx.AsyncClient` factory with no direct `httpx`/`requests` call site outside it, every client the factory produces carries explicit connect, read, write, and pool timeouts (none defaulted to unlimited), and TLS certificate verification is enabled with no per-call or per-host opt-out parameter exposed by the factory API

#### Scenario: Hung server aborts at the configured timeout

- **WHEN** a request is made through the factory client to a mock server that accepts the connection but never sends a response body
- **THEN** the request fails with a timeout error at the configured read timeout (observed duration within tolerance of the configured value), and the calling worker/task is released rather than wedged

#### Scenario: Redirect chain is walked manually and bounded at 5 hops

- **WHEN** a mock server returns a chain of 6 redirect responses
- **THEN** the client (auto-redirects disabled; hops walked manually) stops after the 5th hop and raises a bounded too-many-redirects error, and a 4-hop chain to a valid target succeeds with each hop observable to the egress-validation layer (FRG-SEC-001)

#### Scenario: Oversize and slow-drip responses are aborted by the streaming byte cap

- **WHEN** a parsed-response fetch streams a body that exceeds the configured maximum byte cap (including a server that omits/lies in Content-Length and drips an unbounded body)
- **THEN** the response is aborted at the cap with a bounded, logged error; no unbounded buffer is accumulated in memory and the partial body is not handed to any parser

### Requirement: FRG-NFR-008 — secret redaction in logs and errors

The system SHALL redact secret material (API keys, passwords, session tokens, auth headers, key-bearing URLs) from all log output, error messages, exception traces, and diagnostic artifacts.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §1.2/§4 (CV key embedded in logged URLs); mylar-feature-surface.md §8 (carepackage stripping); CLAUDE.md Secrets ("never echo them into files, logs").
- **Notes**: Implement as a logging filter plus the outbound-client choke point — the same machinery serves the DEP diagnostic bundle. Complements (does not replace) "send keys outside the URL".

#### Scenario: Registered secret values never reach any handler unmasked

- **WHEN** the configuration is loaded with known sentinel secret values (API keys, passwords) and logging-heavy paths are exercised (outbound client errors, config dumps, failure paths)
- **THEN** each secret-valued config field self-registers with the redaction filter at config load time, and the sentinel values never appear in output captured from any attached log handler — every occurrence is replaced with a mask token

#### Scenario: Redaction covers messages, args, and formatted exception traces

- **WHEN** log records are emitted that carry a sentinel secret (a) inline in the message string, (b) via a `%s`/args parameter, and (c) inside the text of a formatted exception traceback (e.g., an httpx error whose URL embeds the key)
- **THEN** all three record forms are masked before reaching any handler; the captured output for each case contains the mask token and not the sentinel

#### Scenario: api_key-shaped URL query parameters are masked

- **WHEN** a URL containing a credential-bearing query parameter (e.g., `?api_key=…`, `?apikey=…`) is logged by the shared HTTP client or any other path
- **THEN** the parameter value appears masked in the captured log line even if that specific value was not pre-registered as a config secret, while non-secret query parameters remain readable

### Requirement: FRG-NFR-009 — configuration validation at startup

The system SHALL validate the entire effective configuration (types, ranges, interval minimums, required-when-enabled dependencies, path existence/writability) at startup, failing fast with messages naming each offending key and expected form; out-of-range intervals are clamped with a warning rather than failing.

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §7 (typed _CONFIG_DEFINITIONS, interval min-clamping); sonarr-architecture.md §7.2 (validated settings contracts).
- **Notes**: Pydantic settings models give this nearly for free. DEP owns config sources/precedence /migration; NFR owns validation semantics — dedup hint for the orchestrator.

#### Scenario: Invalid configuration fails fast with field-precise errors

- **WHEN** the application starts with a configuration containing a wrong-typed value and a nonexistent/unwritable required path
- **THEN** startup fails before the listener binds, with a pydantic-settings validation report naming each offending key (field-precise, both errors reported in one pass) and the expected form/type for each

#### Scenario: Startup failure exits non-zero

- **WHEN** the process is launched with an invalid configuration
- **THEN** the process terminates with a non-zero exit code (observable to the container supervisor) rather than continuing in a partially configured state

#### Scenario: Out-of-range intervals are clamped with a warning

- **WHEN** the configuration supplies a polling/politeness interval below its documented safe floor (where the spec designates clamping rather than rejection)
- **THEN** startup succeeds, the effective value is the documented floor, and a warning log names the key, the supplied value, and the clamped value
