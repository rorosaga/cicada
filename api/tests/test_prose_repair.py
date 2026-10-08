"""Synthetic candidate generation: never read or mutate an owner bank."""
import json
from pathlib import Path
import subprocess

import pytest

from api.services import claims, markdown_parser as md, prose_repair as repair


@pytest.fixture
def bank(tmp_path):
    bank = tmp_path / 'bank'
    (bank / 'entities').mkdir(parents=True)
    (bank / 'episodes').mkdir()
    md.write(bank / 'episodes/ep_2024-01-15_001.md', {'timestamp': '2024-01-15T12:00:00Z'},
             'user: Planned a local notes prototype.')
    raw = claims.write_claims('## Summary\nA local notes project.\n\n## Key Facts\n- Planned a local notes prototype.',
                             [claims.Claim(id='closed', text='An obsolete belief.', valid_to='2024-02-01')])
    md.write(bank / 'entities/alpha-project.md', {'name': 'alpha-project', 'type': 'project',
             'source_episodes': ['ep_2024-01-15_001']}, raw)
    return bank


def snapshot(bank):
    return {str(p.relative_to(bank)): p.read_bytes() for p in bank.rglob('*') if p.is_file()}


def fake(calls, *, edit=False, bad=False):
    def completion(**kw):
        calls.append(kw['messages'][-1]['content'])
        data = json.loads(calls[-1].partition('\nINPUT:\n')[2])
        edits = []
        if edit:
            item = data['items'][0]
            edits = [{'id': item['id'], 'source_id': data['sources'][0]['id'],
                      'text': '2024-01-15: ' + item['text']}]
        return {'choices': [{'message': {'content': 'bad json' if bad else json.dumps({
            'summary': 'In January 2024, a notes prototype was planned. Its present status is unknown.',
            'dated_edits': edits})}}]}
    return completion


def test_inventory_and_generation_leave_bank_byte_identical(bank, tmp_path):
    before = snapshot(bank)
    calls = []
    result = repair.run(bank, tmp_path / 'inventory', llm_fn=fake(calls))
    assert calls == [] and result['calls'] == 0
    assert result['pages'][0]['status'] == 'eligible'
    result = repair.run(bank, tmp_path / 'candidates', generate=True, llm_fn=fake(calls, edit=True),
                        max_calls=1, token_budget=10000, today='2026-10-08', engine_id='fake-v1')
    assert result['calls'] == 1 and result['pages'][0]['status'] == 'candidate'
    candidate = json.loads(Path(result['pages'][0]['candidate']).read_text())
    assert '2024-01-15: Planned a local notes prototype.' in candidate['body']
    assert claims.raw_claim_entries(candidate['body']) == claims.raw_claim_entries(md.parse(bank / 'entities/alpha-project.md').body)
    assert 'An obsolete belief.' not in calls[0]
    assert snapshot(bank) == before


def test_resume_hashes_page_source_and_engine(bank, tmp_path):
    out = tmp_path / 'candidates'
    calls = []
    kw = dict(generate=True, llm_fn=fake(calls), max_calls=1, token_budget=10000,
              today='2026-10-08', engine_id='fake-v1')
    repair.run(bank, out, **kw)
    assert repair.run(bank, out, **kw)['pages'][0]['status'] == 'cached'
    assert len(calls) == 1
    path = bank / 'episodes/ep_2024-01-15_001.md'
    path.write_text(path.read_text() + '\nuser: Later detail.')
    assert repair.run(bank, out, **kw)['calls'] == 1
    assert len(calls) == 2
    assert repair.run(bank, out, **{**kw, 'engine_id': 'fake-v2'})['calls'] == 1


