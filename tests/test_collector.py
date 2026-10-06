import copy
from datetime import datetime, timezone, timedelta
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("collector", ROOT / "scripts/collector.py")
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)
UTC = timezone.utc
NOW = datetime(2026, 10, 5, 6, 0, tzinfo=UTC)


def feed(title="A dated public announcement", published="2026-10-04T12:00:00Z"):
    return json.dumps({"items": [{"id": "notice-1", "url": "https://example.gov/notice", "title": title, "date_published": published, "content_text": "Complete fixture body."}]}).encode()


def policy(body=None):
    body = body or feed()
    item = collector.parse_feed(body, "json-feed")[0]
    return {
        "schemaVersion": 1, "enabled": True, "allowedHosts": ["example.gov"],
        "maxSourcesPerRun": 12, "maxResponseBytes": 524288, "timeoutSeconds": 10, "staleAfterHours": 48,
        "sources": [{"id": "official", "url": "https://example.gov/feed", "nonBillable": True, "parser": "json-feed", "pollMinutes": 360}],
        "posts": [{"id": "example-post", "timezone": "UTC", "sourceIds": ["official"]}],
        "reviewedEvents": [{"id": "notice-1", "sourceId": "official", "sourceHash": collector.digest(body), "itemHash": item["itemHash"], "sourceUrl": item["url"], "title": "Reviewed public notice", "summary": "Illustrative fixture only.", "publishedAt": item["publishedAt"], "occurredAt": "2026-10-02T10:00:00Z", "reviewedAt": "2026-10-04T20:00:00Z", "reviewedByRole": "editor", "status": "announced", "postIds": ["example-post"], "roleIds": ["consular"]}],
    }


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.output = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def run_tick(self, data=None, state=None, now=NOW, body=None, status=200):
        return collector.run_tick(data or policy(), state or {}, now, self.output, lambda *_: (status, body or feed(), {"etag": '"fixture"'}))

    def test_disabled_policy_is_inactive_even_with_reviewed_admissions(self):
        data = json.loads((ROOT / "data/collection-policy.json").read_text())
        data["enabled"] = False
        collector.validate_policy(data)
        state = collector.run_tick(data, {}, NOW, self.output, lambda *_: self.fail("No network expected"))
        self.assertEqual(state, {})
        self.assertEqual(list(self.output.iterdir()), [])

    def test_published_occurred_and_generated_dates_stay_distinct(self):
        edition = self.run_tick()["editions"]["example-post"]
        event = edition["events"][0]
        self.assertEqual(event["publishedAt"], "2026-10-04T12:00:00Z")
        self.assertEqual(event["occurredAt"], "2026-10-02T10:00:00Z")
        self.assertEqual(edition["generatedAt"], "2026-10-05T06:00:00Z")

    def test_unreviewed_source_cannot_publish(self):
        data = policy()
        data["reviewedEvents"] = []
        result = self.run_tick(data=data)
        self.assertEqual(result["editions"], {})
        snapshot = next((self.output / "sources").rglob("*.json")).read_text()
        self.assertNotIn("A dated public announcement", snapshot)
        self.assertNotIn("Complete fixture body", snapshot)

    def test_source_or_item_change_requires_new_review(self):
        state = self.run_tick()
        changed = feed("Correction: updated notice")
        result = self.run_tick(state=state, now=NOW + timedelta(days=1), body=changed)
        self.assertEqual(result["editions"]["example-post"]["snapshotHash"], state["editions"]["example-post"]["snapshotHash"])
        self.assertEqual(result["editions"]["example-post"]["warnings"][0]["status"], "awaiting-review")

    def test_reviewed_retraction_replaces_same_event_and_preserves_old_snapshot(self):
        state = self.run_tick()
        changed = feed("Notice withdrawn")
        data = policy(changed)
        data["reviewedEvents"][0]["status"] = "retracted"
        result = self.run_tick(data=data, state=state, now=NOW + timedelta(days=1), body=changed)
        self.assertEqual(result["editions"]["example-post"]["events"][0]["status"], "retracted")
        self.assertEqual(len(list((self.output / "editions").rglob("*.json"))), 2)

    def test_parser_failure_preserves_last_good(self):
        state = self.run_tick()
        result = self.run_tick(state=state, now=NOW + timedelta(days=1), body=b'{"items": [')
        self.assertEqual(result["sources"]["official"]["status"], "failed")
        self.assertEqual(result["sources"]["official"]["lastValidHash"], state["sources"]["official"]["lastValidHash"])
        self.assertEqual(result["editions"]["example-post"]["date"], "2026-10-05")

    def test_304_requires_prior_valid_parse(self):
        empty = self.run_tick(status=304)
        self.assertEqual(empty["sources"]["official"]["status"], "failed")
        state = self.run_tick()
        result = self.run_tick(state=state, now=NOW + timedelta(days=1), status=304)
        self.assertEqual(result["sources"]["official"]["status"], "unchanged")
        self.assertEqual(result["editions"]["example-post"]["date"], "2026-10-06")

    def test_stale_failed_source_cannot_claim_fresh_edition(self):
        state = self.run_tick()
        result = self.run_tick(state=state, now=NOW + timedelta(days=3), body=b"invalid")
        edition = result["editions"]["example-post"]
        self.assertEqual(edition["date"], "2026-10-05")
        self.assertEqual(edition["warnings"][0]["status"], "stale")

    def test_shared_source_fetched_once(self):
        data = policy()
        data["posts"].append({"id": "second-post", "timezone": "UTC", "sourceIds": ["official"]})
        data["reviewedEvents"][0]["postIds"].append("second-post")
        calls = []
        result = collector.run_tick(data, {}, NOW, self.output, lambda *args: (calls.append(args) or (200, feed(), {})))
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(result["editions"]), 2)

    def test_repeated_tick_does_not_refetch_or_create_duplicate_edition(self):
        state = self.run_tick()
        result = collector.run_tick(policy(), state, NOW + timedelta(minutes=15), self.output, lambda *_: self.fail("Repeated fetch"))
        self.assertEqual(result, state)

    def test_delayed_tick_catches_up_without_duplicate_editions(self):
        data = policy()
        late = NOW + timedelta(hours=5)
        state = self.run_tick(data=data, now=late)
        self.assertEqual(state["editions"]["example-post"]["date"], "2026-10-05")
        self.assertEqual(collector.due_date(data["posts"][0], late, "2026-10-05"), None)

    def test_six_am_uses_local_time_and_daylight_saving(self):
        post = {"timezone": "America/New_York"}
        self.assertIsNone(collector.due_date(post, collector.instant("2026-03-08T09:59:00Z"), None))
        self.assertEqual(collector.due_date(post, collector.instant("2026-03-08T10:00:00Z"), None), "2026-03-08")
        self.assertIsNone(collector.due_date(post, collector.instant("2026-11-01T10:59:00Z"), None))
        self.assertEqual(collector.due_date(post, collector.instant("2026-11-01T11:00:00Z"), None), "2026-11-01")
        self.assertEqual(collector.due_date({"timezone": "Asia/Kolkata"}, collector.instant("2026-10-05T00:30:00Z"), None), "2026-10-05")

    def test_publication_date_and_url_must_match_reviewed_candidate(self):
        for key, wrong in (("publishedAt", "2026-10-03T12:00:00Z"), ("sourceUrl", "https://example.gov/different")):
            with self.subTest(key=key):
                data = policy()
                data["reviewedEvents"][0][key] = wrong
                self.assertEqual(self.run_tick(data=data)["editions"], {})

    def test_future_publication_and_oversized_response_fail_closed(self):
        for body in (feed(published="2027-01-01T00:00:00Z"), b" " * 524289):
            with self.subTest(size=len(body)):
                result = self.run_tick(body=body)
                self.assertEqual(result["editions"], {})
                self.assertEqual(result["sources"]["official"]["status"], "failed")

    def test_duplicate_items_deduplicate(self):
        entry = json.loads(feed())["items"][0]
        self.assertEqual(len(collector.parse_feed(json.dumps({"items": [entry, entry]}).encode(), "json-feed")), 1)

    def test_feed_parser_rejects_missing_date_and_entities(self):
        with self.assertRaises((ValueError, KeyError)):
            collector.parse_feed(b'{"items":[{"title":"No date","url":"https://example.gov/a"}]}', "json-feed")
        with self.assertRaises(ValueError):
            collector.parse_feed(b'<!DOCTYPE rss [<!ENTITY x "invalid">]><rss><channel/></rss>', "rss-atom")

    def test_rss_and_atom_parse_complete_dated_items(self):
        rss = b'<rss><channel><item><title>Notice</title><link>https://example.gov/a</link><pubDate>Sun, 04 Oct 2026 12:00:00 GMT</pubDate></item></channel></rss>'
        atom = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Notice</title><link href="https://example.gov/a"/><published>2026-10-04T12:00:00Z</published></entry></feed>'
        for body in (rss, atom):
            self.assertEqual(collector.parse_feed(body, "rss-atom")[0]["publishedAt"], "2026-10-04T12:00:00Z")

    def test_policy_rejects_expense_or_unbounded_config(self):
        for mutate in (lambda p: p["sources"][0].update(nonBillable=False), lambda p: p.update(maxSourcesPerRun=13), lambda p: p["sources"][0].update(url="https://not-admitted.test/feed"), lambda p: p["sources"][0].update(pollMinutes=1)):
            data = policy()
            mutate(data)
            with self.assertRaises(ValueError):
                collector.validate_policy(data)


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        for directory in ("scripts", "data", "dist/embassy-manager/assets"):
            (self.path / directory).mkdir(parents=True)
        for file in ("scripts/preflight.mjs", "wrangler.static.jsonc", "data/collection-policy.json"):
            shutil.copyfile(ROOT / file, self.path / file)
        (self.path / "dist/embassy-manager/index.html").write_text('<!doctype html><html><head><link rel="stylesheet" href="/embassy-manager/assets/app.css"></head><body><script src="/embassy-manager/assets/app.js"></script></body></html>')
        (self.path / "dist/embassy-manager/assets/app.js").write_text('document.title = "Embassy Manager";')
        (self.path / "dist/embassy-manager/assets/app.css").write_text('body { color: navy; }')
        (self.path / "dist/_headers").write_text("/embassy-manager/*\n  Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self' https://raw.githubusercontent.com/brand-on-fire/embassy-manager-data/public-data/ https://embassy-public-ranking.wild-snowflake-1dd9.workers.dev/v2/desk/; font-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'\n  Referrer-Policy: no-referrer\n")

    def check(self, mode="--preview"):
        return subprocess.run(["node", str(self.path / "scripts/preflight.mjs"), mode], capture_output=True, text=True, check=False)

    def test_static_preview_passes_but_release_stays_blocked(self):
        self.assertEqual(self.check().returncode, 0)
        result = self.check("--release")
        self.assertEqual(result.returncode, 1)
        self.assertIn("data/release-readiness.json is absent", result.stderr)

    def test_billable_binding_is_rejected(self):
        path = self.path / "wrangler.static.jsonc"
        config = json.loads(path.read_text())
        config["kv_namespaces"] = []
        path.write_text(json.dumps(config))
        self.assertEqual(self.check().returncode, 1)

    def test_remote_resource_and_secret_artifact_rejected(self):
        (self.path / "dist/embassy-manager/index.html").write_text('<script src="https://remote.test/analytics.js"></script>')
        (self.path / "dist/.env").write_text("NON_SECRET_FIXTURE=1")
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("Resource must be bundled locally", result.stderr)
        self.assertIn("Private/server path", result.stderr)

    def test_active_workflow_rejected_before_any_runner_can_be_used(self):
        directory = self.path / ".github/workflows"
        directory.mkdir(parents=True)
        (directory / "bad.yml").write_text("name: forbidden")
        self.assertIn("Live workflows are not admitted", self.check().stderr)

    def test_network_writes_rejected(self):
        (self.path / "dist/embassy-manager/assets/app.js").write_text('fetch("/submit", {method: "POST"});')
        self.assertIn("Network write method", self.check().stderr)

    def test_csp_cannot_add_remote_resource_or_reporting_overrides(self):
        path = self.path / "dist/_headers"
        original = path.read_text()
        for header in (original.replace("img-src 'self' data:", "img-src *"), original.replace("style-src 'self'", "style-src 'self' 'unsafe-inline'"), original.replace("frame-ancestors 'none'", "frame-ancestors 'none'; report-uri https://remote.test/collect"), original.replace("frame-ancestors 'none'", "frame-ancestors 'none'; script-src-elem https://remote.test"), original.replace("script-src 'self'", "script-src *; script-src 'self'")):
            path.write_text(header)
            self.assertEqual(self.check().returncode, 1)

    def test_release_booleans_do_not_replace_audit_evidence(self):
        readiness = {"schemaVersion": 1, "selectedTheme": "light", "selectedThemeByUser": True, "reviewedBy": "editor", "reviewedAt": "2026-10-05T00:00:00Z", "qualifiedPostIds": ["example"], "worldwideAudit": {"complete": True, "directoryUrl": "https://www.usembassy.gov/", "auditedAt": "2026-10-05T00:00:00Z", "unresolvedClaims": 0, "coveredPostIds": ["example"], "evidencePath": "docs/audit.json"}, "checks": {key: True for key in ("privacy", "billing", "chromeDesktop", "chromeMobile", "publication")}}
        (self.path / "data/release-readiness.json").write_text(json.dumps(readiness))
        self.assertIn("existing local JSON evidence ledger", self.check("--release").stderr)

    def test_template_has_public_runner_guard_and_no_billing_features(self):
        workflow = (ROOT / "collector-template/collect.yml.disabled").read_text()
        self.assertIn("if: github.event.repository.private == false", workflow)
        self.assertIn("runs-on: ubuntu-24.04", workflow)
        for forbidden in ("upload-artifact", "actions/cache", "CLOUDFLARE_API_TOKEN", "self-hosted", "ubuntu-latest-xl"):
            self.assertNotIn(forbidden, workflow)


if __name__ == "__main__":
    unittest.main()
