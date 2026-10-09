"""G194 + #241: one batch's orientations are retained once, with exact guards."""
import asyncio
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from api.config import Settings
from api.services import conflict_resolver as cr, entity_body as eb, entity_resolver as er
from api.services import fact_policy, markdown_parser as md, section_provenance as sp


@pytest.mark.parametrize('update, enabled', [(False, False), (True, False), (True, True)])
@pytest.mark.parametrize('oversized', [False, True])
@pytest.mark.parametrize('already_fact', [False, True])
def test_25_same_name_mentions_retain_each_orientation_once(tmp_path, monkeypatch, update, enabled, oversized, already_fact):
    for directory in ('entities', 'episodes', 'inbox'):
        (tmp_path / directory).mkdir()
    monkeypatch.setenv('CICADA_MEMORY_PATH', str(tmp_path))
    monkeypatch.setattr(er, 'SqliteVecIndexer', lambda *args, **kwargs: None)
    async def no_call(*args, **kwargs):
        raise AssertionError('default bounded merge must not add model calls')
    monkeypatch.setattr(er, '_llm_judge_same_entity', no_call)
    monkeypatch.setattr(cr.litellm, 'acompletion', no_call)
    settings = Settings(_env_file=None, summary_synthesis_enabled=enabled)
    extracted = []
    for n in range(1, 26):
        day = f'{2024 + (n - 1) // 12}-{(n - 1) % 12 + 1:02d}-15'
        episode = f'ep_{day}_001'
        summary = f'alpha-project evaluated orientation-{n:02d}.'
        if oversized and n == 1:
            summary += ' Additional design context.' * 40
        entity = {'name': 'alpha-project', 'type': 'project', 'confidence': 0.9 if n == 1 else 0.8,
                  'summary': summary, 'key_facts': [f'Atomic observation-{n:02d}.'],
                  'source_episode': episode, 'source_episode_timestamp': day + 'T12:00:00Z',
                  'source_episode_day': day}
        if already_fact:
            entity['key_facts'].append(summary)
        sp.attach(entity, episode, f'user: {summary} Atomic observation-{n:02d}.')
        extracted.append({'episode_id': episode, 'episode_timestamp': day + 'T12:00:00Z',
                          'entities': [entity], 'relationships': [], 'body': 'user: Synthetic observation.'})

    calls = []
    if enabled:
        async def choose_carried(**kwargs):
            prompt = kwargs['messages'][-1]['content']
            calls.append(prompt)
            result = ({'summary': extracted[21]['entities'][0]['summary']}
                      if 'SECTION-AWARE ORIENTATION' in prompt else {'has_unresolvable_contradiction': False})
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(result)))])
        monkeypatch.setattr(cr.litellm, 'acompletion', choose_carried)

    path = tmp_path / 'entities/alpha-project.md'
    existing = []
    old_episode = 'ep_2023-01-15_001'
    fence = '```claims\n- id: old-closed\n  text: Historical belief.\n  valid_to: 2023-02-01\n```'
    if update:
        # This orientation will also arrive as a carried Key Fact from #241.
        original = {'name': 'alpha-project', 'type': 'project',
                    'summary': extracted[1]['entities'][0]['summary'], 'key_facts': ['Existing atomic fact.']}
        sp.attach(original, old_episode, 'user: Synthetic prior context.')
        cr.apply_changes([{'id': 'alpha-project', 'action': 'create', 'entity': original,
                           'source_episode': old_episode,
                           'source_episode_timestamp': '2023-01-15T12:00:00Z'}], tmp_path)
        page = md.parse(path)
        md.write(path, page.frontmatter, page.body + '\n' + fence)
        existing = [{'id': path.stem, 'frontmatter': page.frontmatter, 'body': page.body + '\n' + fence}]

    result = asyncio.run(er.resolve(extracted, existing, settings))
    assert len(result['changes']) == 1
    changes = asyncio.run(cr.resolve_and_prune(result['changes'], existing, settings, decay=False,
                                               now=datetime(2026, 10, 8)))
    cr.apply_changes(changes, tmp_path)
    page = md.parse(path)
    sections = eb.parse_sections(page.body)
    assert len(sections['Summary']) <= 600 and '\n\n' not in sections['Summary']
    visible = page.body.replace('\n  ', '\n')
    matched = sp.matched(page.frontmatter, page.body)
    scan = sp.scan(page.body)
    for n, entry in enumerate(extracted, 1):
        entity = entry['entities'][0]
        orientation = entity['summary']
        # Every sentence of every orientation is on the page, and the one that names it once.
        sentences = fact_policy.sentences(orientation)
        assert all(sentence in visible for sentence in sentences)
        assert visible.count(sentences[0]) == 1, sentences[0]
        assert f'Atomic observation-{n:02d}.' in sections['Key Facts']
        # Every retained exact orientation in Summary/Key Facts keeps its own
        # input episode. Undated History is intentionally uninstrumented.
        for title in ('summary', 'key_facts'):
            for item in scan.get(title, []):
                if item.text == orientation:
                    rows = matched[title][item.key][1]
                    assert entity['source_episode'] in {row.episode for row in rows}
                    assert all(row.kind == 'reasoning' for row in rows)
    expected = {e['episode_id'] for e in extracted} | ({old_episode} if update else set())
    assert set(page.frontmatter['source_episodes']) == expected
    assert str(page.frontmatter['last_referenced']) == '2026-01-15'
    assert not matched.get('history')
    if not update and not oversized:
        assert sections['Summary'] == extracted[0]['entities'][0]['summary']
        orientations = {e['entities'][0]['summary'] for e in extracted}
        assert sum(i.text in orientations for i in scan['key_facts']) == 24
    assert len(calls) == (2 if enabled else 0)
    if enabled:
        assert sections['Summary'] == extracted[21]['entities'][0]['summary']
        item = next(i for i in scan['key_facts'] if i.text == extracted[1]['entities'][0]['summary'])
        assert {ev.episode for ev in matched['key_facts'][item.key][1]} == {
            old_episode, extracted[1]['episode_id']}, 'the old exact guard must follow Summary-to-fact carry'
    if update:
        assert fence in page.body and 'Existing atomic fact.' in sections['Key Facts']
    # Replaying the same committed change does not create carry duplicates or
    # multiply evidence rows (metadata and prose both remain identical).
    before = page.body, page.frontmatter.get(sp.FIELD), page.frontmatter['source_episodes']
    cr.apply_changes(changes, tmp_path)
    again = md.parse(path)
    assert (again.body, again.frontmatter.get(sp.FIELD), again.frontmatter['source_episodes']) == before


