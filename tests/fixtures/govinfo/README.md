# GovInfo metadata discovery fixtures

These are complete anonymous public responses reviewed on October 6, 2026. Request records preserve their source URLs, response headers, byte counts and hashes. `fixture-manifest.json` records every retained source file. No test fetches a network resource.

The October 5 Federal Register issue contains 108 direct constituent records: 106 numbered documents, front matter and reader aids. Nested rendition/citation records are not additional documents. The parser produces only hashes, official document URLs and the issue publication date. It does not publish titles, abstracts, contacts or policy conclusions.

The complete example document `2026-20384.htm` is retained separately to verify the existing full-document parser. Its content hash differs from the metadata hash. No source or event admission is added by these fixtures; the active policy and workflow are unchanged.

[GovInfo's access description](https://www.govinfo.gov/about/index.html) documents free public access. [Content Details](https://www.govinfo.gov/help/content-details) describes downloadable Metadata Object Description Schema files and separate documents within an issue. [GovInfo's copyright policy](https://www.govinfo.gov/about/policies) generally permits government-authored material while retaining exceptions for incorporated third-party works and licensed images. Complete versions of these three evidence pages are included; their image resources were not fetched.

Discovery requires a separately admitted, exact issue URL and `metadataOnly: true`. Automatic rolling issue selection, event approval and workflow activation are outside this change. Complete-document editorial review is still required before any country/role association, summary or policy status can be published.
