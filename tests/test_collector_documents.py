"""Offline complete-document admission regressions; no public fetches or publication."""
import copy
import json
from datetime import timedelta
from pathlib import Path
import tempfile
import unittest

from test_collector import collector, NOW
from test_collector_publication import reviewed_policy

URL = 'https://www.govinfo.gov/content/pkg/FR-2026-10-04/html/2026-12345.htm'


def document(text='A synthetic proposed consultation, not an effective measure.'):
    return ('''<html><head><title>Offline test document</title></head><body><pre>
[Federal Register Volume 91, Number 190 (Sunday, October 4, 2026)]
[Notices]
[FR Doc No: 2026-12345]
''' + text + '''
[FR Doc. 2026-12345 Filed 10-2-26; 8:45 am]
BILLING CODE 0000-00-P
</pre></body></html>''').encode()


def document_policy(body=None, semantic=True):
    body = body or document()
    data = reviewed_policy()
    data['allowedHosts'] = ['www.govinfo.gov']
    data['sources'][0].update(parser='govinfo-fr-html', url=URL)
    item = collector.parse_feed(body, 'govinfo-fr-html', source_url=URL)[0]
    data['reviewedEvents'][0].update(sourceUrl=URL, sourceHash=collector.digest(body), itemHash=item['itemHash'], publishedAt='2026-10-04', occurredAt='2026-10-04', status='proposed', precision='relevance')
    if semantic:
        data['reviewedEvents'][0]['reviewBinding'] = collector.DOCUMENT_REVIEW_BINDING
    return data