@pytest.mark.parametrize('kind', ['human', 'custom', 'corrupt', 'missing', 'oversized'])
def test_unsafe_or_incomplete_inputs_skip_without_call(bank, tmp_path, kind):
    path = bank / 'entities/alpha-project.md'
    page = md.parse(path)
    if kind == 'human': page.frontmatter['human_edited'] = True
    if kind == 'custom': page.body = '## Personal notes\nKeep this exact.\n' + page.body
    if kind == 'corrupt': page.body += '\n```claims\nunterminated'
    if kind == 'missing': page.frontmatter['source_episodes'].append('ep_2025-01-15_001')
    if kind == 'oversized': page.body = '## Key Facts\n- ' + 'detail ' * 5000
    md.write(path, page.frontmatter, page.body)
    calls = []
    result = repair.run(bank, tmp_path / 'candidates', generate=True, llm_fn=fake(calls),
                        max_calls=1, token_budget=10000, engine_id='fake-v1')
    assert result['pages'][0]['status'] == 'deferred'
    assert calls == []


def test_budgets_invalid_output_and_path_overlap(bank, tmp_path):
    calls = []
    for max_calls, budget in [(0, 10000), (1, 1)]:
        result = repair.run(bank, tmp_path / f'out-{max_calls}-{budget}', generate=True,
                            llm_fn=fake(calls), max_calls=max_calls, token_budget=budget, engine_id='fake-v1')
        assert result['calls'] == 0
    result = repair.run(bank, tmp_path / 'bad', generate=True, llm_fn=fake(calls, bad=True),
                        max_calls=1, token_budget=10000, engine_id='fake-v1')
    assert result['pages'][0]['reason'] == 'invalid_output' and len(calls) == 1
    for output in (bank / 'scratch', bank.parent):
        with pytest.raises(ValueError): repair.run(bank, output)
    alias = tmp_path / 'alias'
    alias.symlink_to(bank, target_is_directory=True)
    with pytest.raises(ValueError): repair.run(bank, alias / 'out')


def test_no_apply_argument_or_symbol():
    assert not hasattr(repair, 'apply')


def test_pilot_selection_and_max_pages(bank, tmp_path):
    result = repair.run(bank, tmp_path / 'out', entity_ids=['alpha-project', 'missing-project'], max_pages=1)
    assert len(result['pages']) == 1 and result['pages'][0]['entity_id'] == 'alpha-project'
    with pytest.raises(ValueError): repair.run(bank, tmp_path / 'unsafe', entity_ids=['../../escape'])


def test_changed_source_during_call_is_deferred(bank, tmp_path):
    calls = []
    def completion(**kw):
        result = fake(calls)(**kw)
        path = bank / 'episodes/ep_2024-01-15_001.md'
        path.write_text(path.read_text() + '\nuser: Changed during generation.')
        return result
    result = repair.run(bank, tmp_path / 'out', generate=True, llm_fn=completion,
                        max_calls=1, token_budget=10000, engine_id='fake-v1')
    assert result['pages'][0]['reason'] == 'changed_input'
    assert not list((tmp_path / 'out').glob('*.candidate.json'))


def test_edits_cannot_rewrite_facts_or_invent_dates(bank, tmp_path):
    def completion(**kw):
        data = json.loads(kw['messages'][-1]['content'].partition('\nINPUT:\n')[2])
        return {'choices': [{'message': {'content': json.dumps({'summary': 'A local notes project.',
            'dated_edits': [{'id': data['items'][0]['id'], 'source_id': data['sources'][0]['id'],
                             'text': '2026-10-08: Changed unrelated facts.'}]})}}]}
    before = snapshot(bank)
    result = repair.run(bank, tmp_path / 'out', generate=True, llm_fn=completion,
                        max_calls=1, token_budget=10000, engine_id='fake-v1')
    assert result['pages'][0]['reason'] == 'invalid_output' and snapshot(bank) == before


def test_dirty_bank_no_call_and_no_git_index_write(bank, tmp_path):
    subprocess.run(['git', 'init', '-q', str(bank)], check=True)
    before = snapshot(bank)
    calls = []
    result = repair.run(bank, tmp_path / 'out', generate=True, llm_fn=fake(calls),
                        max_calls=1, token_budget=10000, engine_id='fake-v1')
    assert result['pages'][0]['reason'] == 'dirty_bank'
    assert calls == [] and snapshot(bank) == before


