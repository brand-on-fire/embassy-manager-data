"""Offline metadata discovery: complete inputs, bounded pointers, no publication."""
import copy
from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from test_collector import collector, NOW, ROOT, policy
from test_collector_publication import reviewed_policy


URL = "https://www.govinfo.gov/metadata/pkg/FR-2026-10-05/mods.xml"
DOCUMENT_URL = "https://www.govinfo.gov/content/pkg/FR-2026-10-05/html/2026-20384.htm"
FIXTURES = ROOT / "tests/fixtures/govinfo"
NS = "{http://www.loc.gov/mods/v3}"
HREF = "{http://www.w3.org/1999/xlink}href"
PATH = {"m": NS[1:-1]}


def discovery_policy():
    data = policy()
    data.update(allowedHosts=["www.govinfo.gov"], maxResponseBytes=1048576,
                maxSourcesPerRun=2, reviewedEvents=[])
    data["sources"][0].update(url=URL, parser="govinfo-fr-mods", metadataOnly=True)
    data["posts"].append({"id": "second-post", "timezone": "UTC", "sourceIds": ["official"]})
    return data


def serialize(root):
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def selected(root):
    return next(item for item in root.findall(NS + "relatedItem")
                if item.findtext('m:identifier[@type="FR Doc No."]', namespaces=PATH) == "2026-20384")


class ModsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.body = (FIXTURES / "FR-2026-10-05-mods.xml").read_bytes()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)

    def parse(self, body=None, url=URL):
        return collector.parse_feed(self.body if body is None else body, "govinfo-fr-mods", source_url=url)

    def tree(self):
        return ET.fromstring(self.body)

    def assert_rejected(self, body, url=URL):
        with self.assertRaises((ValueError, UnicodeError, ET.ParseError)):
            self.parse(body, url)

    def test_complete_real_issue_produces_only_106_unique_document_pointers(self):
        self.assertEqual(len(self.body), 623157)
        self.assertEqual(collector.digest(self.body), "a82bf6140c8a92770f1170ed3cb38853e7f83b0f3594a00688808fc78e44c910")
        root = self.tree()
        constituents = root.findall(NS + "relatedItem")
        self.assertEqual(len(constituents), 108)
        self.assertEqual(len(root.findall(".//" + NS + "relatedItem")), 384)
        classes = {}
        for item in constituents:
            kind = item.findtext("m:extension/m:granuleClass", namespaces=PATH)
            classes[kind] = classes.get(kind, 0) + 1
        self.assertEqual(classes, {"CONTENTS": 1, "RULE": 8, "PRORULE": 17, "NOTICE": 80, "PRESDOCU": 1, "AIDS": 1})
        result = self.parse()
        self.assertEqual(len(result), 106)
        self.assertEqual(len({item["url"] for item in result}), 106)
        self.assertEqual(len({item["itemHash"] for item in result}), 106)
        for item in result:
            self.assertEqual(set(item), {"itemHash", "url", "publishedAt"})
            self.assertRegex(item["itemHash"], r"^[a-f0-9]{64}$")
            self.assertRegex(item["url"], r"^https://www\.govinfo\.gov/content/pkg/FR-2026-10-05/html/\d{4}-\d{4,6}\.htm$")
            self.assertEqual(item["publishedAt"], "2026-10-05")
        self.assertIn(DOCUMENT_URL, {item["url"] for item in result})

    def test_issue_publication_is_not_ingestion_or_record_change_date(self):
        root = self.tree()
        root.find("m:extension/m:dateIngested", PATH).text = "2026-10-06"
        root.find("m:recordInfo/m:recordChangeDate", PATH).text = "2026-10-06"
        result = self.parse(serialize(root))
        self.assertEqual({item["publishedAt"] for item in result}, {"2026-10-05"})

    def test_endpoint_is_fixed_and_identity_matches_entire_package(self):
        for url in (None, URL + "?x=1", URL + "#fragment", URL.replace("www.govinfo.gov", "www.govinfo.gov.example"),
                    URL.replace("https://", "http://"), URL.replace("2026-10-05", "2026-10-06"),
                    URL.replace("2026-10-05", "2026-02-30"), URL.replace("/pkg/", "/granule/")):
            with self.subTest(url=url):
                self.assert_rejected(self.body, url)

    def test_incomplete_encoding_and_declarations_reject_whole_input(self):
        cases = {
            "empty": b"", "missing-closing-root": self.body.rsplit(b"</mods>", 1)[0],
            "invalid-utf8": self.body.replace(b"Methionine", b"\xffMethionine", 1),
            "utf16": self.body.decode("utf-8").replace('encoding="UTF-8"', 'encoding="UTF-16"').encode("utf-16"),
            "doctype": self.body.replace(b"<mods ", b'<!DOCTYPE mods [<!ENTITY test "value">]><mods ', 1),
            "instruction": self.body.replace(b"<mods ", b'<?probe instruction?><mods ', 1),
            "comment": self.body.replace(b"Methionine", b"<!--source revision-->Methionine", 1),
            "trailing-garbage": self.body + b"incomplete-extra-record",
        }
        for name, body in cases.items():
            with self.subTest(case=name):
                self.assert_rejected(body)

    def test_root_namespace_dates_and_duplicate_required_fields_reject(self):
        mutations = (
            lambda r: setattr(r, "tag", NS + "modsCollection"),
            lambda r: setattr(r, "tag", "mods"),
            lambda r: setattr(r.find("m:originInfo/m:dateIssued", PATH), "text", "2026-10-06"),
            lambda r: setattr(r.find("m:originInfo/m:dateIssued", PATH), "text", "2026-02-30"),
            lambda r: r.find("m:originInfo", PATH).remove(r.find("m:originInfo/m:dateIssued", PATH)),
            lambda r: r.find("m:originInfo", PATH).append(copy.deepcopy(r.find("m:originInfo/m:dateIssued", PATH))),
            lambda r: setattr(r.find("m:extension/m:accessId", PATH), "text", "FR-2026-10-06"),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(case=index):
                root = self.tree()
                mutate(root)
                self.assert_rejected(serialize(root))

    def test_one_invalid_or_duplicate_constituent_rejects_every_candidate(self):
        def duplicate(root):
            root.append(copy.deepcopy(selected(root)))

        def missing_title(root):
            node = selected(root).find("m:titleInfo", PATH)
            node.remove(node.find(NS + "title"))

        def duplicate_document_id(root):
            item = selected(root)
            item.append(copy.deepcopy(item.find('m:identifier[@type="FR Doc No."]', PATH)))

        mutations = (
            duplicate, missing_title, duplicate_document_id,
            lambda r: selected(r).set("type", "host"),
            lambda r: selected(r).set("ID", "id-2026-99999"),
            lambda r: setattr(selected(r).find('m:identifier[@type="FR Doc No."]', PATH), "text", "not-a-document"),
            lambda r: setattr(selected(r).find("m:extension/m:frDocNumber", PATH), "text", "2026-99999"),
            lambda r: setattr(selected(r).find("m:extension/m:accessId", PATH), "text", "2026-99999"),
            lambda r: setattr(selected(r).find("m:extension/m:granuleClass", PATH), "text", "UNKNOWN"),
            lambda r: setattr(selected(r).find("m:titleInfo/m:partName", PATH), "text", "Proposed Rules"),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(case=index):
                root = self.tree()
                mutate(root)
                self.assert_rejected(serialize(root))

    def test_canonical_links_cannot_disagree_or_escape_source(self):
        paths = ('m:identifier[@type="uri"]', 'm:location/m:url[@displayLabel="HTML rendition"]',
                 'm:location/m:url[@displayLabel="PDF rendition"]')
        for path in paths:
            for suffix in ("?x=1", "#fragment"):
                with self.subTest(path=path, suffix=suffix):
                    root = self.tree()
                    node = selected(root).find(path, PATH)
                    node.text += suffix
                    self.assert_rejected(serialize(root))
        for path in (None, 'm:relatedItem[@type="otherFormat"]'):
            for replacement in ("https://example.gov/other.xml", URL, "https://www.govinfo.gov/metadata/granule/FR-2026-10-05/2026-99999/mods.xml"):
                with self.subTest(path=path, replacement=replacement):
                    root = self.tree()
                    node = selected(root) if path is None else selected(root).find(path, PATH)
                    node.set(HREF, replacement)
                    self.assert_rejected(serialize(root))

    def test_complete_granule_prose_and_reference_links_affect_hash_not_output(self):
        baseline = {item["url"]: item for item in self.parse()}
        for path in ("m:abstract", "m:extension/m:summary", "m:extension/m:contact", "m:extension/m:urlRef"):
            with self.subTest(path=path):
                root = self.tree()
                node = selected(root).find(path, PATH)
                node.text += "/changed" if path.endswith("urlRef") else " Complete-source revision."
                changed = {item["url"]: item for item in self.parse(serialize(root))}
                changed_urls = {url for url in baseline if baseline[url] != changed[url]}
                self.assertEqual(changed_urls, {DOCUMENT_URL})
                self.assertEqual(set(changed[DOCUMENT_URL]), {"itemHash", "url", "publishedAt"})

        root = self.tree()
        extra = ET.SubElement(selected(root).find("m:extension", PATH), NS + "reviewNote", {"revision": "fixture-only"})
        extra.text = "Uninterpreted complete metadata must remain part of the evidence hash."
        changed = next(item for item in self.parse(serialize(root)) if item["url"] == DOCUMENT_URL)
        self.assertNotEqual(changed["itemHash"], baseline[DOCUMENT_URL]["itemHash"])
        extra.set("revision", "second-fixture-revision")
        changed_again = next(item for item in self.parse(serialize(root)) if item["url"] == DOCUMENT_URL)
        self.assertNotEqual(changed["itemHash"], changed_again["itemHash"])

    def test_front_matter_and_reader_aids_still_count_toward_500_limit(self):
        # Keep the complete synthetic input below the byte and node limits so
        # this tests the item count, including the two excluded constituents.
        root = self.tree()
        for item in list(root.findall(NS + "relatedItem")):
            if item.findtext("m:extension/m:granuleClass", namespaces=PATH) not in ("CONTENTS", "AIDS"):
                root.remove(item)
        base = "https://www.govinfo.gov/"

        def constituent(index):
            document = f"2026-{10000 + index}"
            detail = base + "app/details/FR-2026-10-05/" + document
            html = base + "content/pkg/FR-2026-10-05/html/" + document + ".htm"
            pdf = base + "content/pkg/FR-2026-10-05/pdf/" + document + ".pdf"
            item = ET.Element(NS + "relatedItem", {"type": "constituent", "ID": "id-" + document,
                                                   HREF: base + "metadata/granule/FR-2026-10-05/" + document + "/mods.xml"})
            title = ET.SubElement(item, NS + "titleInfo")
            ET.SubElement(title, NS + "title").text = "Synthetic metadata count fixture"
            ET.SubElement(title, NS + "partName").text = "Notices"
            ET.SubElement(item, NS + "identifier", {"type": "FR Doc No."}).text = document
            ET.SubElement(item, NS + "identifier", {"type": "uri"}).text = detail
            location = ET.SubElement(item, NS + "location")
            for label, url in (("Content Detail", detail), ("HTML rendition", html), ("PDF rendition", pdf)):
                ET.SubElement(location, NS + "url", {"displayLabel": label}).text = url
            for url in (html, pdf):
                ET.SubElement(item, NS + "relatedItem", {"type": "otherFormat", HREF: url})
            extension = ET.SubElement(item, NS + "extension")
            for tag, text in (("accessId", document), ("frDocNumber", document), ("granuleClass", "NOTICE")):
                ET.SubElement(extension, NS + tag).text = text
            return item

        for index in range(498):
            root.append(constituent(index))
        self.assertEqual(len(root.findall(NS + "relatedItem")), 500)
        self.assertLess(len(serialize(root)), 1048576)
        self.assertEqual(len(self.parse(serialize(root))), 498)
        root.append(constituent(498))
        self.assertEqual(len(root.findall(NS + "relatedItem")), 501)
        self.assertLess(len(serialize(root)), 1048576)
        with self.assertRaisesRegex(ValueError, "500"):
            self.parse(serialize(root))

    def test_depth_nodes_and_complete_response_bytes_are_bounded(self):
        root = self.tree()
        for item in list(root.findall(NS + "relatedItem")):
            if item is not selected(root):
                root.remove(item)
        compact = serialize(root)
        self.assertEqual(len(self.parse(compact)), 1)
        deep = copy.deepcopy(root)
        parent = selected(deep).find("m:extension", PATH)
        for _ in range(21):
            parent = ET.SubElement(parent, NS + "note")
        self.assertLess(len(serialize(deep)), 1048576)
        self.assert_rejected(serialize(deep))
        wide = copy.deepcopy(root)
        parent = selected(wide).find("m:extension", PATH)
        for _ in range(50001):
            ET.SubElement(parent, NS + "note")
        self.assertLess(len(serialize(wide)), 1048576)
        self.assert_rejected(serialize(wide))
        oversized = self.body + b" " * (1048577 - len(self.body))
        self.assert_rejected(oversized)

    def test_metadata_requires_explicit_admission_and_cannot_approve_events(self):
        data = discovery_policy()
        collector.validate_policy(data)
        for value in (None, False, "true"):
            with self.subTest(metadataOnly=value):
                invalid = copy.deepcopy(data)
                if value is None:
                    invalid["sources"][0].pop("metadataOnly")
                else:
                    invalid["sources"][0]["metadataOnly"] = value
                with self.assertRaises(ValueError):
                    collector.validate_policy(invalid)
        event = policy()["reviewedEvents"][0]
        event.update(sourceUrl=DOCUMENT_URL, sourceHash=collector.digest(self.body),
                     itemHash=next(i["itemHash"] for i in self.parse() if i["url"] == DOCUMENT_URL),
                     publishedAt="2026-10-05", reviewedAt="2026-10-05T06:00:00Z")
        for binding in (None, collector.DOCUMENT_REVIEW_BINDING):
            invalid = copy.deepcopy(data)
            invalid["reviewedEvents"] = [copy.deepcopy(event)]
            if binding:
                invalid["reviewedEvents"][0]["reviewBinding"] = binding
            with self.subTest(binding=binding), self.assertRaises(ValueError):
                collector.validate_policy(invalid)

    def test_shared_discovery_queues_pointers_without_editions_or_source_prose(self):
        calls = []
        data = discovery_policy()
        state = collector.run_tick(data, {}, NOW, self.output,
                                   lambda *args: (calls.append(args[0]["id"]) or (200, self.body, {})))
        self.assertEqual(calls, ["official"])
        self.assertEqual(state["editions"], {})
        self.assertEqual(state["acceptedReviews"], {})
        self.assertEqual(len(state["reviewQueue"]), 106)
        expected = {"sourceId", "sourceHash", "itemHash", "url", "publishedAt", "change"}
        for item in state["reviewQueue"]:
            self.assertEqual(set(item), expected)
        saved = list((self.output / "sources").rglob("*.json"))
        self.assertEqual(len(saved), 1)
        for raw in (json.dumps(state), saved[0].read_text()):
            self.assertNotIn("Methionine", raw)
            self.assertNotIn("Applicable October", raw)
            self.assertNotIn("Complete-source revision", raw)
            for contact in self.tree().findall("m:relatedItem/m:extension/m:contact", PATH):
                if contact.text and contact.text.strip():
                    self.assertNotIn(contact.text, raw)

    def test_publication_validation_and_retained_export_cannot_bypass_metadata_gate(self):
        data = reviewed_policy()
        collector.validate_publication_policy(data)
        data["allowedHosts"] = ["www.govinfo.gov"]
        data["sources"][0].update(url=URL, parser="govinfo-fr-mods", metadataOnly=True)
        event = data["reviewedEvents"][0]
        event.update(sourceUrl=DOCUMENT_URL, sourceHash=collector.digest(self.body),
                     itemHash=next(item["itemHash"] for item in self.parse() if item["url"] == DOCUMENT_URL),
                     publishedAt="2026-10-05", reviewedAt="2026-10-05T06:00:00Z")
        with self.assertRaises(ValueError):
            collector.validate_publication_policy(data)
        # Even if no new metadata-backed review is configured, retained state
        # must not publish one without the same full-document admission gate.
        state = {"editions": {"example-post": {"events": [copy.deepcopy(event)]}}}
        data["reviewedEvents"] = []
        with self.assertRaises(ValueError):
            collector.publication_envelope(data, state, data["posts"][0])

    def test_six_hour_poll_and_two_attempt_tick_limits_are_unchanged(self):
        data = discovery_policy()
        for index in (2, 3):
            source = copy.deepcopy(data["sources"][0])
            source["id"] = f"metadata-{index}"
            data["sources"].append(source)
        calls = []
        fetch = lambda source, *_: (calls.append(source["id"]) or (200, self.body, {}))
        state = collector.run_tick(data, {}, NOW, self.output, fetch)
        self.assertEqual(calls, ["official", "metadata-2"])
        calls.clear()
        state = collector.run_tick(data, state, NOW + timedelta(minutes=15), self.output, fetch)
        self.assertEqual(calls, ["metadata-3"])
        state = collector.run_tick(data, state, NOW + timedelta(hours=5, minutes=59), self.output,
                                   lambda *_: self.fail("A source was polled before six hours"))
        calls.clear()
        collector.run_tick(data, state, NOW + timedelta(hours=6), self.output, fetch)
        self.assertEqual(calls, ["official", "metadata-2"])

    def test_failed_refresh_retains_complete_queue_and_observes_retry_interval(self):
        data = discovery_policy()
        state = collector.run_tick(data, {}, NOW, self.output, lambda *_: (200, self.body, {}))
        for bad in (self.body.rsplit(b"</mods>", 1)[0], self.body + b" " * 1048576):
            with self.subTest(case="oversized" if len(bad) > 1048576 else "incomplete"):
                failed = collector.run_tick(data, state, NOW + timedelta(hours=6), self.output, lambda *_: (200, bad, {}))
                self.assertEqual(failed["sources"]["official"]["status"], "failed")
                self.assertEqual(failed["sources"]["official"]["lastValidHash"], state["sources"]["official"]["lastValidHash"])
                self.assertEqual(failed["sources"]["official"]["items"], state["sources"]["official"]["items"])
                self.assertEqual(failed["reviewQueue"], state["reviewQueue"])
                self.assertEqual(failed["editions"], {})
                collector.run_tick(data, failed, NOW + timedelta(hours=6, minutes=15), self.output,
                                   lambda *_: self.fail("A failed attempt was retried early"))

    def test_complete_document_remains_separate_from_discovery_hash(self):
        body = (FIXTURES / "2026-20384.htm").read_bytes()
        self.assertEqual(len(body), 8294)
        self.assertEqual(collector.digest(body), "a55176388a13f0d66318bdb31c839ac275977bcfbaa28e94523fd96a4abcdcd7")
        item = collector.parse_feed(body, "govinfo-fr-html", source_url=DOCUMENT_URL)[0]
        self.assertEqual(item, {"url": DOCUMENT_URL, "publishedAt": "2026-10-05",
                                "itemHash": "ecf6d170687bcbafcca868417c9ec7f31c23a6c3ccb5f0f440520cf2a1acee58"})
        metadata = next(item for item in self.parse() if item["url"] == DOCUMENT_URL)
        self.assertNotEqual(metadata["itemHash"], item["itemHash"])

    def test_offline_inspection_exposes_complete_granule_without_approving_it(self):
        inspected = collector.inspect_feed(discovery_policy(), FIXTURES / "FR-2026-10-05-mods.xml", "official", DOCUMENT_URL)
        self.assertEqual(inspected["responseBytes"], len(self.body))
        self.assertEqual(inspected["sourceHash"], collector.digest(self.body))
        expected = ET.tostring(selected(self.tree()), encoding="unicode")
        self.assertEqual(inspected["completeEntry"], expected)
        self.assertEqual(inspected["itemHash"], collector.digest(expected.encode()))
        self.assertNotIn("reviewChecks", inspected)
        self.assertEqual(list(self.output.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