def test_25_identical_summaries_union_sources_without_fact_or_history_copies(tmp_path, monkeypatch):
    for directory in ('entities', 'episodes', 'inbox'):
        (tmp_path / directory).mkdir()
    monkeypatch.setenv('CICADA_MEMORY_PATH', str(tmp_path))
    monkeypatch.setattr(er, 'SqliteVecIndexer', lambda *args, **kwargs: None)
    settings = Settings(_env_file=None, summary_synthesis_enabled=False)
    summary = 'alpha-project is a local notes application.'
    extracted = []
    for n in range(1, 26):
        episode = f'ep_2026-01-15_{n:03d}'
        entity = {'name': 'alpha-project', 'type': 'project', 'summary': summary,
                  'key_facts': [summary], 'confidence': 0.8, 'source_episode': episode,
                  'source_episode_timestamp': '2026-01-15T12:00:00Z'}
        sp.attach(entity, episode, 'user: Synthetic repeated context.')
        extracted.append({'episode_id': episode, 'entities': [entity], 'relationships': []})
    result = asyncio.run(er.resolve(extracted, [], settings))
    assert len(result['changes']) == 1
    cr.apply_changes(result['changes'], tmp_path)
    page = md.parse(tmp_path / 'entities/alpha-project.md')
    assert page.body.count(summary) == 1
    assert '## Key Facts' not in page.body and '## History' not in page.body
    rows = next(iter(sp.matched(page.frontmatter, page.body)['summary'].values()))[1]
    assert len(rows) == 25 and {ev.episode for ev in rows} == {e['episode_id'] for e in extracted}