def test_cli_inventory_bootstraps_scratch_and_has_no_apply(bank, tmp_path):
    repo = Path(__file__).resolve().parents[2]
    scratch = tmp_path / 'cli-out'
    before = snapshot(bank)
    result = subprocess.run([str(repo / 'api/.venv/bin/python'), str(repo / 'scripts/repair_entity_prose.py'),
                             '--bank', str(bank), '--scratch', str(scratch)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['calls'] == 0 and snapshot(bank) == before
    assert (scratch / 'manifest.json').stat().st_mode & 0o777 == 0o600
    result = subprocess.run([str(repo / 'api/.venv/bin/python'), str(repo / 'scripts/repair_entity_prose.py'),
                             '--bank', str(bank), '--scratch', str(scratch), '--apply'], capture_output=True, text=True)
    assert result.returncode != 0 and snapshot(bank) == before


def test_repair_keeps_unknown_metadata_without_certifying_new_summary(bank, tmp_path):
    from api.services import section_provenance as sp
    page_path = bank / 'entities/alpha-project.md'
    page = md.parse(page_path)
    page.frontmatter[sp.FIELD] = {'v': 999, 'future': 'opaque'}
    md.write(page_path, page.frontmatter, page.body)
    result = repair.run(bank, tmp_path / 'out', generate=True, llm_fn=fake([]),
                        max_calls=1, token_budget=10000, engine_id='fake-v1')
    candidate = json.loads(Path(result['pages'][0]['candidate']).read_text())
    assert candidate['frontmatter'][sp.FIELD] == page.frontmatter[sp.FIELD]


def test_partial_engine_failure_checkpoints_and_resumes(bank, tmp_path):
    from api.services.engine_errors import EngineUnavailable
    page = md.parse(bank / 'entities/alpha-project.md')
    md.write(bank / 'entities/beta-project.md', {**page.frontmatter, 'name': 'beta-project'}, page.body)
    before = snapshot(bank)
    calls = []
    def failing(**kw):
        if calls:
            raise EngineUnavailable('Synthetic failure.')
        return fake(calls)(**kw)
    out = tmp_path / 'out'
    kw = dict(generate=True, max_calls=2, token_budget=20000, engine_id='fake-v1', today='2026-10-08')
    with pytest.raises(EngineUnavailable): repair.run(bank, out, llm_fn=failing, **kw)
    manifest = json.loads((out / 'manifest.json').read_text())
    assert manifest['calls'] == 2 and manifest['pages'][1]['reason'] == 'engine_failure'
    assert len(list(out.glob('run-*.json'))) == 1
    resumed = repair.run(bank, out, llm_fn=fake([]), **{**kw, 'max_calls': 1})
    assert resumed['calls'] == 1 and resumed['pages'][0]['status'] == 'cached'
    assert len(list(out.glob('run-*.json'))) == 2
    assert snapshot(bank) == before


def test_date_prefix_loses_exact_provenance_guard(bank, tmp_path):
    from api.services import section_provenance as sp
    page_path = bank / 'entities/alpha-project.md'
    page = md.parse(page_path)
    fields = {'key_facts': ['Planned a local notes prototype.']}
    sp.attach(fields, 'ep_2024-01-15_001', 'user: Planned a local notes prototype.')
    sp.refresh(page.frontmatter, '', page.body, fields)
    md.write(page_path, page.frontmatter, page.body)
    assert sp.matched(page.frontmatter, page.body)['key_facts']
    result = repair.run(bank, tmp_path / 'out', generate=True, llm_fn=fake([], edit=True),
                        max_calls=1, token_budget=10000, engine_id='fake-v1')
    candidate = json.loads(Path(result['pages'][0]['candidate']).read_text())
    assert not sp.matched(candidate['frontmatter'], candidate['body']).get('key_facts')


def test_repair_preserves_nonbullet_text_in_other_sections(bank, tmp_path):
    path = bank / 'entities/alpha-project.md'
    page = md.parse(path)
    page.body = page.body.replace('## Key Facts\n', '## Key Facts\nUnstructured context.\n')
    md.write(path, page.frontmatter, page.body)
    result = repair.run(bank, tmp_path / 'out', generate=True, llm_fn=fake([], edit=True),
                        max_calls=1, token_budget=10000, engine_id='fake-v1')
    candidate = json.loads(Path(result['pages'][0]['candidate']).read_text())
    assert 'Unstructured context.' in candidate['body']
