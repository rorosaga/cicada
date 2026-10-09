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
    # What each displaced orientation said is a Key Fact, once; nothing goes to History.
    assert all(f'option-{index}.' in sections['Key Facts'] for index in range(mentions))
    assert 'History' not in sections
    assert len(sections['Key Facts'].splitlines()) == 2 * mentions


@pytest.mark.parametrize('summary', ['Sentence. ' * 100, 'First paragraph.\n\nSecond paragraph.'])
def test_invalid_creation_keeps_whole_sentences_and_every_distinct_one(summary):
    sections = body.parse_sections(compose(summary))
    assert len(sections['Summary']) <= 600 and '\n\n' not in sections['Summary']
    assert sections['Summary'].endswith('.')
    for sentence in {'Sentence.', 'First paragraph.', 'Second paragraph.'} & set(summary.split('\n\n') + ['Sentence.']):
        if sentence in summary:
            assert (sections['Summary'] + sections.get('Key Facts', '')).count(sentence) == 1
    merged = body.merge_sections_fallback(sections, {'summary': 'Another observation.'})
    assert 'Another observation.' in merged['Key Facts']


def test_existing_overlong_summary_keeps_its_leading_sentences_without_clipping():
    old = 'alpha-project evaluated a design. ' * 100
    sections = body.merge_sections_fallback({'Summary': old}, {'key_facts': ['Retained fact.']})
    assert sections['Summary'] == 'alpha-project evaluated a design.'
    assert sections['Key Facts'] == '- Retained fact.'


def test_glued_orientations_keep_the_first_introduction():
    glued = ('Forge CI is a CI platform. Forge CI is the workflow platform used by alpha-project. '
             'It runs every push. Forge CI is a CI/CD automation platform.')
    sections = body.bound_summary({'Summary': glued}, name='Forge CI', entity_type='tool')
    assert sections['Summary'] == 'Forge CI is a CI platform. It runs every push.'
    facts = sections['Key Facts']
    assert 'Forge CI is the workflow platform used by alpha-project.' in facts
    assert 'Forge CI is a CI/CD automation platform.' in facts
    assert 'History' not in sections


def test_an_unusable_summary_with_no_sentence_to_keep_names_only_what_it_is():
    one_sentence = 'alpha-project ' + 'evaluated a long design ' * 40 + 'option.'
    sections = body.merge_sections_fallback({}, {'name': 'alpha-project', 'type': 'project', 'summary': one_sentence})
    assert sections['Summary'] == 'alpha-project is a project.'
    assert 'not established' not in sections['Summary']
    assert one_sentence in sections['Key Facts']


def test_human_summary_is_exact_and_exempt_even_when_overlong():
    human = 'The owner chose these words. ' * 100
    original = {'Summary': human, 'My Notes': 'Preserve this personal note.'}
    merged = body.merge_sections_human_safe(original, {'summary': 'New observation.'}, human_edited=True)
    assert merged['Summary'] == human
    assert merged['My Notes'] == original['My Notes']
    assert 'New observation.' in merged['Key Facts']


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
    assert 'A later observation.' in body.parse_sections(page.body)['Key Facts']


def test_long_synthesis_output_is_bounded_without_changing_other_sections(tmp_path):
    (tmp_path / 'entities').mkdir()
    md.write(tmp_path / 'entities/alpha-project.md', {'name': 'alpha-project', 'type': 'project'},
             '## Summary\nA notes application.\n\n## Key Facts\n- Original fact.')
    cr.apply_changes([{'id': 'alpha-project', 'action': 'update', 'entity': {},
                       'synthesized_body': '## Summary\n' + 'Long generated observation. ' * 100 +
                       '\n\n## Key Facts\n- Original fact.'}], tmp_path)
    page = body.parse_sections(md.parse(tmp_path / 'entities/alpha-project.md').body)
    # The rewrite's leading whole sentence is its Summary (the repeats say nothing more); every other
    # section is the page's own, item for item.
    assert page['Summary'] == 'Long generated observation.'
    assert page['Key Facts'] == '- Original fact.'


def test_unknown_provenance_does_not_block_bounded_write(tmp_path):
    (tmp_path / 'entities').mkdir()
    md.write(tmp_path / 'entities/alpha-project.md', {'name': 'alpha-project', 'section_provenance': {'v': 999}},
             '## Summary\n' + 'Long observation. ' * 100)
    cr.apply_changes([{'id': 'alpha-project', 'action': 'update', 'entity': {}}], tmp_path)
    page = md.parse(tmp_path / 'entities/alpha-project.md')
    assert page.frontmatter['section_provenance'] == {'v': 999}
    assert len(body.parse_sections(page.body)['Summary']) <= 600
