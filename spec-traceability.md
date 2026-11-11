# Ovue specification reconstruction audit

## Status and method

This audit compares `spec.md` with the source messages and tool-displayed file contents preserved in this conversation. It does not claim access to the deleted originals. Git recovery was unavailable because the Irúo directory was not a Git repository when checked.

The specification is a reconstruction. Its headings, diagrams, and some prose were rewritten; it is not byte-identical to the deleted file or the exact artifact reviewed by the security agent. The security-review files themselves have not been restored by this audit. This document must not be presented as a replacement for those reviews or as a security certification.

Source precedence: an explicit later user decision supersedes an earlier one; an approved edit is evidence of the chosen implementation requirement; a review recommendation by itself is not an accepted requirement. Repeated security findings are not evidence that new scope was approved. Unresolved conflicts are retained and identified below.

No application code was changed or runtime behavior tested during this audit.

## Source catalogue

The labels below refer to identifiable messages in this chat. Search the quoted phrase to locate the source. These are conversation anchors, not invented file versions or recovered commits.

| Key | Source and identifying text | Authority |
|---|---|---|
| B | Original feature brief: “FEATURE 1: AGENT MESSAGE CHANNEL (replace the human courier)” | User-supplied initial requirements, acceptance test, non-goals, open questions, and reporting rules. |
| C | User contract decisions: “to should be an array”, “to should be ids”, “each registered entity should be given an id”, “ref should be a valid url only”, followed by `ref: {url, title?}` | User decisions evolving the original shape. |
| P3 | “SPEC REVIEW: patch list for modules/message/spec.md (v3)” | User-supplied protocol patch list; distinct from security-review-v3. |
| P4 | “SPEC REVIEW: patch list for modules/message/spec.md (v4)” | User-supplied protocol patch list. |
| P5 | “Spec review: Agent Message Channel (patch list v5)” | User-supplied protocol patch list. |
| P6 | “Spec review: Agent Message Channel (patch list v6)” | User-supplied protocol patch list. |
| E | “It isn't just notion. this can be used for any external reference” | User requirement to remove external-system coupling. |
| SNAP | Full file displayed after “Yes fix the spec for all the security loop holes 1-10” | Pre-hardening spec snapshot, including original sections and acceptance tests 1–31. |
| S1 | First security review, SEC-01 through SEC-10; user: “Yes fix the spec for all the security loop holes 1-10” | Broad authorization followed by concrete tool-visible edits for the first hardening pass. |
| S2 | Security-review-v2; user: “For the mvp should we fix 3, 5, 6 and 7 and call it a day?”, then “Go ahead” | Approved fair-share requirements, retention clarity, reserved operator ID, atomic sends, and documented trust assumptions. |
| S3 | Security-review-v3; user: “go ahead” after the proposed receiver deduplication and concrete reservation changes | Approved receiver requirements and reservations of one stream and ten unread deliveries in the ensuing patch. |
| S4 | Security-review-v4; user: “go ahead” after receiver-state and total-storage proposals | Approved replacement of premature handled-marking by receiver states; global storage exemption. |
| S5 | Security-review-v5; user: “Update spec.” after terminal acknowledgement and finite storage proposal | Approved terminal ack, finite record/byte limits, 80% warnings, and storage rejection. |
| S6 | Security-review-v6; user: “Let's go ahead with the mvp, document these as known issues” | Explicit deferral of race-safe storage-capacity enforcement and per-seat historical-storage fairness. |
| PKG | Latest package discussion: user “exactly... kindly fix” after the tree with root `pyproject.toml`, sibling `iruo/` and `ovue/` packages | Supersedes earlier nested project-root and message-module incubation layouts. |
| DEV | “strict structure and line by line comment”; “we don't do god files”; “let's slice it up and write one piece at a time”; preference for colocated tests | User implementation and teaching preferences. |
| FUT | Redis/NATS discussion: “I totally buy into your future plans” and “Should we document these as future plans?” | Future evaluation direction; no current backend migration or adapter implementation approved. |

## Requirement trace

“Present” means the requirement is stated in the current spec, not implemented or tested. “Restored” identifies omissions repaired by this audit. “Superseded” records why an earlier rule should not be reintroduced.

