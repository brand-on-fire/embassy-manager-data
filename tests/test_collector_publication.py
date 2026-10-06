"""Offline tests: no provider, credentials, network, or actual Git push."""
import copy
from datetime import timedelta
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_collector import collector, feed, policy, NOW, ROOT

SPEC = importlib.util.spec_from_file_location('publisher', ROOT / 'collector-template/publish.py')
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)


def reviewed_policy(body=None):
    data = policy(body)
    data['publication'] = {'repository': 'brand-on-fire/embassy-manager-data', 'branch': 'public-data', 'maxPayloadBytes': 10485760, 'maxRepositoryBytes': 209715200, 'editionVersions': 3, 'sourceVersions': 2}
    data['sources'][0]['admission'] = {'anonymousPublicRead': True, 'permittedFeedUse': True, 'verifiedAt': '2026-10-05', 'accessEvidenceUrl': 'https://example.gov/feeds', 'rightsEvidenceUrl': 'https://example.gov/rights', 'scope': 'Offline fixture; not a real source admission.'}
    data['posts'][0].update(country='Example country', roleIds=['consular'])
    data['reviewedEvents'][0].update(sourceTitle='Dated public notice', publisher='Example publisher', supports='Offline fixture only.', topic='Consular services', reviewChecks={key: True for key in collector.REVIEW_CHECKS})
    return data


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out = self.root / 'public'
        self.snapshots = self.out / 'collector-state'

    def tick(self, data=None, state=None, now=NOW, body=None):
        return collector.run_tick(data or reviewed_policy(), state or {}, now, self.snapshots, lambda *_: (200, body or feed(), {}))

    def export(self, data=None, state=None):
        data = data or reviewed_policy()
        state = state or self.tick(data)
        manifest = collector.export_publication(data, state, self.out)
        envelope = json.loads((self.out / manifest['posts'][0]['path']).read_text())
        return manifest, envelope

    def test_content_hash_bytes_and_editorial_date_match(self):
        manifest, envelope = self.export()
        entry = manifest['posts'][0]
        raw = (self.out / entry['path']).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), entry['sha256'])
        self.assertEqual(len(raw), entry['bytes'])
        self.assertEqual(envelope['edition']['publishedAt'], '2026-10-04')
        self.assertEqual(envelope['generatedAt'], '2026-10-05T06:00:00Z')
        self.assertEqual(envelope['edition']['events'][0]['occurredAt'], '2026-10-02')
        self.assertEqual(envelope['sources'][0]['verifiedAt'], '2026-10-04')
        self.assertEqual(envelope['collection']['sourceCheckedAt'], '2026-10-05T06:00:00Z')
        publisher.storage_guard(self.out, 0, self.root / 'empty-git')

    def test_unchanged_tick_keeps_every_export_byte_and_mtime(self):
        data = reviewed_policy(); state = self.tick(data)
        collector.write_json(self.snapshots / 'state.json', state)
        self.export(data, state)
        before = {p.relative_to(self.out).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.out.rglob('*') if p.is_file()}
        state2 = collector.run_tick(data, state, NOW + timedelta(minutes=15), self.snapshots, lambda *_: self.fail('Unexpected fetch'))
        collector.write_json(self.snapshots / 'state.json', state2)
        self.export(data, state2)
        after = {p.relative_to(self.out).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.out.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_date_only_rss_is_explicit_and_never_invents_time(self):
        body = b'<rss><channel><item><title>Notice</title><link>https://example.gov/a</link><pubDate>Sun, 04 Oct 2026</pubDate></item></channel></rss>'
        self.assertEqual(collector.parse_feed(body, 'rss-atom', True)[0]['publishedAt'], '2026-10-04')
        with self.assertRaises(ValueError): collector.parse_feed(body, 'rss-atom')
        with self.assertRaises(ValueError): collector.parse_feed(body.replace(b'Sun,', b'Mon,'), 'rss-atom', True)

    def test_inspection_returns_the_complete_item_and_rejects_ambiguous_selection(self):
        body = feed(); path = self.root / 'complete.feed'; path.write_bytes(body)
        result = collector.inspect_feed(reviewed_policy(), path, 'official', 'https://example.gov/notice')
        self.assertEqual(result['completeEntry'], json.loads(body)['items'][0])
        self.assertEqual(result['responseBytes'], len(body))
        self.assertEqual(result['sourceHash'], collector.digest(body))
        another = json.loads(body); another['items'].append({**another['items'][0], 'title': 'Conflicting revision'})
        path.write_text(json.dumps(another))
        with self.assertRaisesRegex(ValueError, 'unambiguous'):
            collector.inspect_feed(reviewed_policy(), path, 'official', 'https://example.gov/notice')

    def test_unrelated_feed_change_preserves_exact_previously_reviewed_item(self):
        data = reviewed_policy(); state = self.tick(data)
        changed = json.loads(feed())
        changed['items'].append({'title': 'Unreviewed name and body', 'url': 'https://example.gov/new', 'date_published': '2026-10-05T12:00:00Z', 'content_text': 'Never public prose.'})
        body = json.dumps(changed).encode()
        result = self.tick(data, state, NOW + timedelta(days=1), body)
        self.assertEqual(result['editions']['example-post']['date'], '2026-10-06')
        manifest, envelope = self.export(data, result)
        self.assertEqual(len(envelope['edition']['events']), 1)
        queue = (self.out / 'review-queue.json').read_text()
        self.assertNotIn('Unreviewed name', queue)
        self.assertNotIn('Never public', queue)
        self.assertIn('https://example.gov/new', queue)
        self.assertEqual(envelope['edition']['publishedAt'], '2026-10-04')
        # A fresh collector cannot assume a prior review was accepted against another full feed.
        self.assertEqual(self.tick(data, now=NOW + timedelta(days=1), body=body)['editions'], {})

    def test_changed_item_retains_original_prose_with_review_warning(self):
        data = reviewed_policy(); state = self.tick(data)
        result = self.tick(data, state, NOW + timedelta(days=1), feed('Changed policy wording'))
        _, envelope = self.export(data, result)
        self.assertEqual(envelope['collection']['reviewState'], 'retained-last-valid')
        self.assertEqual(envelope['collection']['sourceWarnings'][0]['status'], 'awaiting-review')
        self.assertEqual(envelope['generatedAt'], '2026-10-05T06:00:00Z')
        self.assertEqual(envelope['edition']['events'][0]['summary'], 'Illustrative fixture only.')

    def test_removed_item_is_review_signal_not_automatic_retraction(self):
        data = reviewed_policy(); state = self.tick(data)
        result = self.tick(data, state, NOW + timedelta(days=1), b'{"items":[]}')
        _, envelope = self.export(data, result)
        self.assertEqual(result['reviewQueue'][0]['change'], 'removed')
        self.assertEqual(len(envelope['edition']['events']), 1)
        self.assertEqual(envelope['corrections'], [])

    def test_reviewed_retraction_is_explicit_and_excluded_from_current_events(self):
        data = reviewed_policy(); state = self.tick(data)
        body = feed('Official withdrawal')
        revised = reviewed_policy(body)
        revised['reviewedEvents'][0].update(status='retracted', reviewedAt='2026-10-06T05:00:00Z', correction={'kind': 'retracted', 'summary': 'The issuing source withdrew the notice.'})
        result = self.tick(revised, state, NOW + timedelta(days=1), body)
        _, envelope = self.export(revised, result)
        self.assertEqual(envelope['edition']['events'], [])
        self.assertEqual(envelope['corrections'][0]['eventId'], 'notice-1')
        self.assertEqual(envelope['corrections'][0]['kind'], 'retracted')
        self.assertEqual(envelope['edition']['publishedAt'], '2026-10-06')
        self.assertEqual(len(envelope['sources']), 1)

    def test_corrected_source_link_gets_new_evidence_identity_and_stable_event(self):
        data = reviewed_policy(); state = self.tick(data)
        _, before = self.export(data, state)
        changed = json.loads(feed()); changed['items'][0]['url'] = 'https://example.gov/corrected-notice'
        body = json.dumps(changed).encode(); revised = reviewed_policy(body)
        revised['reviewedEvents'][0].update(reviewedAt='2026-10-06T05:00:00Z', correction={'kind': 'corrected', 'summary': 'The notice source link was corrected.'})
        result = self.tick(revised, state, NOW + timedelta(days=1), body)
        _, after = self.export(revised, result)
        self.assertEqual(before['edition']['events'][0]['id'], after['edition']['events'][0]['id'])
        self.assertNotEqual(before['sources'][0]['id'], after['sources'][0]['id'])
        self.assertEqual(after['sources'][0]['url'], changed['items'][0]['url'])
        self.assertEqual(after['corrections'][0]['sourceIds'], [after['sources'][0]['id']])

    def test_review_deletion_cannot_silently_erase_or_unflag_published_work(self):
        data = reviewed_policy(); state = self.tick(data)
        data['reviewedEvents'] = []
        with self.assertRaisesRegex(ValueError, 'explicit reviewed correction'):
            self.tick(data, state, NOW + timedelta(days=1))

    def test_stale_failure_preserves_review_age(self):
        data = reviewed_policy(); state = self.tick(data)
        result = self.tick(data, state, NOW + timedelta(days=3), b'invalid')
        _, envelope = self.export(data, result)
        self.assertEqual(envelope['collection']['sourceWarnings'][0]['status'], 'stale')
        self.assertEqual(envelope['collection']['sourceCheckedAt'], '2026-10-05T06:00:00Z')
        self.assertEqual(envelope['sources'][0]['verifiedAt'], '2026-10-04')

    def test_discovery_only_source_collects_metadata_without_inventing_post_events(self):
        data = reviewed_policy(); data['posts'] = []; data['reviewedEvents'] = []
        data['sources'][0]['metadataOnly'] = True
        state = self.tick(data)
        self.assertEqual(state['editions'], {})
        self.assertEqual(len(state['reviewQueue']), 1)
        manifest = collector.export_publication(data, state, self.out)
        self.assertEqual(manifest['posts'], [])
        self.assertIsNone(manifest['generatedAt'])
        collector.run_tick(data, state, NOW + timedelta(minutes=15), self.snapshots, lambda *_: self.fail('Six-hour minimum not enforced'))

    def test_admission_review_role_correction_and_acronym_guards(self):
        mutations = [lambda p: p['sources'][0]['admission'].update(permittedFeedUse=False), lambda p: p['reviewedEvents'][0]['reviewChecks'].update(completeInputReviewed=False), lambda p: p['reviewedEvents'][0].update(roleIds=['unsupported']), lambda p: p['reviewedEvents'][0].update(summary='Undefined XYZ acronym.'), lambda p: p['reviewedEvents'][0].update(status='retracted', correction={'kind': 'corrected', 'summary': 'Conflicting status.'}), lambda p: p['reviewedEvents'][0].update(summary='<script>unsafe</script>')]
        for mutation in mutations:
            data = reviewed_policy(); mutation(data)
            with self.assertRaises(ValueError): collector.validate_policy(data)

    def test_retained_file_counts_and_payload_cap(self):
        data = reviewed_policy(); state = None
        for day in range(6):
            state = self.tick(data, state, NOW + timedelta(days=day))
            self.export(data, state)
            collector.prune_snapshots(data, self.snapshots)
        self.assertEqual(len(list((self.out / 'editions/example-post').glob('*.json'))), 3)
        self.assertEqual(len(list((self.snapshots / 'editions/example-post').glob('*.json'))), 3)
        data['publication']['maxPayloadBytes'] = 1
        with self.assertRaisesRegex(ValueError, 'payload limit'): self.export(data, state)

    def test_manifest_tampering_and_repository_size_stop(self):
        manifest, _ = self.export()
        with self.assertRaisesRegex(ValueError, 'MAINTENANCE'):
            publisher.storage_guard(self.out, publisher.MAX_REPOSITORY, self.root / 'empty')
        entry = manifest['posts'][0]
        (self.out / entry['path']).write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError, 'hash or byte count'):
            publisher.storage_guard(self.out, 0, self.root / 'empty')

    def test_unexpected_files_symlinks_and_wrong_workflow_are_rejected(self):
        self.export()
        bad = self.out / 'visitor-export.json'; bad.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'Unexpected'): publisher.storage_guard(self.out, 0, self.root / 'empty')
        bad.unlink(); bad.symlink_to(self.out / 'manifest.json')
        with self.assertRaisesRegex(ValueError, 'Symbolic'): publisher.storage_guard(self.out, 0, self.root / 'empty')
        with patch.dict(os.environ, {}, clear=True), patch.object(publisher, 'urlopen', side_effect=AssertionError('No network allowed')):
            with self.assertRaisesRegex(ValueError, 'restricted'): publisher.check_context()

    def test_checked_in_export_is_actual_byte_valid(self):
        data = json.loads((ROOT / 'data/collection-policy.json').read_text())
        collector.validate_policy(data)
        publisher.storage_guard(ROOT / 'collector-template/example', 0, self.root / 'empty')


