import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("backlog_collector", ROOT / "scripts/collector.py")
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)
NOW = datetime(2026, 10, 6, 6, 7, tzinfo=timezone.utc)
BODY = json.dumps({"items": [{"title": "Synthetic announcement", "url": "https://example.gov/item", "date_published": "2026-10-05T12:00:00Z", "content_text": "Complete offline fixture."}]}).encode()


def policy():
    item = collector.parse_feed(BODY, "json-feed")[0]
    return {
        "schemaVersion": 1, "enabled": True, "allowedHosts": ["example.gov"],
        "maxSourcesPerRun": 2, "maxResponseBytes": 1048576, "timeoutSeconds": 10, "staleAfterHours": 48,
        "sources": [{"id": sid, "url": "https://example.gov/" + sid, "nonBillable": True, "parser": "json-feed", "pollMinutes": 360, "metadataOnly": sid == "discovery"} for sid in ("approved", "discovery", "later")],
        "posts": [{"id": "sample", "timezone": "UTC", "sourceIds": ["approved", "later"]}],
        "reviewedEvents": [{"id": "reviewed-fixture", "sourceId": "approved", "sourceHash": collector.digest(BODY), "itemHash": item["itemHash"], "sourceUrl": item["url"], "title": "Reviewed fixture", "summary": "Synthetic offline review.", "publishedAt": item["publishedAt"], "occurredAt": "2026-10-05", "reviewedAt": "2026-10-05T18:00:00Z", "reviewedByRole": "editor", "status": "announced", "postIds": ["sample"], "roleIds": ["consular"]}],
    }


class SourceBacklogTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name)
        self.calls = []

    def tick(self, data, state=None, now=NOW, failed=None, body=BODY):
        self.calls = []

        def fetch(source, *_):
            self.calls.append(source["id"])
            if source["id"] == failed:
                raise ValueError("Synthetic failure")
            return 200, body, {}

        return collector.run_tick(data, state or {}, now, self.output, fetch)

    def test_cap_keeps_post_due_until_later_source_is_checked(self):
        for metadata_only in (False, True):
            with self.subTest(metadata_only=metadata_only):
                data = policy()
                data["sources"][2]["metadataOnly"] = metadata_only
                first = self.tick(data)
                self.assertEqual(self.calls, ["approved", "discovery"])
                self.assertEqual(first["editions"], {})
                self.assertNotIn("later", first["sources"])
                second = self.tick(data, first, NOW + timedelta(minutes=15))
                self.assertEqual(self.calls, ["later"])
                self.assertEqual(second["editions"]["sample"]["date"], "2026-10-06")
                self.assertEqual(second["editions"]["sample"]["warnings"], [{"sourceId": "later", "status": "awaiting-review", "lastVerifiedAt": "2026-10-06T06:22:00Z"}])
                self.assertEqual([e["id"] for e in second["editions"]["sample"]["events"]], ["reviewed-fixture"])
                third = self.tick(data, second, NOW + timedelta(minutes=30))
                self.assertEqual(self.calls, [])
                self.assertEqual(third, second)

    def test_previous_edition_is_retained_until_attempt_then_failure_is_visible(self):
        data = policy()
        prior = self.tick({**data, "maxSourcesPerRun": 3})
        first = self.tick(data, prior, NOW + timedelta(days=1))
        self.assertEqual(self.calls, ["approved", "discovery"])
        self.assertEqual(first["editions"], prior["editions"])
        second = self.tick(data, first, NOW + timedelta(days=1, minutes=15), failed="later")
        self.assertEqual(self.calls, ["later"])
        self.assertEqual(second["editions"]["sample"]["date"], "2026-10-07")
        self.assertEqual(second["sources"]["later"]["lastValidHash"], prior["sources"]["later"]["lastValidHash"])
        self.assertEqual(second["editions"]["sample"]["warnings"][0]["status"], "failed")

    def test_same_day_editorial_change_survives_cap_and_state_roundtrip(self):
        data = policy()
        prior = copy.deepcopy(self.tick({**data, "maxSourcesPerRun": 3}))
        data["reviewedEvents"][0]["summary"] = "Revised reviewed fixture."
        first = self.tick(data, prior, NOW + timedelta(hours=6))
        self.assertEqual(first["editions"], prior["editions"])
        second = self.tick(data, json.loads(json.dumps(first)), NOW + timedelta(hours=6, minutes=15))
        self.assertEqual(self.calls, ["later"])
        self.assertEqual(second["editions"]["sample"]["events"][0]["summary"], "Revised reviewed fixture.")
        self.assertEqual(second["editions"]["sample"]["generatedAt"], "2026-10-06T12:22:00Z")

    def test_deferred_source_does_not_block_an_independent_post(self):
        data = policy()
        data["posts"].append({"id": "independent", "timezone": "UTC", "sourceIds": ["approved"]})
        data["reviewedEvents"][0]["postIds"].append("independent")
        first = self.tick(data)
        self.assertEqual(set(first["editions"]), {"independent"})
        second = self.tick(data, first, NOW + timedelta(minutes=15))
        self.assertEqual(self.calls, ["later"])
        self.assertEqual(second["editions"]["independent"], first["editions"]["independent"])
        self.assertEqual(set(second["editions"]), {"sample", "independent"})

    def test_twelve_wanted_sources_finish_in_six_bounded_ticks(self):
        data = policy()
        for index in range(3, 12):
            data["sources"].append({**data["sources"][2], "id": f"source-{index}", "url": f"https://example.gov/source-{index}"})
            data["posts"][0]["sourceIds"].append(f"source-{index}")
        state, all_calls = {}, []
        for tick in range(6):
            state = self.tick(data, state, NOW + timedelta(minutes=15 * tick))
            self.assertEqual(len(self.calls), 2)
            all_calls.extend(self.calls)
            if tick < 5:
                self.assertEqual(state["editions"], {})
        self.assertEqual(all_calls, [source["id"] for source in data["sources"]])
        self.assertEqual(state["editions"]["sample"]["date"], "2026-10-06")

    def test_cached_source_in_poll_cooldown_does_not_block_edition(self):
        data = policy()
        state = copy.deepcopy(self.tick({**data, "maxSourcesPerRun": 3}))
        data["reviewedEvents"][0]["summary"] = "Reviewed update within cooldown."
        second = self.tick(data, state, NOW + timedelta(minutes=15))
        self.assertEqual(self.calls, [])
        self.assertEqual(second["editions"]["sample"]["events"][0]["summary"], data["reviewedEvents"][0]["summary"])

    def test_generic_metadata_only_does_not_replace_explicit_review(self):
        data = policy()
        data["sources"][0]["metadataOnly"] = True
        data["posts"][0]["sourceIds"] = ["approved"]
        unreviewed = copy.deepcopy(data)
        unreviewed["reviewedEvents"] = []
        state = self.tick(unreviewed)
        self.assertEqual(state["editions"], {})
        self.assertTrue(state["reviewQueue"])
        self.assertEqual(set(state["reviewQueue"][0]), {"sourceId", "sourceHash", "itemHash", "url", "publishedAt", "change"})
        reviewed = self.tick(data, state, NOW + timedelta(minutes=15))
        self.assertEqual(reviewed["editions"]["sample"]["events"], data["reviewedEvents"])


if __name__ == "__main__":
    unittest.main()