| Requirement | Source | Current location | Finding/disposition |
|---|---|---|---|
| Replace manual courier across changing agent tools | B context/problem | §1 | Present. |
| Provider independence and pointers owned by external systems | B, E | §§1–2, 4 | Present; Notion-only wording superseded. |
| Small server, minimal necessary framework, local or cheap hosting | B requirement 8 | §2 | Restored; remote hosting remains subject to later security gates. |
| One README with curl examples for every endpoint | B requirement 8 | §2, test 53 | Restored. Adding the requirement does not mean a README has been implemented. |
| Operator can open a traffic view and see every message | B requirement 7; P3 item 8 | §§2, 8–9, test 28 | Restored explicit view requirement; local CLI is the agreed MVP surface. |
| No waking/starting sessions, attachments, or Notion integration | B non-goals; E | §2 | Present. |
| Registered stable seat IDs; recipients use IDs | C; SNAP §5 | §§4–5 | Restored explicit registration assignment sentence. |
| Required kind rather than optional | C; P3 item 2; P4 item 5 | §4 | Present. Fixed enum: done, blocked, needs-decision, info, acknowledged. |
| `line` renamed to `description`, 120-character maximum | P4 item 1 | §4 | Present. Earlier 200-character `line` is superseded. |
| Description Unicode allowance narrowed to printable ASCII | P5 item 10; S1 tool-visible edits | §4, test 11 | ASCII was introduced in the approved hardening pass; not invented during reconstruction. |
| `to` array maximum 10, duplicates collapse, no self-send | P5 item 4 | §4, tests 12–13 | Restored explicit submitted-array limit. Deduplication does not permit an oversized request array. |
| Required ref, absolute URL, optional title | C; P3 item 1; P4 items 2–4 | §4 | Present. No service `fallback_ref_url` configuration; sender supplies a known page when needed. |
| Title ≤12, exact permitted alphabet | P4 item 2; S1 | §4, tests 10, 34 | Present. Title and URL remain opaque labels. |
| URL ≤2,048 characters | SNAP §4 | §4 | Present; number is supported by the displayed spec. |
| HTTPS, localhost HTTP exception, disallowed schemes | P5 item 1; S1 | §4, tests 9, 32 | Present. |
| Host allowlist and parser restrictions | P4 item 3; S1 SEC-02/03 and edits | §§4, 9–10 | Present; empty-list permissiveness was superseded by the hardening edits. |
| No query, fragment, userinfo, IP/IDN hosts, non-default ports | S1 concrete spec patches | §4, test 32 | Present; these were chosen restrictions, not new reconstruction decisions. |
| No URL fetching; public paths and secret prohibition | S1; S3 approved trust assumptions | §§4, 12 | Present. Secret detection is not guaranteed. |
| Token-derived sender; reject body `from` | P3 item 3; SNAP | §§4–5, test 8 | Present. |
| Renderable sender object with ID, display name, role | P3 item 6 | §4 | Present. |
| Independent per-recipient state, separate message/delivery IDs | P3 item 5; P4 item 6; P5 item 8 | §§4–5, 7 | Present. `delivery_state`/acked names remain superseded by `state`/read. |
| SSE id uses a per-recipient sequence, not delivery ID | P4 item 6 | §7 | Present. |
| At-least-once replay with stable delivery ID | P4 item 7; P5 item 9; P6 item 5 | §7, tests 6, 31 | Present. No exactly-once claim. |
| No-cursor unread backlog, multiple connections, 20-second heartbeat | P3 items 5 and 9 | §7, tests 14–15, 24 | Present. |
| Stream consumable with curl; single-line JSON payload | B requirement 3; P3 item 6 | §7, test 57 | Restored explicitly; SSE id and blank-line framing still apply. |
| Startup polling for tools unable to hold connections | B third open question; SNAP §8 | §7, test 57 | Restored explicitly. No session waking implied. |
| MCP can call same core later | B second open question; SNAP §3 | §3 | Present as a future transport, not current MVP implementation. |
| Own-seat inbox/stream only, foreign access 403 | B auth; P6 item 3 | §5, tests 12, 30 | Present. |
| Own-delivery ack; absent/foreign IDs share 404 | P6 item 3 | §5, test 29 | Present. |
| Idempotent repeated ack | P3 item 5 | §5, test 19 | Present. |
| Default inbox both states; unread=1 unread; unread=0 read | P3 open decisions; SNAP §§8, 12; P5 state rename | §5, test 55 | `unread=0` was omitted; restored from explicit P3 decision. |
| `/seats` includes operator and only public identity fields | P5 item 3; P6 item 4 | §5, test 16 | Present. |
| Local CLI administration, operator send/read/ack/log | P3 items 4, 8; P4 item 9 | §§5, 9 | Present. No HTTP admin endpoint. |
| Operator ID cannot be registered/imported/renamed | S2 SEC-06 approval | §9, test 45 | Present. |
| Token entropy ≥256 bits, hash only, constant-time comparison | P4 item 8; S1 SEC-06 edits | §9 | Present. Removed the reconstruction-added mandatory salt; predeletion requirement said “secure hash”. |
| Rotation re-enables a revoked seat | P5 item 2: “Today a revoked seat can never be re-enabled” | §9, test 54 | Restored explicitly. |
| Revocation atomic and streams close immediately | P3 item 10; S1 SEC-06 edits | §§7, 9 | Present as required behavior; not verified. |
| Terminal receiver state before ack | S4 receiver correction; S5 approval | §§4–5, test 56 | Present. Client obligation clarified; no added completion API or claimed server proof. |
| Receiver crash recovery and idempotency | S4 approval | §4, test 50 | Present; premature “record handled before action” remains superseded. |
| All-or-nothing send, quotas/sequences in transaction, commit before success | S2 SEC-07 approval | §§6, 8, tests 36, 47 | Present. |
| Persistence across restart, UTC ISO 8601 | B requirement 4; P4 item 10 | §8, test 27 | Present. |
| Safe structured audit records and operator permissions | S1 SEC-10 | §8, test 44 | Present. |
| Local directory 0700, files 0600, backup/export protections | S1 SEC-04/08 edits | §§8–9 | Present. |
| Same-user and terminal compromise are accepted trust boundaries | S2/S3 approved assumptions | §§9, 12 | Present. Stronger admin identity/IPC not added. |
| Non-local finite retention/purge and local bounded storage | S2 SEC-05; S4 then S5 amendments | §§8, 12, tests 48, 51–52 | Present. Indefinite duration up to capacity differs from unbounded storage; automatic local deletion was not approved. |
| Finite records/database bytes and 80% warnings | S5 proposal and approved patch | §8, tests 51–52 | Present. |
| Quotas: 60 sends/min, 4KiB, 8 streams/seat, 128 total, 100 unread, 1,000 replay | SNAP; S1 edits | §10 | Present. No additional numeric defaults invented. |
| One stream and ten unread slots reserved per seat; admission rejection | S3 approved patch | §10, test 49 | Present. |
| Test 46 reserved-capacity wording | S2 added test 46, later S3/S4/S6 decisions | Test 46 and note below tests | Earlier wording restored; later storage exception documented explicitly. |
| Storage fairness and concurrent capacity checks deferred | S6 explicit user decision | §§8, 12 | Present as known limitations; not falsely closed. |
| TLS/proxy/CORS/SSE deployment rules | S1 SEC-09 approved edits | §10, test 43 | Present; runtime checks not performed. |
| JSON errors, all validation issues, safe paths/codes/limits, no echoed input | P5 item 5; P6 item 3 | §5, tests 17, 29 | Present; 409 naming ambiguity is tracked below. |
| Report works/tested/could-not-test | B and P3/P4 reporting instructions | §13 | Restored. |
| Package location, future extraction, colocation, comments, focused files, one piece at a time | PKG; DEV | §§3, 13 | Added from later explicit user corrections, not represented as original reviewed text. |
| Module diagram nodes, boundaries, and arrows | SNAP §3 Mermaid block | §3 diagram | Restored from the displayed original: Operator and Admin outside the boundary; Service to Auth/Store/Log; Admin to Service/Auth/Log; Auth/Store/Log to one SQLite node. Only the old Irúo message-module label changes to the agreed Ovue package label. |
| Redis/NATS as future evaluation direction | FUT | §14 | Recorded as nonbinding; false triggers such as “multiple machines require Redis” were not restored. |

