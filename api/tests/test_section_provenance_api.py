"""Engine-free item provenance, no backfill, same request body-read budget."""
import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, evidence, markdown_parser as md, provenance, section_provenance as sp
from api.services.claims import Evidence

EP = 'ep_2026-10-07_001'
SOURCE = 'user: A synthetic observation.\nassistant: Another observation 🐝.'
BODY = '## Summary\nExample project.\n\n## Key Facts\n- One fact.\n- Another fact.'


@pytest.fixture
def bank(tmp_path):
    (tmp_path / 'episodes').mkdir()
    (tmp_path / 'entities').mkdir()
    md.write(tmp_path / 'episodes' / f'{EP}.md', {'title': 'Synthetic conversation', 'session_id': 'session-example'}, SOURCE)
    ev = Evidence(episode=EP, start=6, end=29, hash=evidence.body_hash(SOURCE), kind='user')
    rows = {}
    for key, items in sp.scan(BODY).items():
        rows[key] = {item.key: (item.text_hash, [ev, evidence.reasoning(EP, hash=ev.hash)]) for item in items}
    md.write(tmp_path / 'entities' / 'alpha-project.md', {'name': 'alpha-project', 'source_episodes': [EP],
        sp.FIELD: sp.encode(rows)}, BODY)
    bank_index.invalidate()
    return tmp_path


def read(bank):
    return provenance.entity_provenance(bank, bank / 'entities' / 'alpha-project.md')


def test_payload_keeps_each_item_passage_and_reasoning_separate(bank):
    result = read(bank)
    assert result.page_body_hash == evidence.body_hash(BODY)
    summary, facts = result.sections
    assert (summary.key, summary.status, summary.item_count, summary.recorded_items) == ('summary', 'tracked', 1, 1)
    assert (facts.span_count, facts.reasoning_count, facts.recorded_items) == (2, 2, 2)
    assert result.totals.claims == result.totals.with_span == 0
    for section in result.sections:
        for row in section.items:
            assert ''.join(BODY[a:b] for a, b in row.body_ranges) == row.text
            exact, inferred = row.evidence
            assert exact.status == 'current' and exact.source_available
            assert exact.source_title == 'Synthetic conversation' and exact.conversation_id == 'session-example'
            assert exact.span.start == 6 and not exact.span.derived
            assert inferred.evidence.kind == 'reasoning' and inferred.span is None


def test_human_edit_changes_one_guard_and_counts_current_vs_unmatched(bank):
    path = bank / 'entities' / 'alpha-project.md'
    parsed = md.parse(path)
    md.write(path, parsed.frontmatter, parsed.body.replace('One fact.', 'Human edit.'))
    result = read(bank)
    facts = result.sections[1]
    assert facts.status == 'partial' and facts.recorded_items == facts.unmatched_records == 1
    assert not facts.items[0].evidence and len(facts.items[1].evidence) == 2
    assert result.page_body_hash != evidence.body_hash(BODY)


@pytest.mark.parametrize('body,status', [(SOURCE + '\nuser: Appended turn.', 'grown'), ('user: Rewritten source.', 'stale')])
def test_source_append_and_rewrite_never_mis_highlight(bank, body, status):
    path = bank / 'episodes' / f'{EP}.md'
    md.write(path, md.parse(path).frontmatter, body)
    bank_index.invalidate()
    row = read(bank).sections[0].items[0].evidence[0]
    assert row.status == status
    assert row.span.grown == (status == 'grown')
    assert (row.span.start is None) == (status == 'stale')


def test_missing_source_and_body_cap_keep_coordinates_as_metadata_without_wash(bank, monkeypatch):
    monkeypatch.setattr(provenance, 'MAX_PROVENANCE_CONVERSATIONS', 0)
    row = read(bank).sections[0].items[0].evidence[0]
    assert row.status == 'not_checked' and row.span is None
    assert row.evidence.start == 6 and row.source_available
    (bank / 'episodes' / f'{EP}.md').unlink()
    bank_index.invalidate()
    row = read(bank).sections[0].items[0].evidence[0]
    assert row.status == 'missing' and not row.source_available and row.span is None


def test_unreadable_claim_fence_makes_only_affected_trailing_section_unavailable(bank):
    path = bank / 'entities' / 'alpha-project.md'
    parsed = md.parse(path)
    md.write(path, parsed.frontmatter, parsed.body + '\n\n```claims\n- unknown: unfinished')
    summary, facts = read(bank).sections
    assert summary.status == 'tracked'
    assert facts.status == 'metadata_unavailable' and facts.recorded_items == 0
    assert all(not row.evidence for row in facts.items)


def test_invalid_schema_and_legacy_page_are_honest(bank):
    path = bank / 'entities' / 'alpha-project.md'
    parsed = md.parse(path)
    parsed.frontmatter[sp.FIELD]['v'] = 999
    md.write(path, parsed.frontmatter, parsed.body)
    assert all(s.status == 'metadata_unavailable' for s in read(bank).sections)
    parsed.frontmatter.pop(sp.FIELD)
    md.write(path, parsed.frontmatter, parsed.body)
    assert all(s.status == 'not_tracked' for s in read(bank).sections)


def test_section_response_overflow_is_honest_and_does_not_mutate_records(bank, monkeypatch):
    path = bank / 'entities' / 'alpha-project.md'
    before = path.read_bytes()
    monkeypatch.setattr(provenance, 'MAX_SECTION_RESPONSE_BYTES', 1)
    result = read(bank)
    assert result.sections_partial
    assert all(s.partial and not s.items for s in result.sections)
    assert result.sections[1].recorded_items == 2
    assert path.read_bytes() == before


def test_route_ship_together_camel_payload_etag_shape_and_conditional_get(bank, monkeypatch):
    monkeypatch.setenv('CICADA_MEMORY_PATH', str(bank))
    config.get_settings.cache_clear()
    try:
        with TestClient(main.app) as client:
            url = '/entities/alpha-project/provenance'
            first = client.get(url)
            assert first.status_code == 200, first.text
            data = first.json()
            assert data['pageBodyHash'] == evidence.body_hash(BODY) and data['sections'][0]['recordedItems'] == 1
            assert 'bodyRanges' in data['sections'][0]['items'][0]
            etag = first.headers['etag']
            assert client.get(url, headers={'If-None-Match': etag}).status_code == 304
            path = bank / 'entities' / 'alpha-project.md'
            parsed = md.parse(path)
            md.write(path, parsed.frontmatter, parsed.body + '\n- New human item.')
            response = client.get(url, headers={'If-None-Match': etag})
            assert response.status_code == 200 and response.headers['etag'] != etag
            assert response.json()['sections'][1]['status'] == 'partial'
    finally:
        config.get_settings.cache_clear()


def test_ambiguous_duplicate_items_have_distinct_server_row_identities(bank):
    path = bank / 'entities' / 'alpha-project.md'
    parsed = md.parse(path)
    md.write(path, parsed.frontmatter, parsed.body + '\n- One fact.')
    facts = read(bank).sections[1]
    assert len({item.identity for item in facts.items}) == len(facts.items)
    assert sum(item.ambiguous for item in facts.items) == 2
    assert all(not item.evidence for item in facts.items if item.ambiguous)