def test_opt_in_orientation_can_select_an_incoming_carried_fact_once(tmp_path, monkeypatch):
    (tmp_path / 'entities').mkdir()
    monkeypatch.setenv('CICADA_MEMORY_PATH', str(tmp_path))
    page_path = tmp_path / 'entities/alpha-project.md'
    md.write(page_path, {'name': 'alpha-project', 'type': 'project'},
             '## Summary\nA notes prototype.\n\n## Key Facts\n- Existing fact.')
    fields = {'summary': 'New orientation.', 'key_facts': ['A desktop notes application.']}
    episode = 'ep_2026-01-15_001'
    sp.attach(fields, episode, 'user: Synthetic desktop context.')
    # Real shared composer, with the synthetic engine's chosen Summary.
    from api.services import entity_orientation
    current = md.parse(page_path)
    candidate = entity_orientation.compose(current.body, fields, fields['key_facts'][0])
    change = {'id': 'alpha-project', 'action': 'update', 'entity': fields,
              'synthesized_body': candidate, 'section_aware_synthesis': True, 'source_episode': episode}
    cr.apply_changes([change], tmp_path)
    page = md.parse(page_path)
    assert page.body.count('A desktop notes application.') == 1
    assert 'Existing fact.' in page.body and 'New orientation.' in page.body and 'A notes prototype.' in page.body
    matched = sp.matched(page.frontmatter, page.body)
    rows = next(iter(matched['summary'].values()))[1]
    assert {ev.episode for ev in rows} == {episode}


@pytest.mark.parametrize('indented', [False, True])
def test_selection_keeps_multiline_content_without_certifying_changed_format(tmp_path, indented):
    (tmp_path / 'entities').mkdir()
    fact = 'A detailed fact.\n' + ('  ' if indented else '') + 'Further context.'
    fields = {'name': 'alpha-project', 'type': 'project', 'summary': 'A notes project.', 'key_facts': [fact]}
    episode = 'ep_2026-01-15_001'
    sp.attach(fields, episode, 'user: Synthetic detailed context.')
    cr.apply_changes([{'id': 'alpha-project', 'action': 'create', 'entity': fields}], tmp_path)
    page = md.parse(tmp_path / 'entities/alpha-project.md')
    [item] = sp.scan(page.body)['key_facts']
    assert item.text.replace('\n  ', '\n') == fact.replace('\n  ', '\n')
    matched = sp.matched(page.frontmatter, page.body)
    if indented:
        assert {ev.episode for ev in matched['key_facts'][item.key][1]} == {episode}
    else:
        assert not matched.get('key_facts'), 'changed whitespace must not invent an exact guard'
    original = page.body
    cr.apply_changes([{'id': 'alpha-project', 'action': 'update', 'entity': {'key_facts': [fact]}}], tmp_path)
    assert md.parse(tmp_path / 'entities/alpha-project.md').body == original


def test_existing_human_fact_matching_summary_is_not_removed():
    summary = 'The owner chose this prose. ' * 50
    existing = {'Summary': summary, 'Key Facts': '- ' + summary.strip(), 'Personal Notes': 'Keep this exact.'}
    merged = eb.merge_sections_human_safe(existing, {'key_facts': [summary]}, human_edited=True)
    assert merged == existing


def test_malformed_incoming_metadata_cannot_block_or_recategorize_stale_guards(tmp_path):
    (tmp_path / 'entities').mkdir()
    fields = {'name': 'alpha-project', 'type': 'project', 'summary': 'Original orientation.'}
    sp.attach(fields, 'ep_2024-01-15_001', 'user: Synthetic original context.')
    cr.apply_changes([{'id': 'alpha-project', 'action': 'create', 'entity': fields}], tmp_path)
    cr.apply_changes([{'id': 'alpha-project', 'action': 'update',
                      'entity': {'key_facts': ['New atomic fact.'], sp.INPUTS: 'opaque'}}], tmp_path)
    page = md.parse(tmp_path / 'entities/alpha-project.md')
    assert 'New atomic fact.' in page.body
    matched = sp.matched(page.frontmatter, page.body)
    assert not matched.get('key_facts')
    assert {ev.episode for _, rows in matched['summary'].values() for ev in rows} == {'ep_2024-01-15_001'}
