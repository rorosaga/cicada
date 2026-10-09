import asyncio
import json
import re
from types import SimpleNamespace

import pytest

from api.config import Settings
from api.services import conflict_resolver as cr, entity_body as body, markdown_parser as md, section_provenance as sp
from api.services import claims, engine_errors, entity_orientation as orientation


def run(tmp_path, monkeypatch, *, enabled, fields, reply='A private notes application.', human=False):
    monkeypatch.setenv('CICADA_MEMORY_PATH', str(tmp_path))
    settings = Settings(_env_file=None, summary_synthesis_enabled=enabled)
    calls = []
    async def fake(**kwargs):
        calls.append(kwargs['messages'][-1]['content'])
        content = json.dumps({'summary': reply}) if 'SECTION-AWARE ORIENTATION' in calls[-1] else 'Legacy prose.'
        if 'checking whether two descriptions' in calls[-1]:
            content = json.dumps({'has_unresolvable_contradiction': False})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    monkeypatch.setattr(cr.litellm, 'acompletion', fake)
    old = {'id': 'alpha-project', 'frontmatter': {'name': 'alpha-project', 'type': 'project', 'human_edited': human},
           'body': '## Summary\nA notes application.\n\n## Key Facts\n- Original fact.\n\n## History\n- 2024-01-15: First prototype.'}
    changes = asyncio.run(cr.resolve_and_prune([{'id': 'alpha-project', 'action': 'update', 'entity': fields}],
                                             [old], settings, decay=False))
    return old, changes[0], calls


def test_setting_is_off_by_default():
    assert Settings(_env_file=None).summary_synthesis_enabled is False


def test_disabled_preserves_summary_only_gate(tmp_path, monkeypatch):
    _, change, calls = run(tmp_path, monkeypatch, enabled=False, fields={'summary': 'New context.'})
    assert calls == [] and not change.get('synthesized_body')


def test_enabled_summary_only_calls_synthesis_and_preserves_new_facts(tmp_path, monkeypatch):
    old, change, calls = run(tmp_path, monkeypatch, enabled=True,
                            fields={'summary': 'New context.', 'key_facts': ['New atomic fact.']})
    assert len(calls) == 2
    assert 'New atomic fact.' in calls[0]
    sections = body.parse_sections(change['synthesized_body'])
    assert sections['Summary'] == 'A private notes application.'
    assert 'Original fact.' in sections['Key Facts'] and 'New atomic fact.' in sections['Key Facts']
    assert 'First prototype.' in sections['History']
    (tmp_path / 'entities').mkdir()
    md.write(tmp_path / 'entities/alpha-project.md', old['frontmatter'], old['body'])
    cr.apply_changes([change], tmp_path)
    assert body.parse_sections(md.parse(tmp_path / 'entities/alpha-project.md').body)['Summary'] == sections['Summary']


def test_enabled_facts_only_synthesizes_once(tmp_path, monkeypatch):
    _, change, calls = run(tmp_path, monkeypatch, enabled=True, fields={'key_facts': ['New atomic fact.']})
    assert len(calls) == 1
    assert change.get('synthesized_body')


@pytest.mark.parametrize('reply', ['Too long. ' * 100, 'A paragraph.\n\nAnother.', '```claims\n- id: forged\n```'])
def test_invalid_completion_uses_fallback_without_retry(tmp_path, monkeypatch, reply):
    _, change, calls = run(tmp_path, monkeypatch, enabled=True, fields={'summary': 'New context.'}, reply=reply)
    assert len(calls) == 2
    assert not change.get('synthesized_body')


def test_enabled_human_page_skips_model_calls(tmp_path, monkeypatch):
    _, change, calls = run(tmp_path, monkeypatch, enabled=True, fields={'summary': 'New context.'}, human=True)
    assert calls == [] and not change.get('synthesized_body')