## Security-review dispositions

These entries track decisions, not claims that implementation has eliminated the vulnerabilities.

| Review | Items | Approved disposition and location |
|---|---|---|
| Security v1 | SEC-01 text, SEC-02 URL content, SEC-03 hosts | §4 restrictions and untrusted-data rules. ASCII does not prove truthful content. |
| Security v1 | SEC-04 local admin, SEC-06 credentials, SEC-09 deployment | §§9–10 requirements; local user remains trusted. |
| Security v1 | SEC-05 streams, SEC-07 resource abuse | §§7, 10 bounds; numeric limits came from tool-visible edits. |
| Security v1 | SEC-08 retention, SEC-10 logs | §8 requirements; later finite ceilings supersede unbounded local storage. |
| Security v2 | SEC-03 fairness, SEC-05 retention, SEC-06 reserved ID, SEC-07 transaction | Approved four fixes; later S4/S6 narrowed historical-storage fairness. |
| Security v2 | SEC-01 deceptive data, SEC-02 same user, SEC-04 path secrets, SEC-08 terminal, SEC-09 deployments | Documented receiver/deployment responsibilities and accepted local assumptions. No free-text removal or stronger admin isolation approved. |
| Security v3 | SEC-02 receiver dedup, SEC-04 nonzero reservation | Approved, then receiver handled-before-action rule corrected by S4. |
| Security v3 | SEC-01, SEC-03, SEC-05, SEC-06, SEC-07 | Untrusted content, public paths, same-user control, recipient/directory visibility documented. |
| Security v4 | SEC-02 receiver states, SEC-06 record capacity | Approved states; global storage exemption selected. |
| Security v4 | SEC-01, SEC-03, SEC-04, SEC-05 | Existing trust/privacy assumptions retained. |
| Security v5 | SEC-02 ack timing, SEC-03 storage abuse | Approved terminal ack and hard global limits. Per-seat historical-storage fairness was not implemented by that decision. |
| Security v5 | SEC-01, SEC-04, SEC-05, SEC-06 | Existing trust/privacy assumptions retained. |
| Security v6 | SEC-02 concurrent storage checks, SEC-03 historical-storage fairness | Explicitly deferred as known MVP issues by S6. |
| Security v6 | SEC-01 deceptive content, SEC-04 same user, SEC-05 path secrets, SEC-06 metadata | Existing assumptions retained; cannot claim these risks disappeared. |

