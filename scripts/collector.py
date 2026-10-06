#!/usr/bin/env python3
"""Bounded public-source collector. Inactive by default; standard library only."""
import argparse
import hashlib
import ipaddress
import json
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from html.parser import HTMLParser
from pathlib import Path
import re
import urllib.error
import urllib.request
from urllib.parse import urlparse
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

UTC = timezone.utc
REVIEW_CHECKS = ("completeInputReviewed", "dateSemanticsChecked", "roleRelevanceChecked", "rightsChecked", "personnelNamesRemoved", "acronymsChecked", "conflictsResolved")
PUBLIC_STATUSES = ("proposed", "announced", "effective", "historical", "reported")
DOCUMENT_REVIEW_BINDING = "complete-document-content-v1"


def calendar_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Expected a calendar date")
    return datetime.strptime(value, "%Y-%m-%d").date().isoformat()


def publication(value):
    """Keep date-only publications date-only; midnight is never an asserted source time."""
    return calendar_date(value) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value or "") else stamp(instant(value))


def publication_after(value, now):
    return value > now.date().isoformat() if len(value) == 10 else instant(value) > now


def safe_text(value, limit=10000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or re.search(r"[<>\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", value):
        raise ValueError("Reviewed text must be bounded plain text")
    return value


def digest(value):
    raw = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def instant(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Date must include a timezone")
    return parsed.astimezone(UTC)


def stamp(value):
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def public_url(value, hosts=None):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("A bounded public URL is required")
    parsed = urlparse(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.port not in (None, 443) or parsed.fragment):
        raise ValueError("Only credential-free public HTTPS URLs are accepted")
    try:
        ipaddress.ip_address(parsed.hostname)
    except ValueError:
        pass
    else:
        raise ValueError("Literal network addresses are forbidden")
    if "." not in parsed.hostname or parsed.hostname.endswith((".local", ".localhost", ".internal")):
        raise ValueError("A public hostname is required")
    if hosts is not None and parsed.hostname not in hosts:
        raise ValueError("Source hostname is not explicitly admitted")
    return value


def validate_policy(policy):
    if policy.get("schemaVersion") != 1 or not isinstance(policy.get("enabled"), bool):
        raise ValueError("Invalid collection policy")
    for key, ceiling in (("maxSourcesPerRun", 12), ("maxResponseBytes", 1048576), ("timeoutSeconds", 10), ("staleAfterHours", 168)):
        if not isinstance(policy.get(key), int) or not 1 <= policy[key] <= ceiling:
            raise ValueError("Unsafe collection limit: " + key)
    if not all(isinstance(policy.get(key), list) for key in ("allowedHosts", "sources", "posts", "reviewedEvents")):
        raise ValueError("Policy lists are required")
    source_ids = set()
    if len(policy["sources"]) > 12 or len(policy["posts"]) > 300 or len(policy["reviewedEvents"]) > 1000:
        raise ValueError("Collection inventory exceeds its hard cap")
    for source in policy["sources"]:
        if not re.fullmatch(r"[a-z0-9-]+", source["id"]) or source["id"] in source_ids:
            raise ValueError("Source identifiers must be unique safe slugs")
        source_ids.add(source["id"])
        public_url(source["url"], policy["allowedHosts"])
        if source.get("nonBillable") is not True or source.get("parser") not in ("json-feed", "rss-atom", "govinfo-fr-html"):
            raise ValueError("Source requires explicit non-billable admission and supported parser")
        if source["parser"] == "govinfo-fr-html":
            govinfo_document_url(source["url"])
        if not isinstance(source.get("pollMinutes"), int) or source["pollMinutes"] < 360:
            raise ValueError("Poll interval must be at least six hours")
        if not isinstance(source.get("dateOnlyPublication", False), bool):
            raise ValueError("Date-only parser admission must be explicit")
        if not isinstance(source.get("metadataOnly", False), bool):
            raise ValueError("Metadata discovery admission must be explicit")
    post_ids = set()
    for post in policy["posts"]:
        if not re.fullmatch(r"[a-z0-9-]+", post["id"]) or post["id"] in post_ids:
            raise ValueError("Post identifiers must be unique safe slugs")
        post_ids.add(post["id"])
        ZoneInfo(post["timezone"])
        if not post["sourceIds"] or not set(post["sourceIds"]).issubset(source_ids):
            raise ValueError("Post references unknown sources")
    event_ids = set()
    for event in policy["reviewedEvents"]:
        if not re.fullmatch(r"[a-z0-9-]+", event["id"]) or event["id"] in event_ids or event["sourceId"] not in source_ids or not event["postIds"] or not set(event["postIds"]).issubset(post_ids):
            raise ValueError("Reviewed event references are invalid")
        event_ids.add(event["id"])
        if event["status"] not in (*PUBLIC_STATUSES, "suspended", "superseded", "retracted"):
            raise ValueError("Unsupported event status")
        for key in ("sourceHash", "itemHash"):
            if not re.fullmatch(r"[a-f0-9]{64}", event[key]):
                raise ValueError("Review must bind complete source and item hashes")
        for key in ("publishedAt", "occurredAt"):
            publication(event[key])
        instant(event["reviewedAt"])
        if publication_after(event["publishedAt"], instant(event["reviewedAt"])):
            raise ValueError("Review predates publication")
        for key in ("title", "summary", "reviewedByRole"):
            safe_text(event.get(key))
        public_url(event["sourceUrl"])
        validate_review_binding(event, policy["sources"])
        if event.get("precision", "country") not in ("country", "relevance"):
            raise ValueError("Collected events require explicit country relevance or country location")
    if "publication" in policy:
        validate_publication_policy(policy)


def validate_publication_policy(policy):
    config = policy["publication"]
    if config.get("repository") != "brand-on-fire/embassy-manager-data" or config.get("branch") != "public-data":
        raise ValueError("Publication repository and branch must be explicitly approved")
    for key, ceiling in (("maxPayloadBytes", 10 * 1024 * 1024), ("maxRepositoryBytes", 200 * 1024 * 1024), ("editionVersions", 3), ("sourceVersions", 2)):
        if type(config.get(key)) is not int or not 1 <= config[key] <= ceiling:
            raise ValueError("Unsafe publication limit: " + key)
    for source in policy["sources"]:
        admission = source.get("admission", {})
        if admission.get("anonymousPublicRead") is not True or admission.get("permittedFeedUse") is not True:
            raise ValueError("Source access and feed-use evidence are required")
        calendar_date(admission.get("verifiedAt"))
        for key in ("accessEvidenceUrl", "rightsEvidenceUrl"):
            public_url(admission.get(key))
        safe_text(admission.get("scope"))
    posts = {post["id"]: post for post in policy["posts"]}
    for post in posts.values():
        safe_text(post.get("country"), 200)
        if not post.get("roleIds") or any(not re.fullmatch(r"[a-z0-9-]+", role) for role in post["roleIds"]):
            raise ValueError("Publication requires explicit supported role identifiers")
    for event in policy["reviewedEvents"]:
        validate_review_binding(event, policy["sources"])
        if any(event.get("reviewChecks", {}).get(key) is not True for key in REVIEW_CHECKS):
            raise ValueError("Incomplete editorial review")
        if event.get("precision", "country") not in ("country", "relevance"):
            raise ValueError("Collected events require explicit country relevance or country location")
        for key in ("sourceTitle", "publisher", "supports", "topic"):
            safe_text(event.get(key))
        if not event.get("roleIds") or any(not set(event["roleIds"]) & set(posts[pid]["roleIds"]) for pid in event["postIds"]):
            raise ValueError("Reviewed role mapping is not supported at each post")
        allowed_roles = {role for pid in event["postIds"] for role in posts[pid]["roleIds"]}
        if not set(event["roleIds"]).issubset(allowed_roles):
            raise ValueError("Reviewed event contains an unknown role")
        if event["status"] in ("suspended", "superseded", "retracted") or "correction" in event:
            correction = event.get("correction", {})
            if correction.get("kind") not in ("corrected", "suspended", "superseded", "retracted"):
                raise ValueError("A withdrawn or corrected event needs explicit correction metadata")
            if event["status"] not in PUBLIC_STATUSES and correction["kind"] != event["status"]:
                raise ValueError("Correction kind must agree with the withdrawn event status")
            safe_text(correction.get("summary"))
        terms = policy.get("acronyms", {})
        prose = [event[key] for key in ("title", "summary", "sourceTitle", "publisher", "supports", "topic")]
        if "correction" in event:
            prose.append(event["correction"]["summary"])
        for text in prose:
            if any(term not in terms for term in re.findall(r"\b(?:[A-Z]\.){2,}|\b[A-Z]{2,}\b", text)):
                raise ValueError("Reviewed publication contains an undefined acronym")


def validate_review_binding(event, sources):
    if "reviewBinding" not in event:
        return
    source = next((source for source in sources if source["id"] == event["sourceId"]), None)
    if event["reviewBinding"] != DOCUMENT_REVIEW_BINDING or not source or source["parser"] != "govinfo-fr-html":
        raise ValueError("Complete-document review binding is restricted to the admitted document parser")


def govinfo_document_url(url):
    public_url(url, ["www.govinfo.gov"])
    match = re.fullmatch(r"https://www\.govinfo\.gov/content/pkg/FR-(\d{4}-\d{2}-\d{2})/html/(\d{4}-\d{4,6})\.htm", url)
    if not match:
        raise ValueError("Expected an exact official Federal Register document URL")
    return calendar_date(match[1]), match[2]


def parse_govinfo_document(body, source_url):
    """Validate one complete official document; retain only its hash, URL and issue date."""
    date, document = govinfo_document_url(source_url)

    def email(encoded):
        # Cloudflare's first byte is an XOR key; preserve the complete decoded
        # address, never its changing nonce. The value is hashed, not published.
        if not re.fullmatch(r"[0-9a-fA-F]{4,642}", encoded or "") or len(encoded) % 2:
            raise ValueError("Unsupported protected email encoding")
        raw = bytes.fromhex(encoded)
        value = bytes(byte ^ raw[0] for byte in raw[1:]).decode("utf-8")
        if not re.fullmatch(r"[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+", value):
            raise ValueError("Invalid protected email address")
        return value

    class Document(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.opened = self.closed = self.html_closed = 0
            self.in_pre = False
            self.parts = []
            self.links = []
            self.protected_email = None
            self.protected_placeholder = []

        def handle_starttag(self, tag, attrs):
            if tag == "pre":
                self.opened += 1
                if self.opened != 1 or self.in_pre:
                    raise ValueError("Expected one complete document body")
                self.in_pre = True
            elif self.in_pre:
                if tag not in ("a", "span", "bullet", "br") or self.protected_email is not None:
                    raise ValueError("Unsupported document body markup")
                fields = dict(attrs)
                if len(fields) != len(attrs):
                    raise ValueError("Duplicate document attributes")
                if tag == "a" and "href" in fields:
                    target = fields["href"]
                    if not isinstance(target, str):
                        raise ValueError("Invalid document link")
                    prefix = "/cdn-cgi/l/email-protection#"
                    if target.startswith(prefix):
                        target = "mailto:" + email(target[len(prefix):])
                    elif target.startswith("/cdn-cgi/l/email-protection"):
                        raise ValueError("Unsupported protected email link")
                    self.links.append(target)
                if "data-cfemail" in fields:
                    if tag != "span" or fields.get("class") != "__cf_email__":
                        raise ValueError("Unsupported protected email element")
                    self.protected_email = email(fields["data-cfemail"])
                    self.protected_placeholder = []
                if tag == "br":
                    self.parts.append("\n")

        def handle_endtag(self, tag):
            if tag == "span" and self.protected_email is not None:
                if "".join(self.protected_placeholder).replace("\u00a0", " ") != "[email protected]":
                    raise ValueError("Unexpected protected email contents")
                self.parts.append(self.protected_email)
                self.protected_email = None
            elif tag == "pre":
                if not self.in_pre:
                    raise ValueError("Unexpected document end")
                self.closed += 1
                self.in_pre = False
            elif tag == "html":
                self.html_closed += 1

        def handle_data(self, data):
            if self.in_pre:
                (self.protected_placeholder if self.protected_email is not None else self.parts).append(data)

    if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise ValueError("Document declarations are unsupported")
    reader = Document()
    reader.feed(body.decode("utf-8"))
    reader.close()
    if reader.opened != 1 or reader.closed != 1 or reader.in_pre or reader.html_closed != 1 or reader.protected_email is not None:
        raise ValueError("Incomplete Federal Register document")
    complete_text = "".join(reader.parts)
    text = complete_text.strip()
    header = re.match(r"\[Federal Register Volume \d+, Number \d+ \(([A-Za-z]+, [A-Za-z]+ \d{1,2}, \d{4})\)\]\n", text)
    if not header:
        raise ValueError("Federal Register issue date is missing")
    parsed = datetime.strptime(header[1], "%A, %B %d, %Y")
    if parsed.date().isoformat() != date or parsed.strftime("%A") != header[1].split(",")[0]:
        raise ValueError("Document publication date conflicts with its URL or weekday")
    if text.count("[FR Doc No: " + document + "]") != 1 or not re.search(r"\[FR Doc\. " + re.escape(document) + r" Filed [^\]\n]+\]\s*BILLING CODE [A-Z0-9-]+\s*$", text):
        raise ValueError("Document number or complete filing footer is missing")
    # Hash the entire decoded document, including whitespace and every link in
    # source order. Only publisher chrome and email-obfuscation nonces are not
    # content. The complete raw response remains separately bound by sourceHash.
    content = {"binding": DOCUMENT_REVIEW_BINDING, "text": complete_text, "links": reader.links}
    return [{"itemHash": digest(content), "url": source_url, "publishedAt": date}]


def parse_feed(body, parser, date_only=False, source_url=None):
    """Parse a complete body. Return hashes/links/dates; do not persist unreviewed prose."""
    if parser == "govinfo-fr-html":
        return parse_govinfo_document(body, source_url)
    if parser == "json-feed":
        feed = json.loads(body.decode("utf-8"))
        if not isinstance(feed, dict) or not isinstance(feed.get("items"), list):
            raise ValueError("JSON feed must contain an items array")
        items = []
        for entry in feed["items"]:
            published = stamp(instant(entry["date_published"]))
            public_url(entry["url"])
            if not isinstance(entry.get("title"), str) or not entry["title"].strip():
                raise ValueError("Every feed item requires a title")
            items.append({"itemHash": digest(entry), "url": entry["url"], "publishedAt": published})
    elif parser == "rss-atom":
        if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
            raise ValueError("Document type/entity declarations are forbidden")
        root = ET.fromstring(body)
        ns = "{http://www.w3.org/2005/Atom}"
        if root.tag == "rss":
            if root.find("channel") is None:
                raise ValueError("RSS channel is required")
            entries = root.findall("channel/item")
        elif root.tag == ns + "feed":
            entries = root.findall(ns + "entry")
        else:
            raise ValueError("Unsupported feed document")
        items = []
        for entry in entries:
            if root.tag == "rss":
                title, url, date = (entry.findtext(key) for key in ("title", "link", "pubDate"))
                if date_only and re.fullmatch(r"[A-Z][a-z]{2}, \d{2} [A-Z][a-z]{2} \d{4}", date or ""):
                    parsed = datetime.strptime(date, "%a, %d %b %Y")
                    if parsed.strftime("%a, %d %b %Y") != date:
                        raise ValueError("Publication weekday conflicts with its date")
                    published = parsed.date().isoformat()
                else:
                    parsed = parsedate_to_datetime(date)
                    if parsed.tzinfo is None:
                        raise ValueError("Publication date timezone is required")
                    published = stamp(parsed)
            else:
                title = entry.findtext(ns + "title")
                link = next((link for link in entry.findall(ns + "link") if link.get("rel", "alternate") == "alternate"), None)
                url = link.get("href") if link is not None else None
                published = stamp(instant(entry.findtext(ns + "published")))
            if not title or not url:
                raise ValueError("Every feed entry requires title and public link")
            public_url(url)
            items.append({"itemHash": digest(ET.tostring(entry, encoding="utf-8")), "url": url, "publishedAt": published})
    else:
        raise ValueError("Unsupported parser")
    # Duplicate content is one candidate; conflicting revisions remain separate hashes.
    if len(items) > 500:
        raise ValueError("Feed exceeds the 500-item admission limit")
    return list({item["itemHash"]: item for item in items}.values())


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Redirect requires a new explicitly admitted source URL")


def fetch_source(source, previous, policy):
    public_url(source["url"], policy["allowedHosts"])
    headers = {"User-Agent": "EmbassyManagerEducationalCollector/0.1", "Accept": "application/feed+json, application/json, application/atom+xml, application/rss+xml", "Accept-Encoding": "identity"}
    if previous.get("lastValidHash") and previous.get("etag"):
        headers["If-None-Match"] = previous["etag"]
    request = urllib.request.Request(source["url"], headers=headers, method="GET")
    opener = urllib.request.build_opener(NoRedirects())
    try:
        response = opener.open(request, timeout=policy["timeoutSeconds"])
    except urllib.error.HTTPError as error:
        if error.code == 304:
            return 304, b"", {}
        raise ValueError("Source returned HTTP " + str(error.code)) from None
    with response:
        if response.status != 200 or response.headers.get("Content-Encoding", "identity") != "identity":
            raise ValueError("Unsupported response status or compression")
        limit = policy["maxResponseBytes"]
        size = response.headers.get("Content-Length")
        if size is not None and int(size) > limit:
            raise ValueError("Response exceeds policy; no partial body is parsed")
        body = response.read(limit + 1)
        if len(body) > limit or (size is not None and len(body) != int(size)):
            raise ValueError("Incomplete or oversized response; no partial body is parsed")
        return 200, body, {"etag": response.headers.get("ETag", "")}


def due_date(post, now, last_date):
    local = now.astimezone(ZoneInfo(post["timezone"]))
    date = local.date().isoformat()
    return date if local.hour >= 6 and (not last_date or date > last_date) else None


def immutable_json(path, value):
    raw = json.dumps(value, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text() != raw:
            raise ValueError("Immutable snapshot collision")
    else:
        path.write_text(raw)


def run_tick(policy, state, now, output, fetch=fetch_source):
    validate_policy(policy)
    if not policy["enabled"]:
        return state
    state = json.loads(json.dumps(state))
    state.setdefault("schemaVersion", 1)
    sources_state, editions = state.setdefault("sources", {}), state.setdefault("editions", {})
    if "publication" in policy:
        current_ids = {event["id"] for event in policy["reviewedEvents"]}
        retained_ids = {event["id"] for edition in editions.values() for event in edition["events"]}
        if not retained_ids.issubset(current_ids):
            raise ValueError("Previously published events require an explicit reviewed correction; deleting a review is not a retraction")
    accepted = state.setdefault("acceptedReviews", {})
    review_digest = digest(policy["reviewedEvents"])
    editorial_change = state.get("reviewDigest") != review_digest
    due = [(post, due_date(post, now, editions.get(post["id"], {}).get("date"))) for post in policy["posts"]]
    if editorial_change:
        due = [(post, date or due_date(post, now, None)) for post, date in due]
    due = [(post, date) for post, date in due if date]
    wanted = {sid for post, _ in due for sid in post["sourceIds"]}
    wanted.update(source["id"] for source in policy["sources"] if source.get("metadataOnly"))
    attempts = 0
    for source in policy["sources"]:
        if source["id"] not in wanted:
            continue
        previous = sources_state.get(source["id"], {})
        if previous.get("checkedAt") and now - instant(previous["checkedAt"]) < timedelta(minutes=source["pollMinutes"]):
            continue
        if attempts >= policy["maxSourcesPerRun"]:
            continue
        attempts += 1
        current = {**previous, "checkedAt": stamp(now)}
        try:
            status, body, headers = fetch(source, previous, policy)
            if status == 304:
                if not previous.get("lastValidHash") or "items" not in previous:
                    raise ValueError("304 response without a prior successfully parsed source")
                current.update(status="unchanged", verifiedAt=stamp(now))
            elif status == 200:
                if len(body) > policy["maxResponseBytes"]:
                    raise ValueError("Oversized response")
                items = parse_feed(body, source["parser"], source.get("dateOnlyPublication", False), source["url"])
                if any(publication_after(item["publishedAt"], now) for item in items):
                    raise ValueError("Future publication date needs source-specific review")
                source_hash = digest(body)
                prior_by_url = {item["url"]: item for item in previous.get("items", [])}
                current_urls = {item["url"] for item in items}
                changes = [{**item, "change": "changed" if item["url"] in prior_by_url else "new"} for item in items if prior_by_url.get(item["url"], {}).get("itemHash") != item["itemHash"]]
                changes += [{**item, "change": "removed"} for item in previous.get("items", []) if item["url"] not in current_urls]
                current.update(status="unchanged" if previous.get("lastValidHash") == source_hash else "awaiting-review", lastValidHash=source_hash, items=items, verifiedAt=stamp(now), etag=headers.get("etag", ""))
                if previous.get("lastValidHash") != source_hash:
                    current["changes"] = changes
                immutable_json(output / "sources" / source["id"] / (source_hash + ".json"), {"sourceId": source["id"], "sourceHash": source_hash, "items": items})
            else:
                raise ValueError("Unexpected response")
            current.pop("error", None)
        except (ValueError, KeyError, TypeError, AttributeError, UnicodeError, ET.ParseError, OSError, HTTPException, urllib.error.URLError) as error:
            # Only class names enter public state; server error text can expose request details.
            current.update(status="failed", error=type(error).__name__)
        sources_state[source["id"]] = current
    # Feed approvals initially bind both exact hashes. The explicit document
    # binding instead matches the entire reviewed article text and link targets.
    # Later unrelated feed changes retain approval only for the identical item.
    def matches(event, source):
        item = next((item for item in source.get("items", []) if item["itemHash"] == event["itemHash"]), None)
        exact = event["sourceHash"] == source.get("lastValidHash")
        approved_before = accepted.get(event["id"]) == digest(event)
        complete_document = event.get("reviewBinding") == DOCUMENT_REVIEW_BINDING
        matched = item and (exact or approved_before or complete_document) and event["sourceUrl"] == item["url"] and publication(event["publishedAt"]) == item["publishedAt"] and instant(event["reviewedAt"]) <= now
        if matched and (exact or complete_document) and source.get("status") != "failed":
            accepted[event["id"]] = digest(event)
        return bool(matched)
    for post, date in due:
        previous = editions.get(post["id"], {})
        approved, warnings = [], []
        for sid in post["sourceIds"]:
            source = sources_state.get(sid, {})
            stale = not source.get("verifiedAt") or now - instant(source["verifiedAt"]) > timedelta(hours=policy["staleAfterHours"])
            candidates = [event for event in policy["reviewedEvents"] if event["sourceId"] == sid and post["id"] in event["postIds"]]
            matched = [event for event in candidates if matches(event, source)]
            unmatched = len(matched) != len(candidates)
            if source.get("status") == "failed" or stale or not matched or unmatched:
                warning = "stale" if stale else ("failed" if source.get("status") == "failed" else "awaiting-review")
                warnings.append({"sourceId": sid, "status": warning, "lastVerifiedAt": source.get("verifiedAt")})
            # A failed refresh retains the last edition; a new unreviewed hash cannot promote prose.
            if source.get("status") != "failed" and not stale:
                approved.extend(matched)
        if not approved:
            # Do not claim a fresh edition merely because the collector ran.
            if previous:
                last_check = max((sources_state.get(sid, {}).get("checkedAt", "") for sid in post["sourceIds"]), default="")
                if warnings != previous.get("warnings") or last_check > previous.get("lastAttemptAt", previous["generatedAt"]) or editorial_change:
                    editions[post["id"]] = {**previous, "warnings": warnings, "lastAttemptAt": stamp(now)}
            continue
        inherited = {event["id"]: event for event in previous.get("events", [])}
        inherited.update({event["id"]: event for event in approved})
        edition = {"schemaVersion": 1, "postId": post["id"], "date": date, "generatedAt": stamp(now), "events": list(inherited.values()), "warnings": warnings}
        version = digest(edition)
        immutable_json(output / "editions" / post["id"] / (version + ".json"), edition)
        editions[post["id"]] = {**edition, "snapshotHash": version}
    queue = []
    for sid, source in sources_state.items():
        reviewed_hashes = {event["itemHash"] for event in policy["reviewedEvents"] if event["sourceId"] == sid and matches(event, source)}
        changes = {item["itemHash"]: item["change"] for item in source.get("changes", [])}
        for item in source.get("items", []):
            if item["itemHash"] not in reviewed_hashes:
                queue.append({"sourceId": sid, "sourceHash": source["lastValidHash"], **item, "change": changes.get(item["itemHash"], "unreviewed")})
        for item in source.get("changes", []):
            if item["change"] == "removed":
                queue.append({"sourceId": sid, "sourceHash": source["lastValidHash"], **item})
    state["reviewQueue"] = queue
    state["reviewDigest"] = review_digest
    return state


def write_json(path, value):
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_bytes() != raw:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(raw)
        temporary.replace(path)
    return raw


def publication_envelope(policy, state, post):
    previous = state.get("editions", {}).get(post["id"])
    if not previous:
        return None
    events, sources, corrections = [], [], []
    for reviewed in previous["events"]:
        # Retained editions carry their original review, never a new policy's unapproved prose.
        validation = {**policy, "reviewedEvents": [reviewed]}
        validate_publication_policy(validation)
        # A corrected source URL is a new evidence record. Existing visitor work
        # can keep the old source reference while the public event identity stays stable.
        sid = "collector-" + digest({"eventId": reviewed["id"], "sourceUrl": reviewed["sourceUrl"]})[:32]
        source = {"id": sid, "title": reviewed["sourceTitle"], "url": reviewed["sourceUrl"], "publisher": reviewed["publisher"], "publishedAt": publication(reviewed["publishedAt"])[:10], "verifiedAt": instant(reviewed["reviewedAt"]).date().isoformat(), "supports": reviewed["supports"]}
        sources.append(source)
        if "correction" in reviewed:
            corrections.append({"eventId": reviewed["id"], "kind": reviewed["correction"]["kind"], "summary": reviewed["correction"]["summary"], "reviewedAt": stamp(instant(reviewed["reviewedAt"])), "sourceIds": [sid]})
        if reviewed["status"] not in PUBLIC_STATUSES:
            continue
        events.append({"id": reviewed["id"], "title": reviewed["title"], "summary": reviewed["summary"], "occurredAt": publication(reviewed["occurredAt"])[:10], "publishedAt": source["publishedAt"], "status": reviewed["status"], "country": post["country"], "location": post["country"], "precision": reviewed.get("precision", "country"), "roleIds": [role for role in reviewed["roleIds"] if role in post["roleIds"]], "sourceIds": [sid], "topic": reviewed["topic"]})
    published = max(instant(event["reviewedAt"]).date().isoformat() for event in previous["events"])
    content = {"events": events, "sources": sources, "corrections": corrections}
    edition = {"schemaVersion": 1, "id": "collector-" + digest(content)[:24], "postId": post["id"], "mode": "reviewed-public", "publishedAt": published, "events": events, "suggestions": []}
    verified = [state.get("sources", {}).get(sid, {}).get("verifiedAt") for sid in post["sourceIds"]]
    warnings = previous.get("warnings", [])
    return {"schemaVersion": 1, "postId": post["id"], "generatedAt": previous["generatedAt"], "edition": edition, "sources": sources, "corrections": corrections, "collection": {"sourceCheckedAt": min(verified) if all(verified) else None, "sourceWarnings": warnings, "reviewState": "retained-last-valid" if warnings else "reviewed"}}


def export_publication(policy, state, destination):
    """Offline bridge: emit only reviewed prose and bounded public metadata."""
    validate_policy(policy)
    if "publication" not in policy:
        raise ValueError("Explicit publication policy is required")
    manifest_path = destination / "manifest.json"
    entries, current_paths, published_times = [], set(), []
    pending = {}
    for post in policy["posts"]:
        envelope = publication_envelope(policy, state, post)
        if envelope is None:
            continue
        raw = (json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
        if len(raw) > 500_000:
            raise ValueError("Published post envelope exceeds 500000 bytes")
        sha = digest(raw)
        relative = f"editions/{post['id']}/{sha}.json"
        target = destination / relative
        if target.exists() and target.read_bytes() != raw:
            raise ValueError("Immutable publication collision")
        pending[target] = envelope
        current_paths.add(relative)
        entries.append({"postId": post["id"], "path": relative, "sha256": sha, "bytes": len(raw)})
        published_times.append(envelope["generatedAt"])
    manifest = {"schemaVersion": 1, "generatedAt": max(published_times) if published_times else None, "posts": entries}
    pending[manifest_path] = manifest
    pending[destination / "review-queue.json"] = {"schemaVersion": 1, "items": state.get("reviewQueue", [])}
    if sum(len(json.dumps(value, ensure_ascii=False).encode()) for value in pending.values()) > policy["publication"]["maxPayloadBytes"]:
        raise ValueError("Publication payload limit reached; maintenance required")
    for path, value in pending.items():
        write_json(path, value)
    # Current plus two older content-addressed editions. Never delete the current path.
    for directory in (destination / "editions").glob("*") if (destination / "editions").exists() else []:
        if not directory.is_dir():
            raise ValueError("Unexpected publication path")
        files = sorted(directory.glob("*.json"), key=lambda path: path.stat().st_mtime_ns, reverse=True)
        current = [path for path in files if path.relative_to(destination).as_posix() in current_paths]
        keep = set(current + [path for path in files if path not in current][:max(0, policy["publication"]["editionVersions"] - len(current))])
        for path in files:
            if path not in keep:
                path.unlink()
    payload = sum(path.stat().st_size for path in destination.rglob("*") if path.is_file())
    if payload > policy["publication"]["maxPayloadBytes"]:
        raise ValueError("Publication payload limit reached; maintenance required")
    return manifest


def prune_snapshots(policy, output):
    config = policy.get("publication", {"sourceVersions": 2, "editionVersions": 3})
    for category, key in (("sources", "sourceVersions"), ("editions", "editionVersions")):
        for directory in (output / category).glob("*") if (output / category).exists() else []:
            files = sorted(directory.glob("*.json"), key=lambda path: path.stat().st_mtime_ns, reverse=True)
            for path in files[config[key]:]:
                path.unlink()


def inspect_feed(policy, path, source_id, item_url):
    """Review one complete entry from a completely parsed local feed; never fetch or approve."""
    source = next((source for source in policy["sources"] if source["id"] == source_id), None)
    if source is None:
        raise ValueError("Unknown source identifier")
    body = path.read_bytes()
    if len(body) > policy["maxResponseBytes"]:
        raise ValueError("Complete feed exceeds the admitted size limit")
    items = parse_feed(body, source["parser"], source.get("dateOnlyPublication", False), source["url"])
    found = [item for item in items if item["url"] == item_url]
    if len(found) != 1:
        raise ValueError("Select an unambiguous complete source item")
    item = found[0]
    if source["parser"] == "govinfo-fr-html":
        entry = body.decode("utf-8")
    elif source["parser"] == "json-feed":
        entry = next(entry for entry in json.loads(body)["items"] if digest(entry) == item["itemHash"])
    else:
        root = ET.fromstring(body)
        entries = root.findall("channel/item") if root.tag == "rss" else root.findall("{http://www.w3.org/2005/Atom}entry")
        entry = ET.tostring(next(entry for entry in entries if digest(ET.tostring(entry, encoding="utf-8")) == item["itemHash"]), encoding="unicode")
    return {"sourceId": source_id, "sourceHash": digest(body), "responseBytes": len(body), **item, "completeEntry": entry}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=Path("data/collection-policy.json"))
    parser.add_argument("--output", type=Path, default=Path("collector-state"))
    parser.add_argument("--collect", action="store_true", help="Allow admitted public GETs only when the policy is enabled")
    parser.add_argument("--export", type=Path, help="Export reviewed public JSON for the static client; never deploy")
    parser.add_argument("--replay", type=Path, help="Read complete <source-id>.feed fixture files instead of network requests")
    parser.add_argument("--now", help="Explicit timestamp for offline replay only")
    parser.add_argument("--inspect-feed", type=Path, help="Print a complete local feed entry and its review hashes, without network or approval")
    parser.add_argument("--source-id")
    parser.add_argument("--item-url")
    args = parser.parse_args()
    policy = json.loads(args.policy.read_text())
    validate_policy(policy)
    if args.inspect_feed:
        if args.collect or args.replay or args.export or args.now or not args.source_id or not args.item_url:
            parser.error("Feed inspection requires only --source-id, --item-url, and a complete local feed")
        print(json.dumps(inspect_feed(policy, args.inspect_feed, args.source_id, args.item_url), indent=2, ensure_ascii=False))
        return
    if args.source_id or args.item_url:
        parser.error("Source and item selection are restricted to feed inspection")
    if args.now and not args.replay:
        parser.error("--now is restricted to offline replay")
    if args.collect and args.replay:
        parser.error("Network collection and offline replay are mutually exclusive")
    if not args.replay and (not args.collect or not policy["enabled"]):
        print("Collector inactive; policy validated; no network requests or output files.")
        return
    state_path = args.output / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    now = instant(args.now) if args.now else datetime.now(UTC)
    if args.replay:
        fetch = lambda source, *_: (200, (args.replay / (source["id"] + ".feed")).read_bytes(), {})
    else:
        fetch = fetch_source
    next_state = run_tick({**policy, "enabled": True}, state, now, args.output, fetch)
    args.output.mkdir(parents=True, exist_ok=True)
    write_json(state_path, next_state)
    prune_snapshots(policy, args.output)
    if args.export:
        export_publication(policy, next_state, args.export)
    print("Collection completed; only reviewed source-hash-matched text is eligible for editions.")


if __name__ == "__main__":
    main()
