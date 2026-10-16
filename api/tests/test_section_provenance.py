"""Item identity/compact storage on synthetic, human-editable pages (G118)."""
import pytest
import yaml

from api.services import section_provenance as sp
from api.services.claims import Evidence

EP = 'ep_2026-10-07_001'


def recorded(body, kind='reasoning'):
    ev = Evidence(episode=EP, hash='123456abcdef', kind=kind)
    if kind != 'reasoning':
        ev.start, ev.end = 1, 9
    return sp.encode({key: {item.key: (item.text_hash, [ev]) for item in items if not item.ambiguous}
                      for key, items in sp.scan(body).items()})


def test_scalar_round_trip_all_six_kinds_and_source_revisions():
    evs = [Evidence(episode=EP, hash=f'{i:012x}', kind=k, start=-1 if k == 'reasoning' else i,
                    end=-1 if k == 'reasoning' else i + 1)
           for i, k in enumerate(('user', 'assistant', 'page', 'reasoning', 'speaker', 'media'))]
    raw = sp.encode({'key_facts': {'123456abcdef': ('abcdef123456', evs + evs)}})
    assert all(isinstance(v, str) for v in raw['sources'].values())
    assert all(isinstance(v, str) for v in raw['sections']['key_facts'].values())
    loaded = yaml.safe_load(yaml.dump(raw, default_flow_style=False, sort_keys=False))
    guard, actual = sp.decode(loaded)['key_facts']['123456abcdef']
    assert guard == 'abcdef123456'
    assert actual == evs


@pytest.mark.parametrize('raw', [None, [], {'v': 2}, {'v': 1, 'sources': {}, 'sections': {'history': {'bad': 'bad'}}},
    {'v': 1, 'sources': {'s0': '../escape 123456abcdef'}, 'sections': {}},
    {'v': 1, 'sources': {'s0': EP + ' 123456abcdef'}, 'sections': {
        'summary': {'123456abcdef': 'abcdef123456 s0:-1:-1:d'}}}])
def test_unknown_malformed_or_derived_storage_fails_closed(raw):
    assert sp.decode(raw) is None


def test_one_typo_in_120_bullets_leaves_119_links_and_reorder_keeps_them():
    body = '## History\n' + '\n'.join(f'- Synthetic observation {i}.' for i in range(120))
    fm = {'section_provenance': recorded(body)}
    changed = body.replace('observation 60.', 'observation sixty.')
    matched = sp.matched(fm, changed)
    assert len(matched['history']) == 119
    reordered = '## History\n' + '\n'.join(reversed(body.splitlines()[1:]))
    assert len(sp.matched(fm, reordered)['history']) == 120
    assert len(sp.matched(fm, body + '\n- New human item.')['history']) == 120


def test_normalized_key_is_only_lookup_exact_guard_prevents_recertifying_edits():
    body = '## Key Facts\n- Uses [[alpha-project]].'
    fm = {'section_provenance': recorded(body)}
    for changed in ('## Key Facts\n- Uses alpha-project.', '## Key Facts\n- uses [[alpha-project]].'):
        assert sp.matched(fm, changed).get('key_facts', {}) == {}


def test_duplicate_bullets_are_ambiguous_and_continuations_belong_to_their_item():
    body = '## Key Facts\n- One item.\n  Its continuation.\n  - Nested detail.\n- Repeated.\n- Repeated.'
    items = sp.scan(body)['key_facts']
    assert len(items) == 3
    assert items[0].text == 'One item.\n  Its continuation.\n  - Nested detail.'
    assert [x.ambiguous for x in items] == [False, True, True]
    assert body[items[0].ranges[0][0]:items[0].ranges[0][1]] == items[0].text


def test_code_and_claim_fences_are_never_items_and_ranges_index_unicode_body():
    body = '## Key Facts\n- Emoji 🐝 fact.\n\n```text\n## History\n- Not an item.\n```\n\n```claims\n[]\n```'
    items = sp.scan(body)
    assert list(items) == ['key_facts']
    assert len(items['key_facts']) == 1
    item = items['key_facts'][0]
    assert body[item.ranges[0][0]:item.ranges[0][1]] == 'Emoji 🐝 fact.'


def test_duplicate_summary_headings_accumulate_but_ranges_exclude_headings():
    body = '## Summary\nFirst.\n\n## Key Facts\n- Fact.\n\n## Summary\nSecond.'
    [item] = sp.scan(body)['summary']
    assert item.text == 'First.\nSecond.'
    assert [body[a:b] for a, b in item.ranges] == ['First.', 'Second.']


def test_refresh_prunes_changed_items_without_resurrecting_unmatched_old_records():
    old = '## Key Facts\n- Original.\n- Stable.'
    edited = old.replace('Original.', 'Human edit.')
    fm = {'section_provenance': recorded(old)}
    sp.refresh(fm, edited, old, {})
    assert len(sp.matched(fm, old)['key_facts']) == 1