## Corrections made in this audit

1. Restored small-server scope, README with curl examples, operator traffic view, and completion-report requirements from B.
2. Restored explicit stable ID assignment from C/SNAP.
3. Restored `unread=0` as read-only filtering from P3; default remains both states.
4. Restored token rotation after revocation from P5's stated purpose.
5. Restored startup polling and curl/SSE payload requirements from B/P3.
6. Removed the added mandatory salting detail; the original requirement was a secure hash. Hash construction remains an implementation choice.
7. Restored earlier test 46 wording and documented later narrowed guarantees rather than silently rewriting the test.
8. Clarified submitted-array size before duplicate collapse using P5's explicit “to array limits” instruction.
9. Added tests 53–57 as trace-derived coverage, clearly labeled new rather than pretending they were recovered numbered tests.
10. Recorded later package/development preferences and the already-discussed future infrastructure direction with their provenance.
11. After the user identified diagram drift, restored the module diagram's original nodes, arrows, and placement from SNAP. The prior audit did not catch the missing Operator/Traffic log nodes or the relocated Admin CLI. The package label is the only intentional change to that original Mermaid block.

## Unresolved source conflicts and implementation boundaries

These existed across the predeletion edits or were left unspecified. They are not silently resolved by this reconstruction.

| ID | Conflict or missing definition | Consequence |
|---|---|---|
| U1 | The error list names `conflict` for 409, while replay prose names `replay_unavailable`. Out-of-range cursor 400 and expired replay 409 also overlap without a precise range definition. | A single public replay error shape/range rule still needs to be settled when implementing the transport. |
| U2 | Test 32 says reject redirects; §4 says the service never fetches URLs. | The service cannot identify a redirect target without fetching. The original test cannot establish that remote URLs never redirect. No network fetching has been authorized to satisfy it. |
| U3 | Hard storage ceilings remain required, but S6 accepts non-race-safe storage prechecks as an MVP limitation. | The spec cannot honestly guarantee no concurrent overshoot until enforced and tested. Do not report this as a verified hard ceiling. |
| U4 | Test 46 originally covered broad shared-capacity fairness, while later decisions reserve only stream/unread slots and exempt historical storage. | Existing stream/read access may survive storage exhaustion, but new sends from another seat can still be denied. Do not promise that storage fairness was fixed. |
| U5 | Page sizes, pagination fields, most global rate limits, buffer limits, and record/byte ceilings are configurable without complete numeric defaults or public cursor shapes. | Choose and record these as implementation decisions in their own slice; do not present them as recovered values. |
| U6 | Terminal ack relies on receiver-local state, with no completion attestation in the HTTP contract. | The server cannot enforce true external completion. Client crash-ordering checks are required; do not add APIs or claim enforcement without a new decision. |

## Verification performed

- Read the reconstructed file on disk and compared the requirement families above with the conversation sources.
- Traced acceptance tests 1–31 to SNAP and protocol patches; tests 32–44 to S1; 45–48 to S2; 49–50 to S3/S4; 51–52 to S5.
- Marked tests 53–57 as new coverage derived from existing requirements, not exact recovered text.
- Retained unresolved source conflicts instead of claiming security sign-off or exact textual restoration.

This establishes traceable coverage of the identified requirements. It does not prove byte-for-byte identity, execution correctness, or complete security. The deleted security-review originals remain unrecovered.