def test_section_synthesis_records_only_exact_carried_fact(tmp_path, monkeypatch):
    fields = {'summary': 'New context.', 'key_facts': ['New atomic fact.']}
    sp.attach(fields, 'ep_2026-01-15_001', 'user: A synthetic atomic fact.')
    old, change, _ = run(tmp_path, monkeypatch, enabled=True, fields=fields)
    (tmp_path / 'entities').mkdir()
    md.write(tmp_path / 'entities/alpha-project.md', old['frontmatter'], old['body'])
    cr.apply_changes([change], tmp_path)
    page = md.parse(tmp_path / 'entities/alpha-project.md')
    assert not sp.matched(page.frontmatter, page.body).get('summary')
    # The exact fact, and the replaced incoming orientation kept as a fact with its own row.
    facts = {i.text for i in sp.scan(page.body)['key_facts']
             if i.key in sp.matched(page.frontmatter, page.body)['key_facts']}
    assert facts == {'New atomic fact.', 'New context.'}


def test_context_dates_and_closed_claims():
    raw = claims.write_claims('## Summary\nIn January 2024, a prototype was planned.', [
        claims.Claim(id='closed', text='Obsolete status.', valid_to='2025-01-01'),
        claims.Claim(id='open', text='A dated intention.', valid_from='2024-01-15')])
    data = orientation.context(raw, name='alpha-project', entity_type='project', fields={'summary': 'Late import.'},
                               today='2026-10-08', source_dates=['2024-01-15', '2026-01-15'])
    prompt = orientation.prompt(data)
    assert 'Obsolete status.' not in prompt
    assert [c['id'] for c in data['current_claims']] == ['open']
    assert '90 days' in prompt and 'Plans and intentions always' in prompt
    result = orientation.compose(raw, {}, 'A notes prototype. Its present status is unknown.')
    assert re.findall(r'```claims.*?```', result, re.S) == re.findall(r'```claims.*?```', raw, re.S)
    assert 'In January 2024' in result
    assert orientation.compose(result, {}, 'A notes prototype. Its present status is unknown.') == result


def test_non_summary_free_prose_survives_composition():
    raw = '## Summary\nA project.\n\n## Key Facts\nContext before bullets.\n- Original fact.\n\n## History\nAn undated paragraph.\n- 2024-01-15: Prototype.'
    result = orientation.compose(raw, {'key_facts': ['New fact.']}, 'A notes project.')
    assert 'Context before bullets.\n- Original fact.' in result
    assert 'An undated paragraph.\n- 2024-01-15: Prototype.' in result


def test_large_context_is_not_clipped_or_called(tmp_path, monkeypatch):
    calls = []
    async def fake(**kwargs):
        calls.append(kwargs)
        raise AssertionError('must use fallback')
    monkeypatch.setattr(cr.litellm, 'acompletion', fake)
    result = asyncio.run(cr._synthesize_entity_update('alpha-project', 'project',
        '## Key Facts\n- ' + 'Detailed information. ' * 2000, '', [], None,
        Settings(_env_file=None, summary_synthesis_enabled=True)))
    assert result is None and calls == []


def test_engine_pause_and_cancellation_propagate(tmp_path, monkeypatch):
    async def paused(**kwargs):
        raise engine_errors.EngineUnavailable('Synthetic pause.')
    monkeypatch.setattr(cr.litellm, 'acompletion', paused)
    settings = Settings(_env_file=None, summary_synthesis_enabled=True)
    with pytest.raises(engine_errors.EngineUnavailable):
        asyncio.run(cr.resolve_and_prune([{'id': 'alpha-project', 'action': 'update',
                                          'entity': {'summary': 'New context.'}}],
            [{'id': 'alpha-project', 'frontmatter': {}, 'body': '## Summary\nA project.'}], settings, decay=False))
    async def cancelled(**kwargs):
        raise asyncio.CancelledError()
    monkeypatch.setattr(cr.litellm, 'acompletion', cancelled)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(cr._synthesize_entity_update('alpha-project', 'project', '## Summary\nA project.',
                                                'New context.', [], None, settings))