def test_refresh_preserves_unknown_schema_fields_and_unknown_version():
    body = '## Summary\nExample.'
    fm = {'section_provenance': recorded(body)}
    fm['section_provenance']['future'] = {'keep': True}
    sp.refresh(fm, body, body, {})
    assert fm['section_provenance']['future'] == {'keep': True}
    fm['section_provenance']['v'] = 2
    before = dict(fm['section_provenance'])
    sp.refresh(fm, body, body, {})
    assert fm['section_provenance'] == before


def test_unreadable_fence_uses_actual_last_heading_not_dictionary_insertion_order():
    body = '## Summary\nFirst.\n\n## Key Facts\n- Stable.\n\n## Summary\nSecond.\n\n```claims\nunfinished'
    assert sp.unavailable_section(body) == 'summary'
    custom = '## Summary\nFirst.\n\n## Custom Notes\nHuman note.\n\n```claims\nunfinished'
    assert sp.unavailable_section(custom) is None


@pytest.mark.parametrize('fences', ['```claims\ninvalid: [\n```', '```claims\n[]\n```\n\n```claims\n[]\n```'])
def test_closed_claim_fences_keep_prose_links_on_read_and_refresh(fences):
    body = '## Summary\nExample.\n\n## Key Facts\n- One.\n- Two.'
    fm = {sp.FIELD: recorded(body)}
    before = sp.decode(fm[sp.FIELD])
    body += '\n\n' + fences
    assert sp.unavailable_section(body) is None
    assert sp.matched(fm, body) == before
    sp.refresh(fm, body, body, {})
    assert sp.decode(fm[sp.FIELD]) == before


@pytest.mark.parametrize('opening', ['summary', 'custom', 'before_headings'])
@pytest.mark.parametrize('fence', ['```claims', '```text', '~~~python'])
def test_open_fence_keeps_hidden_records_and_repair_restores_exact_links(opening, fence):
    body = '## Summary\nExample.\n\n## Key Facts\n- One.\n- Two.'
    fm = {sp.FIELD: recorded(body)}
    before = sp.decode(fm[sp.FIELD])
    if opening == 'before_headings':
        broken = fence + '\nunfinished\n' + body
    else:
        prefix = '\n\n## Custom Notes\nHuman note.' if opening == 'custom' else ''
        broken = body.replace('\n\n## Key Facts', prefix + '\n\n' + fence + '\nunfinished\n\n## Key Facts')
    sp.refresh(fm, broken, broken, {})
    assert sp.decode(fm[sp.FIELD]) == before
    # Repair without changing the original prose: remove the unfinished snippet.
    repaired = broken.replace(fence + '\nunfinished\n', '')
    assert sp.matched(fm, repaired) == before
    # Closing a non-claims snippet changes Summary text but reveals the unchanged facts.
    closed = broken.replace(fence + '\nunfinished', fence + '\nunfinished\n' + fence[:3])
    assert sp.matched(fm, closed)['key_facts'] == before['key_facts']
    # A writer must also preserve what the original body hid when its output is readable.
    sp.refresh(fm, broken, repaired, {})
    assert sp.matched(fm, repaired) == before
    edited = repaired.replace('- One.', '- Human edit.')
    assert len(sp.matched(fm, edited)['key_facts']) == 1


def test_attach_does_not_iterate_string_key_facts_per_character():
    entity = {'summary': 'Example.', 'key_facts': 'One malformed fact.'}
    sp.attach(entity, EP, 'user: Synthetic source.')
    assert [row['field'] for row in entity[sp.INPUTS]] == ['summary']


def test_selected_carry_unions_evidence_rows_without_collapsing_source_revisions_or_spans():
    text = 'Synthetic fact.'
    rows = [Evidence(episode=EP, hash='123456abcdef', kind='reasoning').to_dict(),
            Evidence(episode=EP, hash='abcdef123456', kind='reasoning').to_dict(),
            Evidence(episode=EP, hash='123456abcdef', kind='user', start=1, end=9).to_dict(),
            Evidence(episode=EP, hash='123456abcdef', kind='user', start=10, end=19).to_dict()]
    base = {sp.INPUTS: [{'field': 'summary', 'text': text, 'evidence': rows[:2] + rows[:1]},
                       {'field': 'description', 'text': text, 'evidence': rows}]}
    incoming = {sp.INPUTS: [{'field': 'key_facts', 'text': text, 'evidence': rows}]}
    selected = {'summary': text, 'description': text, 'key_facts': [text, text]}
    merged = sp.merge_selected(base, incoming, selected)
    assert len(merged) == 3
    assert [record['field'] for record in merged] == ['summary', 'description', 'key_facts']
    assert all(record['evidence'] == rows for record in merged)
