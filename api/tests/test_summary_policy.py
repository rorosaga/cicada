"""Bounded machine orientation, full retained context, no model calls."""
import pytest

from api.services import entity_body as body, conflict_resolver as cr, markdown_parser as md, section_provenance as sp


def compose(summary):
    return body.compose_body_v2(summary, [], [], [], [], [])


@pytest.mark.parametrize('mentions', [25, 100])
def test_repeated_mentions_keep_orientation_and_every_detail(mentions):
    orientation = 'alpha-project is a private notes application.'
    sections = body.parse_sections(compose(orientation))
    for index in range(mentions):
        incoming = f'In January 2024, alpha-project evaluated option-{index}.'
        fields = {'summary': incoming, 'key_facts': [f'Observation {index}.']}
        sections = body.merge_sections_fallback(sections, fields)
        # Repeated identical intake is idempotent.
        assert body.merge_sections_fallback(sections, fields) == sections
    assert sections['Summary'] == orientation
    assert len(sections['Summary']) <= 600
    assert all(f'option-{index}.' in sections['History'] for index in range(mentions))
    assert len(sections['Key Facts'].splitlines()) == mentions


@pytest.mark.parametrize('summary', ['Sentence. ' * 100, 'First paragraph.\n\nSecond paragraph.'])
def test_invalid_creation_retains_full_prose_outside_bounded_summary(summary):
    sections = body.parse_sections(compose(summary))
    assert len(sections['Summary']) <= 600
    assert summary.strip() in sections['History'].replace('\n  ', '\n')
    # Another update must not drop a continuation of the preserved prose.
    merged = body.merge_sections_fallback(sections, {'summary': 'Another observation.'})
    assert summary.strip() in merged['History'].replace('\n  ', '\n')


def test_existing_overlong_summary_gets_conservative_fallback_without_clipping():
    old = 'alpha-project evaluated a design. ' * 100
    sections = body.merge_sections_fallback({'Summary': old}, {'key_facts': ['Retained fact.']})
    assert len(sections['Summary']) <= 600
    assert sections['Summary'].endswith('.')
    assert old.strip() in sections['History']
    assert sections['Key Facts'] == '- Retained fact.'


def test_human_summary_is_exact_and_exempt_even_when_overlong():
    human = 'The owner chose these words. ' * 100
    original = {'Summary': human, 'My Notes': 'Preserve this personal note.'}
    merged = body.merge_sections_human_safe(original, {'summary': 'New observation.'}, human_edited=True)
    assert merged['Summary'] == human
    assert merged['My Notes'] == original['My Notes']
    assert 'New observation.' in merged['History']


def test_update_keeps_old_summary_provenance_and_claims(tmp_path):
    (tmp_path / 'entities').mkdir()
    a = {'name': 'alpha-project', 'type': 'project', 'summary': 'A notes application.', 'key_facts': ['Original fact.']}
    sp.attach(a, 'ep_2024-01-15_001', 'user: Synthetic initial context.')
    cr.apply_changes([{'id': 'alpha-project', 'action': 'create', 'entity': a}], tmp_path)
    path = tmp_path / 'entities/alpha-project.md'
    page = md.parse(path)
    fence = '```claims\n- id: synthetic-closed\n  text: An earlier fact\n  valid_to: 2025-01-01\n```'
    md.write(path, page.frontmatter, page.body + '\n\n' + fence)
    cr.apply_changes([{'id': 'alpha-project', 'action': 'update', 'entity': {'summary': 'A later observation.'}}], tmp_path)
    page = md.parse(path)
    assert fence in page.body
    assert len(sp.matched(page.frontmatter, page.body)['summary']) == 1
    assert 'A later observation.' in body.parse_sections(page.body)['History']


def test_long_synthesis_output_is_bounded_without_changing_other_sections(tmp_path):
    (tmp_path / 'entities').mkdir()
    md.write(tmp_path / 'entities/alpha-project.md', {'name': 'alpha-project', 'type': 'project'},
             '## Summary\nA notes application.\n\n## Key Facts\n- Original fact.')
    cr.apply_changes([{'id': 'alpha-project', 'action': 'update', 'entity': {},
                       'synthesized_body': '## Summary\n' + 'Long generated observation. ' * 100 +
                       '\n\n## Key Facts\n- Original fact.'}], tmp_path)
    page = body.parse_sections(md.parse(tmp_path / 'entities/alpha-project.md').body)
    assert page['Summary'] == 'A notes application.'
    assert 'Long generated observation.' in page['History']
    assert page['Key Facts'] == '- Original fact.'


def test_unknown_provenance_does_not_block_bounded_write(tmp_path):
    (tmp_path / 'entities').mkdir()
    md.write(tmp_path / 'entities/alpha-project.md', {'name': 'alpha-project', 'section_provenance': {'v': 999}},
             '## Summary\n' + 'Long observation. ' * 100)
    cr.apply_changes([{'id': 'alpha-project', 'action': 'update', 'entity': {}}], tmp_path)
    page = md.parse(tmp_path / 'entities/alpha-project.md')
    assert page.frontmatter['section_provenance'] == {'v': 999}
    assert len(body.parse_sections(page.body)['Summary']) <= 600