class GitTransportTests(unittest.TestCase):
    def test_ordinary_commit_parent_and_unchanged_no_push(self):
        with tempfile.TemporaryDirectory() as directory:
            old_cwd = Path.cwd(); os.chdir(directory)
            try:
                subprocess.run(['git', 'init', '-q'], check=True)
                generated = Path(directory) / 'generated'; generated.mkdir()
                (generated / 'manifest.json').write_text('{}')
                calls = []; real_run = publisher.run
                def offline_run(*args, env=None):
                    if args[:2] == ('git', 'push'):
                        calls.append(args)
                        self.assertNotIn('--force', args)
                        return b''
                    return real_run(*args, env=env)
                with patch.dict(os.environ, {'GH_TOKEN': 'offline-test-placeholder'}), patch.object(publisher, 'run', side_effect=offline_run), patch('builtins.print'):
                    publisher.publish(generated, None)
                    self.assertEqual(len(calls), 1)
                    commit = calls[0][-1].split(':')[0]
                    parent_line = real_run('git', 'rev-list', '--parents', '-n', '1', commit).decode().split()
                    self.assertEqual(parent_line, [commit])
                    publisher.publish(generated, commit)
                    self.assertEqual(len(calls), 1)
                    (generated / 'manifest.json').write_text('{"changed":true}')
                    publisher.publish(generated, commit)
                    newer = calls[-1][-1].split(':')[0]
                    self.assertEqual(real_run('git', 'rev-list', '--parents', '-n', '1', newer).decode().split(), [newer, commit])
                    restored = Path(directory) / 'restored'
                    publisher.restore(restored, newer)
                    self.assertEqual((restored / 'manifest.json').read_bytes(), (generated / 'manifest.json').read_bytes())
            finally:
                os.chdir(old_cwd)


if __name__ == '__main__':
    unittest.main()