def protected_document(key=1, address='contact@example.gov', href='https://example.gov/notice'):
    encoded = bytes([key, *(byte ^ key for byte in address.encode())]).hex()
    return document(f'A complete synthetic notice. <a href="{href}">Full guidance</a>\nContact: <a href="/cdn-cgi/l/email-protection#{encoded}"><span class="__cf_email__" data-cfemail="{encoded}">[email&#160;protected]</span></a>')


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_complete_hash_and_publication_are_independent_of_filing_and_fetch_time(self):
        body = document()
        metadata = collector.parse_feed(body, 'govinfo-fr-html', source_url=URL)
        self.assertEqual(set(metadata[0]), {'itemHash', 'url', 'publishedAt'})
        self.assertEqual(metadata[0]['publishedAt'], '2026-10-04')
        path = self.root / 'document.htm'; path.write_bytes(body)
        inspected = collector.inspect_feed(document_policy(), path, 'official', URL)
        self.assertEqual(inspected['completeEntry'], body.decode())
        self.assertEqual(inspected['responseBytes'], len(body))
        self.assertEqual(inspected['sourceHash'], collector.digest(body))
        self.assertEqual(inspected['itemHash'], metadata[0]['itemHash'])
        self.assertNotEqual(inspected['sourceHash'], inspected['itemHash'])

    def test_document_endpoint_and_complete_header_footer_must_agree(self):
        for url in [URL.replace('www.govinfo.gov', 'www.govinfo.gov.evil.example'), URL.replace('2026-10-04', '2026-10-05'), URL + '?x=1', URL.replace('2026-12345', '2026-12346')]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                collector.parse_feed(document(), 'govinfo-fr-html', source_url=url)
        for body in [
            document().replace(b'Sunday', b'Monday'), document().replace(b'</pre>', b''),
            document().replace(b'</html>', b''), document().replace(b'[FR Doc No: 2026-12345]', b'[FR Doc No: 2026-99999]'),
            document().replace(b'[FR Doc. 2026-12345 Filed', b'[FR Doc. 2026-99999 Filed'),
            document().replace(b'BILLING CODE', b'INCOMPLETE'), document().replace(b'</pre>', b'</pre><pre>second</pre>'),
            document('<script>unreviewed script</script>'), b'<!DOCTYPE html>' + document(),
        ]:
            with self.subTest(body=body), self.assertRaises(ValueError):
                collector.parse_feed(body, 'govinfo-fr-html', source_url=URL)

    def test_reviewed_proposal_exports_only_reviewed_prose_as_geographic_relevance(self):
        body = document('Raw synthetic source contacts and markup must never be persisted.')
        data = document_policy(body)
        state = collector.run_tick(data, {}, NOW, self.root / 'snapshots', lambda *_: (200, body, {}))
        manifest = collector.export_publication(data, state, self.root / 'public')
        envelope = json.loads((self.root / 'public' / manifest['posts'][0]['path']).read_text())
        event = envelope['edition']['events'][0]
        self.assertEqual(event['status'], 'proposed')
        self.assertEqual(event['precision'], 'relevance')
        self.assertEqual(event['publishedAt'], '2026-10-04')
        self.assertEqual(envelope['collection']['sourceCheckedAt'], '2026-10-05T06:00:00Z')
        for path in self.root.rglob('*.json'):
            self.assertNotIn('Raw synthetic source contacts', path.read_text())
        self.assertEqual(set(state['sources']['official']['items'][0]), {'itemHash', 'url', 'publishedAt'})

    def test_changed_complete_prose_or_link_needs_review_and_cannot_replace_a_published_proposal(self):
        data = document_policy(); original = document()
        for changed in [document('An unreviewed final rule claim.'), document('A synthetic proposed consultation, not an effective measure.<a href="https://example.gov/new">New guidance</a>')]:
            first = collector.run_tick(data, {}, NOW, self.root, lambda *_: (200, original, {}))
            second = collector.run_tick(data, first, NOW + timedelta(days=1), self.root, lambda *_: (200, changed, {}))
            self.assertEqual(second['editions']['example-post']['events'], first['editions']['example-post']['events'])
            self.assertEqual(second['editions']['example-post']['warnings'][0]['status'], 'awaiting-review')
            self.assertEqual(second['reviewQueue'][0]['change'], 'changed')
            self.assertNotIn('unreviewed final rule', json.dumps(second))

    def test_complete_semantic_binding_accepts_first_fresh_nonce_change_without_changing_provenance(self):
        approved, fresh = protected_document(1), protected_document(77)
        data = document_policy(approved)
        self.assertNotEqual(collector.digest(approved), collector.digest(fresh))
        self.assertEqual(collector.parse_feed(approved, 'govinfo-fr-html', source_url=URL), collector.parse_feed(fresh, 'govinfo-fr-html', source_url=URL))
        state = collector.run_tick(data, {}, NOW, self.root, lambda *_: (200, fresh, {}))
        self.assertIn('example-post', state['editions'])
        self.assertEqual(state['sources']['official']['lastValidHash'], collector.digest(fresh))
        self.assertEqual(state['editions']['example-post']['events'][0]['sourceHash'], collector.digest(approved))
        self.assertEqual(state['acceptedReviews']['notice-1'], collector.digest(data['reviewedEvents'][0]))
        self.assertNotIn('contact@example.gov', json.dumps(state))
        no_binding = document_policy(approved, semantic=False)
        withheld = collector.run_tick(no_binding, {}, NOW, self.root / 'exact-only', lambda *_: (200, fresh, {}))
        self.assertNotIn('example-post', withheld['editions'])

    def test_changed_link_or_decoded_email_is_not_a_nonce_change(self):
        approved = protected_document(1)
        data = document_policy(approved)
        for body in [protected_document(77, href='https://example.gov/different'), protected_document(77, address='different@example.gov'), protected_document(77).replace(b'complete synthetic', b'changed synthetic')]:
            state = collector.run_tick(data, {}, NOW, self.root, lambda *_: (200, body, {}))
            self.assertNotIn('example-post', state['editions'])
            self.assertNotEqual(state['sources']['official']['items'][0]['itemHash'], data['reviewedEvents'][0]['itemHash'])

    def test_semantic_binding_is_explicit_and_restricted_to_this_document_parser(self):
        for parser in ['json-feed', 'rss-atom']:
            data = reviewed_policy(); data['sources'][0]['parser'] = parser
            data['reviewedEvents'][0]['reviewBinding'] = collector.DOCUMENT_REVIEW_BINDING
            with self.assertRaisesRegex(ValueError, 'restricted'):
                collector.validate_policy(data)
        data = document_policy(); data['reviewedEvents'][0]['reviewBinding'] = 'partial-text'
        with self.assertRaisesRegex(ValueError, 'restricted'):
            collector.validate_policy(data)
        for body in [protected_document().replace(b'data-cfemail="', b'data-cfemail="ff'), protected_document().replace(b'[email&#160;protected]', b'Additional hidden content'), protected_document().replace(b'__cf_email__', b'unknown')]:
            with self.assertRaises(ValueError):
                collector.parse_feed(body, 'govinfo-fr-html', source_url=URL)

    def test_shared_document_is_fetched_once_and_location_scope_is_validated(self):
        data = document_policy()
        data['posts'].append({**data['posts'][0], 'id': 'second-post'})
        data['reviewedEvents'][0]['postIds'].append('second-post')
        calls = []
        state = collector.run_tick(data, {}, NOW, self.root, lambda source, *_: (calls.append(source['id']) or 200, document(), {}))
        self.assertEqual(calls, ['official'])
        self.assertEqual(set(state['editions']), {'example-post', 'second-post'})
        for precision in ['city', 'unknown', None]:
            bad = copy.deepcopy(data); bad['reviewedEvents'][0]['precision'] = precision
            with self.assertRaisesRegex(ValueError, 'relevance'):
                collector.validate_policy(bad)
        bad = copy.deepcopy(data); bad['sources'][0]['url'] = 'https://www.govinfo.gov/rss/fr.xml'
        with self.assertRaisesRegex(ValueError, 'document URL'):
            collector.validate_policy(bad)


if __name__ == '__main__':
    unittest.main()
