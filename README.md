# Embassy Manager public data

Reviewed public-source editions for an independent educational app. Visitor tasks, reports and preferences never enter this repository.

The `main` branch holds the bounded collector and its review policy. The `public-data` branch holds reviewed editions, a manifest and collection metadata. The first edition describes Japan's May 15, 2025 advisory as historical; it is not presented as a new policy announcement.

The collection workflow checks at 7, 22, 37 and 52 minutes past the hour, using a standard Ubuntu runner only in this public repository. Source requests are shared and limited to once per six hours. Current admission covers the official travel-advisory feed and Federal Register discovery metadata, with one reviewed Tokyo item. New or changed items wait for review. Scheduling is best-effort.

No paid runners, uploaded artifacts, caches, model calls, accounts or application runtime. Publishing stops at the configured storage limits. Set `enabled` to false in the policy or disable the workflow to stop collection. The website update client is activated separately.

See [collector rules](docs/COLLECTOR.md) and [source admissions](data/collection-admissions.json).
