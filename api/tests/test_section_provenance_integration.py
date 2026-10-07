"""Synthetic real extraction/resolution/write/commit/read chain; no live engine."""
import asyncio
import json
import subprocess
from types import SimpleNamespace

from api.config import Settings
from api.services import bank_index, conflict_resolver, entity_extractor, entity_resolver
from api.services import markdown_parser, provenance


def test_substantive_single_episode_promotion_then_b_fact_only_update(tmp_path, monkeypatch):
    (tmp_path / 'entities').mkdir()
    (tmp_path / 'episodes').mkdir()
    (tmp_path / 'inbox').mkdir()
    settings = Settings(_env_file=None, memory_path=tmp_path, litellm_model='synthetic')
    ep_a, ep_b = 'ep_2026-10-07_001', 'ep_2026-10-07_002'
    description = 'A synthetic project with enough substantive description to qualify for single-episode promotion. ' * 3
    outputs = [
        {'entities': [{'name': 'alpha-project', 'type': 'project', 'summary': 'Example project.',
                       'description': description, 'key_facts': ['Original fact.'], 'confidence': .95}], 'relationships': []},
        {'entities': [{'name': 'alpha-project', 'type': 'project', 'key_facts': ['New fact.'], 'confidence': .95}], 'relationships': []},
    ]
    async def fake(**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(outputs.pop(0))))])
    monkeypatch.setattr(entity_extractor.litellm, 'acompletion', fake)
    def git(*args):
        return subprocess.run(['git', *args], cwd=tmp_path, check=True, capture_output=True, text=True).stdout
    git('init', '-q')
    git('config', 'user.name', 'Synthetic Test')
    git('config', 'user.email', 'synthetic@example.com')
    for ep, existing in [(ep_a, []), (ep_b, None)]:
        body = 'user: Synthetic observation for ' + ep
        markdown_parser.write(tmp_path / 'episodes' / f'{ep}.md', {'id': ep, 'timestamp': '2026-10-07T10:00:00Z'}, body)
        if existing is None:
            parsed = markdown_parser.parse(tmp_path / 'entities' / 'alpha-project.md')
            existing = [{'id': 'alpha-project', 'frontmatter': parsed.frontmatter, 'body': parsed.body}]
        extracted = asyncio.run(entity_extractor.extract([{'id': ep, 'content': body, 'origin': 'synthetic'}], settings))
        resolved = asyncio.run(entity_resolver.resolve(extracted, existing, settings))
        assert len(resolved['changes']) == 1
        if ep == ep_a:
            assert resolved['changes'][0]['action'] == 'create'
        else:
            assert not conflict_resolver._entity_summary(resolved['changes'][0]['entity'])
        conflict_resolver.apply_changes(resolved['changes'], tmp_path)
        git('add', 'entities/alpha-project.md', f'episodes/{ep}.md')
        git('commit', '-q', '-m', 'Synthetic provenance fixture', '-m', 'Cicada-Author: cicada')
    bank_index.invalidate()
    result = provenance.entity_provenance(tmp_path, tmp_path / 'entities' / 'alpha-project.md')
    assert result.sections[0].recorded_items == 1
    assert result.sections[1].recorded_items == 2
    summary = result.sections[0].items[0]
    assert {e.evidence.episode for e in summary.evidence} == {ep_a}
    assert {e.evidence.episode for item in result.sections[1].items for e in item.evidence} == {ep_a, ep_b}
    assert git('status', '--porcelain', '--', 'entities', 'episodes') == ''
    assert len(git('log', '--format=%H').splitlines()) == 2
    assert not outputs
