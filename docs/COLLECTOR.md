# Reviewed public collection

The local pipeline is implemented and tested. It has not been activated in a public repository or verified as a live scheduled service. `data/collection-policy.json` is disabled and `collector-template/collect.yml.disabled` cannot run from this application repository. Nothing here changes the frozen application release.

The intended public repository is `brand-on-fire/embassy-manager-data`, with collector code on its default branch and generated files on `public-data`. An anonymous check on October 6, 2026 confirmed the `brand-on-fire` account and returned 404 for that repository; this does not distinguish an absent repository from a private one. Creation, visibility verification, authentication, activation and deployed client verification remain with the release owner.

## What can be collected now

Two anonymous official feeds have documented admissions in `data/collection-admissions.json`. The collector parses the complete response or rejects it; it does not truncate an input to make it pass.

| Source | Admission and current use |
|---|---|
| [Department of State travel advisories](https://travel.state.gov/_res/rss/TAsTWs.xml) | Complete reviewed response: 614,413 bytes and 223 entries. Its publication dates have no time or timezone; those dates remain calendar dates. One Tokyo leadership record describes the historical Japan advisory issued May 15, 2025. It is not represented as a new announcement or proof of the current advisory level. |
| [Government Publishing Office Federal Register feed](https://www.govinfo.gov/rss/fr.xml) | Complete reviewed response: 113,878 bytes and 99 entries. Discovery metadata only. No underlying Federal Register article has been approved for dashboard prose. |

State supplies its feeds for readers and aggregators; its copyright page describes the public-domain status of government-authored consular information and exceptions for other works. GovInfo documents its feeds, free public access and copyright exceptions. These admissions cover links, dates, hashes and short reviewed factual paraphrases, not wholesale republication or photographs. [State feed documentation](https://travel.state.gov/content/travel/en/rss.html), [State copyright notice](https://travel.state.gov/content/travel/en/copyright-disclaimer.html), [GovInfo feeds](https://www.govinfo.gov/feeds), [GovInfo policies](https://www.govinfo.gov/about/policies).

There is no automatic prose generation, model call, automatic claim that a proposal is effective, or automatic inference of a role's authority. Feed titles and descriptions do not enter the public review queue. The queue contains source identifiers, complete-response and item hashes, URLs, publication dates, and change classifications. Feed disappearance means review is needed; it does not establish retraction.

## Collection and review behavior

The proposed scheduler checks every 15 minutes, at minutes 7, 22, 37 and 52. A post becomes due at 6 a.m. in its admitted IANA timezone. The standard library's timezone database handles daylight-saving changes. A delayed run catches up after 6 a.m.; it does not promise an exact-time delivery. GitHub can delay or drop scheduled jobs. [GitHub schedule documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

A shared source is fetched once per due tick and never more often than every six hours, including failed attempts. The initial policy admits two sources, a one-mebibyte response cap, a ten-second request timeout and a 48-hour stale threshold. At most four requests per source per 24 hours are permitted by the polling interval; Tokyo's edition-dependent source ordinarily needs one daily check. Metadata-only sources use the same six-hour minimum independently of post editions. No retries occur within a tick.

A new review binds both the complete-response hash and the complete-item hash, plus the publication date and exact source link. Once accepted, an unchanged item can retain its review when unrelated entries alter the feed. Changed item content cannot inherit that approval. Failed, stale, removed or changed sources preserve the last valid edition and expose a warning. A successful source check updates collection verification time, never the original editorial review date.

The review process is executable locally:

1. Select a candidate from `review-queue.json`. Obtain the complete admitted public feed without credentials and retain it temporarily for review. If the source changed since the queue entry, review the new complete response; do not reuse an obsolete response hash.
2. Inspect the complete selected item with `python3 scripts/collector.py --inspect-feed /absolute/path/feed.xml --source-id travel-advisories --item-url 'https://…'`. This parses the entire file, prints the complete selected entry and its hashes, and neither fetches nor approves anything. A Federal Register feed entry is only a pointer: read the complete linked document before summarizing it.
3. Add or revise an entry in `reviewedEvents`. Verify publication versus occurrence dates, proposal/effective/announcement status, source rights, conflicts, exact supported post and role identifiers, and every claim. Use titles of offices instead of personnel names. Expand acronyms or supply the application's existing glossary entry. Each `reviewChecks` value records editorial attestation; a Boolean cannot prove the underlying research.
4. For a correction, preserve the event identifier and include an explicit `correction` with kind, factual summary and reviewed date. Suspended, superseded and retracted events appear in correction metadata and source evidence, not current events. Deleting a previously published review is rejected; it is not a substitute for a correction. Visitor work is outside this pipeline.
5. Run the offline tests and replay complete source files before committing a reviewed policy change. The first live admission must match the collected full-response hash; a changed feed needs review or previously accepted durable state. Until that succeeds, the client retains its bundled data.

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

Warning statuses are `stale`, `failed` and `awaiting-review`. Correction kinds are `corrected`, `suspended`, `superseded` and `retracted`. `edition.publishedAt` is the most recent editorial review calendar date in that edition; it does not advance merely because the collector runs. Evidence identifiers are derived from the complete event identifier and source URL, so a corrected link receives a new evidence identifier while the event identifier stays stable. Correction identifiers refer to existing events; the client must preserve local tasks and reports when hiding corrected public items.

The actual offline Tokyo example is in `collector-template/example/manifest.json` and its referenced content-addressed envelope. It is evidence of local export behavior, not a live service response. Automated coverage does not replace the existing reviewed country context or establish worldwide news coverage.

## Free runner and storage boundaries

GitHub documents standard hosted runners in public repositories as free. Larger runners, private execution, artifacts and caches have separate charging rules. The inactive workflow uses only `ubuntu-24.04`, an exact public repository/visibility guard before runner allocation, five-minute timeout, one non-overlapping job, a pinned checkout action, and Python's standard library. It uses no uploaded artifacts, cache actions, paid runners, packages, model services, Cloudflare jobs or Cloudflare credentials. [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions).

At 15-minute intervals the schedule has at most 96 scheduled starts per day. Each start performs only bounded work. Anonymous source reads and raw public files require no paid service. Provider availability, rate limits and GitHub's scheduler still apply; this is not a guarantee of uninterrupted hosting. The design must stop rather than enable paid capacity.

`publish.py` independently checks the exact public repository's visibility and reported size before restore and publication. It runs only in an approved scheduled/manual GitHub workflow. The push uses that job's ephemeral repository token in process memory, with checkout credential persistence disabled. There are no stored user credentials or cloud secrets.

Generated working files are capped at 10 MiB: the manifest, metadata queue, collection state, two source snapshots per source, and three edition versions per post. Publication checks all paths, rejects symlinks or unexpected files, checks the current envelope hashes and byte counts, and rejects unsupported envelope fields. Snapshots contain reviewed prose or metadata; complete unreviewed articles are not published.

Git history uses ordinary parent commits. Unchanged generated files create no commit or push. Actual source attempts, review/status changes, or a due daily edition can create a commit. Persisting actual attempts is necessary to preserve the six-hour polling bound across ephemeral runners. A clock-only tick does not advance editorial dates or write files. Files retained at the branch tip are bounded; ordinary history still grows.

Before publication, the greater of GitHub's reported repository size and local full Git checkout storage, plus the generated payload, must remain below 200 MiB. Reaching either cap stops publication and writes a maintenance notice to the job summary; it does not increase a quota, buy capacity, force-push, or rewrite history. The reported provider size can lag, and the local check is conservative rather than an exact billing measurement. The first maintenance action is to stop collection and review the repository; a new retention decision requires review. No unlimited-growth claim is made.

## Local verification and activation

Run these without network or provider credentials:

```sh
python3 -m unittest discover -s tests -p test_collector.py -k CollectorTests
python3 -m unittest discover -s tests -p test_collector_publication.py
python3 scripts/collector.py
```

The final command only validates the disabled policy. For a full replay, put each complete admitted response in a temporary directory as `<source-id>.feed`, then run:

```sh
python3 scripts/collector.py --replay /absolute/path/feeds --now 2026-10-06T00:14:00Z --output /absolute/path/public/collector-state --export /absolute/path/public
```

Replay is offline and can evaluate a disabled policy without changing it. Tests cover complete date handling, daylight saving, delayed ticks, shared source reuse, malformed/oversized inputs, changed/removed records, retractions, stale retention, exact hashes, supported roles, acronym gates, no-op files, retention limits and mocked ordinary Git transport. They do not prove a scheduled run or remote client publication.

Stage an explicit disabled package with `python3 collector-template/package.py /absolute/path/new-empty-directory`; its `PACKAGE-REVIEW.json` records each source file and hash. The staging command never activates or publishes.

The release owner must verify the exact public-only package and owned repository, create or select the public repository, confirm no paid features, copy the inert workflow into `.github/workflows/collect.yml`, enable the reviewed collection policy and repository activation variable, and verify the first actual public-data commit and anonymous raw response. No provider changes have been performed by this collector work. The application must separately verify privacy and client fallback behavior against the live endpoint. Worldwide post-model evidence gaps remain separate from activation of this narrowly admitted source pipeline.
