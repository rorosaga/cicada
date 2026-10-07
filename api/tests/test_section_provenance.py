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
