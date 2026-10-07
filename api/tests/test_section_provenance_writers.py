"""No paid prompt growth: extraction reasoning → selected payload → owned write."""
import asyncio
from types import SimpleNamespace
import json

import pytest

from api.config import Settings
from api.services import conflict_resolver as cr, entity_extractor as ex, entity_resolver as er
from api.services import evidence, markdown_parser as md, provenance, section_provenance as sp

A, B = 'ep_2026-10-07_001', 'ep_2026-10-07_002'


@pytest.fixture(autouse=True)
def bank_dirs(tmp_path):
    (tmp_path / 'entities').mkdir()
    (tmp_path / 'episodes').mkdir()


def entity(summary='Example project.', facts=None, *, ep=A, description=''):
    value = {'name': 'alpha-project', 'type': 'project', 'summary': summary, 'description': description,
             'key_facts': facts or ['Original fact.'], 'confidence': .9, 'source_episode': ep}
    sp.attach(value, ep, 'user: Synthetic conversation for ' + ep)
    return value


def page(memory):
    return md.parse(memory / 'entities' / 'alpha-project.md')


def links(parsed):
    return sp.matched(parsed.frontmatter, parsed.body)


def test_extraction_records_reasoning_from_full_body_without_more_calls_or_prompt_changes(monkeypatch):
    seen = []
    async def fake(**kwargs):
        seen.append(kwargs['messages'])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({
            'entities': [{'name': 'alpha-project', 'type': 'project', 'summary': 'Inferred Summary.',
                          'key_facts': ['Inferred fact.'], sp.INPUTS: [{'forged': True}]}], 'relationships': []})))])
    monkeypatch.setattr(ex.litellm, 'acompletion', fake)
    body = 'user: A synthetic conversation 🐝.'
    [result] = asyncio.run(ex.extract([{'id': A, 'content': body, 'origin': 'synthetic'}], Settings(_env_file=None, litellm_model='m')))
    assert len(seen) == 1
    assert seen[0][0]['content'] == ex.EXTRACTION_SYSTEM_PROMPT
    assert seen[0][1]['content'].endswith(body)
    records = result['entities'][0][sp.INPUTS]
    assert [x['field'] for x in records] == ['summary', 'key_facts']
    assert all(x['evidence'] == [evidence.reasoning(A, hash=evidence.body_hash(body)).to_dict()] for x in records)


def test_stage2_tracks_selected_description_and_base_summary_facts_only():
    base = entity(description='Short.')
    incoming = entity('Incoming Summary.', ['Dropped incoming fact.'], ep=B, description='Longer new description.')
    merged = er._merge_entity_payload(base, incoming)
    assert merged['key_facts'] == ['Original fact.']
    assert merged['summary'] == 'Example project.'
    assert merged['description'] == 'Longer new description.'
    assert {(r['field'], r['evidence'][0]['episode']) for r in merged[sp.INPUTS]} == {
        ('summary', A), ('key_facts', A), ('description', B)}


@pytest.mark.parametrize('human', [False, True])
def test_a_create_b_fact_only_update_keeps_a_summary_precondition(tmp_path, human):
    cr.apply_changes([{'id': 'alpha-project', 'action': 'create', 'entity': entity()}], tmp_path)
    p = page(tmp_path)
    if human:
        p.frontmatter['human_edited'] = True
        md.write(tmp_path / 'entities' / 'alpha-project.md', p.frontmatter, p.body)
    update = entity('', ['New fact.'], ep=B)
    assert not cr._entity_summary(update), 'B must carry no new Summary, critique finding 3'
    cr.apply_changes([{'id': 'alpha-project', 'action': 'update', 'entity': update}], tmp_path)
    matched = links(page(tmp_path))
    assert len(matched['summary']) == 1 and len(matched['key_facts']) == 2
    assert {ev.episode for _, evs in matched['summary'].values() for ev in evs} == {A}
    assert {ev.episode for _, evs in matched['key_facts'].values() for ev in evs} == {A, B}


def test_b_new_summary_invalidates_only_summary_while_a_facts_stay(tmp_path):
    cr.apply_changes([{'id': 'alpha-project', 'action': 'create', 'entity': entity()}], tmp_path)
    cr.apply_changes([{'id': 'alpha-project', 'action': 'update', 'entity': entity('Different Summary.', ['New fact.'], ep=B)}], tmp_path)
    p = page(tmp_path)
    assert 'Different Summary.' in p.body
    assert not links(p).get('summary')
    assert len(links(p)['key_facts']) == 2
    summary, facts = provenance.entity_provenance(tmp_path, tmp_path / 'entities' / 'alpha-project.md').sections
    assert summary.recorded_items == summary.reasoning_count == 0
    assert facts.recorded_items == facts.reasoning_count == 2


def test_synthesis_carries_exact_items_but_not_unseen_incoming_facts(tmp_path):
    cr.apply_changes([{'id': 'alpha-project', 'action': 'create', 'entity': entity(facts=['One.', 'Two.', 'Three.'])}], tmp_path)
    cr.apply_changes([{'id': 'alpha-project', 'action': 'update',
        'entity': entity('Not supplied to synthesis.', ['Unseen incoming.'], ep=B, description='New description.'),
        'synthesized_body': '## Summary\nExample project.\n\n## Key Facts\n- One.\n- Two.\n- Rephrased three.\n- Unseen incoming.'}], tmp_path)
    matched = links(page(tmp_path))
    assert len(matched['summary']) == 1
    assert len(matched['key_facts']) == 2
    assert all(ev.episode == A for _, evs in matched['key_facts'].values() for ev in evs)


def test_legacy_pending_style_input_does_not_get_fabricated_links(tmp_path):
    cr.apply_changes([{'id': 'alpha-project', 'action': 'create', 'entity': {'name': 'alpha-project',
        'description': 'Older pending description.', 'history_entries': [], 'source_episode': A}}], tmp_path)
    assert sp.FIELD not in page(tmp_path).frontmatter


def test_raw_claim_fence_and_atomic_failure_keep_body_metadata_together(tmp_path, monkeypatch):
    cr.apply_changes([{'id': 'alpha-project', 'action': 'create', 'entity': entity()}], tmp_path)
    path = tmp_path / 'entities' / 'alpha-project.md'
    p = page(tmp_path)
    fence = '```claims\n- future: field\n  unreadable: [\n```'
    md.write(path, p.frontmatter, p.body + '\n\n' + fence)
    before = path.read_bytes()
    def fail(*args):
        raise OSError('synthetic replace failure')
    with monkeypatch.context() as patch:
        patch.setattr(md, '_replace', fail)
        with pytest.raises(OSError):
            cr.apply_changes([{'id': 'alpha-project', 'action': 'update', 'entity': entity('', ['New fact.'], ep=B)}], tmp_path)
    assert path.read_bytes() == before
    cr.apply_changes([{'id': 'alpha-project', 'action': 'update', 'entity': entity('', ['New fact.'], ep=B)}], tmp_path)
    assert fence in page(tmp_path).body
