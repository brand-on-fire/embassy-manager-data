# Reviewed public collection

As of October 6, 2026, the separate public repository [brand-on-fire/embassy-manager-data](https://github.com/brand-on-fire/embassy-manager-data) contains the active collector on `main` and an initial reviewed Tokyo payload on `public-data`. Activation commit `ba5f4711b9cf441dd61ce78a28967904020c2bb7` enables its reviewed policy and guarded workflow. The release owner verified public visibility and anonymous manifest/envelope access. The first actual run, triggered by policy-workflow commit `f5d4b837cb7928e2675cb94291d9804836fc8e04`, completed at 02:00:28 UTC: [run 37401996288](https://github.com/brand-on-fire/embassy-manager-data/actions/runs/37401996288). All validation, restore, collection/export and publication steps passed on `ubuntu-24.04`; no artifacts were created. The publisher made ordinary public-data commit `de772ae0da68e5430da14a2bfad46b190caced77`. The existing Tokyo envelope and source-check dates remained unchanged because they were not due; this does not prove a fresh remote source fetch. A naturally scheduled run remains unverified.

The separate application repository retains a disabled collection policy and inert workflow template for packaging and offline tests. This public-data repository retains its enabled `data/collection-policy.json`; its active workflow requires its exact repository, public visibility and `main` ref before allocating a standard Ubuntu runner; it does not require a repository activation variable. The public-update client is enabled in the verified 134-workspace release, and a production browser trace captured the fixed public manifest request. Its initial reviewed payload is historical; this does not establish ongoing worldwide collection. Exact static-site release and browser evidence is maintained separately in the application repository’s `docs/DEPLOYMENT.md`.

## What can be collected now

Two anonymous official feeds are active. One additional reviewed document source is implemented and admitted locally in `data/collection-admissions.json`, and staged in the public-data repository working tree, but has not been published. The collector parses the complete response or rejects it; it does not truncate an input to make it pass.

| Source | Admission and current use |
|---|---|
| [Department of State travel advisories](https://travel.state.gov/_res/rss/TAsTWs.xml) | Complete reviewed response: 614,413 bytes and 223 entries. Its publication dates have no time or timezone; those dates remain calendar dates. One Tokyo leadership record describes the historical Japan advisory issued May 15, 2025. It is not represented as a new announcement or proof of the current advisory level. |
| [Government Publishing Office Federal Register feed](https://www.govinfo.gov/rss/fr.xml) | Complete reviewed response: 113,878 bytes and 99 entries. Discovery metadata only. Its issue-update timestamp is not the publication or effective date of an individual document. |
| [October 5 trade-consultation notice](https://www.govinfo.gov/content/pkg/FR-2026-10-05/html/2026-20341.htm) | Local admission only: complete 10,106-byte document reviewed; the notice opens consultation before the 2027 North American trade agreement review. It is routed to the four qualified leadership desks in Ottawa and Mexico City. It does not establish a treaty amendment or new trade restriction. |

State supplies its feeds for readers and aggregators; its copyright page describes the public-domain status of government-authored consular information and exceptions for other works. GovInfo documents its feeds, free public access and copyright exceptions. These admissions cover links, dates, hashes and short reviewed factual paraphrases, not wholesale republication or photographs. [State feed documentation](https://travel.state.gov/content/travel/en/rss.html), [State copyright notice](https://travel.state.gov/content/travel/en/copyright-disclaimer.html), [GovInfo feeds](https://www.govinfo.gov/feeds), [GovInfo policies](https://www.govinfo.gov/about/policies).

There is no automatic prose generation, model call, automatic claim that a proposal is effective, or automatic inference of a role's authority. Feed titles and descriptions do not enter the public review queue. The queue contains source identifiers, complete-response and item hashes, URLs, publication dates, and change classifications. Feed disappearance means review is needed; it does not establish retraction.

## Collection and review behavior

The active workflow schedules checks every 15 minutes, at minutes 7, 22, 37 and 52. Changes to collector policy, code, tests or workflow on `main` also run the same bounded checks; generated `public-data` commits do not trigger them. A post becomes due at 6 a.m. in its admitted IANA timezone. The standard library's timezone database handles daylight-saving changes. A delayed run catches up after 6 a.m.; it does not promise an exact-time delivery. GitHub can delay or drop scheduled jobs. [GitHub schedule documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

A shared source is fetched once per due tick and never more often than every six hours, including failed attempts. The initial policy admits two sources, a one-mebibyte response cap, a ten-second request timeout and a 48-hour stale threshold. At most four requests per source per 24 hours are permitted by the polling interval; Tokyo's edition-dependent source ordinarily needs one daily check. Metadata-only sources use the same six-hour minimum independently of post editions. No retries occur within a tick.

A feed review binds both the complete-response hash and the complete-item hash, plus the publication date and exact source link. The explicitly selected document-content binding below is the only exception to the initial whole-response equality requirement. Once accepted, an unchanged item can retain its review when unrelated entries alter the feed. Changed item content cannot inherit that approval. Failed, stale, removed or changed sources preserve the last valid edition and expose a warning. A successful source check updates collection verification time, never the original editorial review date.

The local `govinfo-fr-html` parser accepts only an explicit `www.govinfo.gov/content/pkg/FR-YYYY-MM-DD/html/<document-number>.htm` source. It requires a complete single document body, agreeing issue-header date and weekday, matching document number and complete filing footer. The header supplies the publication date; filing and feed-update timestamps remain separate. The complete raw response hash is retained as provenance. An explicit `complete-document-content-v1` review binds the entire decoded document text, including whitespace, plus every article link target in source order. Identified Cloudflare email fields are decoded before hashing: the changing XOR key is ignored, but the actual email address remains part of the text and link-target hash. No decoded address is published. The full article is never excerpted or truncated. Header, document number, footer, date, prose or meaningful link changes still fail the reviewed hash. Malformed protected fields and unsupported body markup are rejected. Source bodies and personal contacts are never stored in the public output. The existing one-mebibyte response cap, two-request tick cap and six-hour minimum remain unchanged. The binding is valid only for `govinfo-fr-html` and must be explicitly set on the reviewed event. Without it, first admission still requires the raw source hash. The initial exact-hash rule for the other feed parsers is unchanged.

These notices use `precision: relevance`. The existing dashboard renders “Relevant to Canada” or “Relevant to Mexico”; neither association asserts that the notice occurred physically in those countries. The parser does not turn a proposal into an effective measure or automatically admit new document links. New documents still need complete source review and explicit role mappings. A future automatic metadata-only template would need distinct machine-check provenance; it must not fabricate human review attestations.

The review process is executable locally:

1. Select a candidate from `review-queue.json`. Obtain the complete admitted public feed without credentials and retain it temporarily for review. If the source changed since the queue entry, review the new complete response; do not reuse an obsolete response hash.
2. Inspect the complete selected item with `python3 scripts/collector.py --inspect-feed /absolute/path/feed.xml --source-id travel-advisories --item-url 'https://…'`. This parses the entire file, prints the complete selected entry and its hashes, and neither fetches nor approves anything. A Federal Register feed entry is only a pointer: read the complete linked document before summarizing it.
3. Add or revise an entry in `reviewedEvents`. Verify publication versus occurrence dates, proposal/effective/announcement status, source rights, conflicts, exact supported post and role identifiers, and every claim. Use titles of offices instead of personnel names. Expand acronyms or supply the application's existing glossary entry. Each `reviewChecks` value records editorial attestation; a Boolean cannot prove the underlying research.
4. For a correction, preserve the event identifier and include an explicit `correction` with kind, factual summary and reviewed date. Suspended, superseded and retracted events appear in correction metadata and source evidence, not current events. Deleting a previously published review is rejected; it is not a substitute for a correction. Visitor work is outside this pipeline.
5. Run the offline tests and replay complete source files before committing a reviewed policy change. The first live feed admission must match the collected full-response hash; a changed feed needs review or previously accepted durable state. An explicitly reviewed GovInfo document may instead match its complete-document-content hash after the exact URL and document/date checks pass. Until that succeeds, the client retains its bundled data.

Newly approved wording is eligible on a due tick after the post's local 6 a.m. The same-day review digest permits a reviewed correction to update an existing edition. The collector cannot decide whether human research was complete or a legal/policy interpretation is correct.

## Static client contract

The fixed anonymous base is `https://raw.githubusercontent.com/brand-on-fire/embassy-manager-data/public-data/`. The client reads the small manifest and only the selected post's envelope, without cookies, credentials, referrer or visitor-authored fields. The app must validate the exact allowlisted origin, path, byte count, content hash, source references and edition schema before using an envelope. Missing, rejected or unavailable remote data must leave the bundled last valid edition usable. The client bridge is owned and verified separately from this collector.

`manifest.json` has `schemaVersion:1`, `generatedAt:string|null`, and `posts:[{postId,path,sha256,bytes}]`. Each path is exactly `editions/<postId>/<sha256>.json`. An envelope is limited to 500,000 bytes and has:

```text
schemaVersion: 1
postId: known post identifier
generatedAt: actual collector edition timestamp
edition: existing Edition, mode reviewed-public, suggestions []
sources: Source[] with original editorial verification dates
corrections: [{eventId,kind,summary,reviewedAt,sourceIds}]
collection: {
  sourceCheckedAt: minimum successful source verification timestamp or null,
  sourceWarnings: [{sourceId,status,lastVerifiedAt}],
  reviewState: reviewed | retained-last-valid
}
```

Timestamp strings are UTC ISO values and may contain up to six fractional-second digits, as produced by Python’s actual clock. Preserve the original string for content-hash verification; browser date normalization must not reject a valid microsecond timestamp. Calendar-only publication and editorial dates remain `YYYY-MM-DD`.

Warning statuses are `stale`, `failed` and `awaiting-review`. Correction kinds are `corrected`, `suspended`, `superseded` and `retracted`. `edition.publishedAt` is the most recent editorial review calendar date in that edition; it does not advance merely because the collector runs. Evidence identifiers are derived from the complete event identifier and source URL, so a corrected link receives a new evidence identifier while the event identifier stays stable. Correction identifiers refer to existing events; the client must preserve local tasks and reports when hiding corrected public items.

The actual offline Tokyo example is in `collector-template/example/manifest.json` and its referenced content-addressed envelope. It is evidence of local export behavior, not a live service response. Automated coverage does not replace the existing reviewed country context or establish worldwide news coverage.

## Free runner and storage boundaries

GitHub documents standard hosted runners in public repositories as free. Larger runners, private execution, artifacts and caches have separate charging rules. The active data-repository workflow uses only `ubuntu-24.04`, an exact public repository/visibility/main-ref guard before runner allocation, five-minute timeout, one non-overlapping job, a pinned checkout action, and Python's standard library. It uses no uploaded artifacts, cache actions, paid runners, packages, model services, Cloudflare jobs or Cloudflare credentials. [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions).

At 15-minute intervals the schedule has at most 96 scheduled starts per day. Each start performs only bounded work. Anonymous source reads and raw public files require no paid service. Provider availability, rate limits and GitHub's scheduler still apply; this is not a guarantee of uninterrupted hosting. The design must stop rather than enable paid capacity.

`publish.py` independently checks the exact public repository's visibility and reported size before restore and publication. It runs only in the approved public repository on the main ref, for scheduled, manual or filtered main-branch push events. The push uses that job's ephemeral repository token in process memory, with checkout credential persistence disabled. There are no stored user credentials or cloud secrets.

Generated working files are capped at 10 MiB: the manifest, metadata queue, collection state, two source snapshots per source, and three edition versions per post. Publication checks all paths, rejects symlinks or unexpected files, checks the current envelope hashes and byte counts, and rejects unsupported envelope fields. Snapshots contain reviewed prose or metadata; complete unreviewed articles are not published.

Git history uses ordinary parent commits. Unchanged generated files create no commit or push. Actual source attempts, review/status changes, or a due daily edition can create a commit. Persisting actual attempts is necessary to preserve the six-hour polling bound across ephemeral runners. A clock-only tick does not advance editorial dates or write files. Files retained at the branch tip are bounded; ordinary history still grows.

Before publication, the greater of GitHub's reported repository size and local full Git checkout storage, plus the generated payload, must remain below 200 MiB. Reaching either cap stops publication and writes a maintenance notice to the job summary; it does not increase a quota, buy capacity, force-push, or rewrite history. The reported provider size can lag, and the local check is conservative rather than an exact billing measurement. The first maintenance action is to stop collection and review the repository; a new retention decision requires review. No unlimited-growth claim is made.

## Local verification and activation

Run these without network or provider credentials:

```sh
python3 -m unittest discover -s tests -p test_collector.py -k CollectorTests
python3 -m unittest discover -s tests -p test_collector_publication.py
python3 -m unittest discover -s tests -p test_collector_documents.py
python3 scripts/collector.py
```

Here, the final command validates the enabled policy without collecting: network collection additionally requires the explicit `--collect` argument. For a full replay, put each complete admitted response in a temporary directory as `<source-id>.feed`, then run:

```sh
python3 scripts/collector.py --replay /absolute/path/feeds --now 2026-10-06T00:14:00Z --output /absolute/path/public/collector-state --export /absolute/path/public
```

Replay is offline and can evaluate a disabled policy without changing it. Tests cover complete date handling, daylight saving, delayed ticks, shared source reuse, malformed/oversized inputs, changed/removed records, retractions, stale retention, exact hashes, supported roles, acronym gates, no-op files, retention limits and mocked ordinary Git transport. They do not prove a scheduled run or remote client publication.

This public-data working tree passes 46 collector/publication/document tests. The separate application checkout passes 54 tests including its static-site preflight tests; those preflight assets are not part of this data repository. An offline replay preserved the accepted Tokyo entry and exported the newly reviewed Ottawa and Mexico City notices. Its allowed payload passed the storage guard: ten JSON files, 376,880 bytes, with source items containing only `itemHash`, `url` and `publishedAt`. The application repository’s `data/collection-semantic-replay-evidence.json` records the final output paths, hashes and limitations. Its first admission accepts the separately retained fresh response despite different raw markup, with no prior accepted state for this document. The earlier replay files describe the superseded raw-hash-only prototype. The replay is not an active scheduled run or public publication. The public-data working tree now contains the parser, appended source admission and dedicated tests. Existing feed receipt hashes and their bootstrap verification date are preserved; the new document has its own review timestamp. The ledger’s `updatedAt` records only this local metadata edit. Its enabled policy, existing Tokyo approval, schedule and repository guards are preserved; no commit, push or workflow run was invoked.

The separate application repository can stage a disabled package with its `collector-template/package.py` script. This data repository’s `PACKAGE-REVIEW.json` instead records the current enabled-policy working-tree update and file hashes; it is not proof of publication.

The remaining live checks are the first naturally scheduled run, its bounded source checks and any resulting ordinary `public-data` commit, followed by deployed client loading and fallback verification. An unchanged tick may correctly create no commit. The original bootstrap audit found seven allowed JSON files, 322 source metadata entries, 321 unreviewed pointers without article bodies, and one reviewed historical Japan item with its accepted-review state. Full source bodies remain outside the public payload. Publication of the new local document admission, further automatic metadata admission and worldwide source coverage remain separate work.

First-run evidence: `evidence/collector-first-run.json`, `evidence/collector-first-run-details.json`, `evidence/collector-post-run-manifest.json`, `evidence/collector-post-run-collector-state-state.json`, and `evidence/collector-push-tests.log`. The new context test rejects other branches, pull-request events and failed fresh public-visibility checks; 18 collector and 20 publication tests passed before the change was pushed.
