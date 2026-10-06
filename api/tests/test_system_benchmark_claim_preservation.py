"""G148 temporal fixture exposed a claim fence swallowed by Related rebuild."""
import pytest
from api.services import claims, conflict_resolver, markdown_parser


@pytest.mark.parametrize('mode', ['synthesis', 'fallback', 'human'])
def test_entity_update_preserves_claims_when_rebuilding_related(tmp_path, mode):
    bank = tmp_path / 'bank'
    entities = bank / 'entities'
    entities.mkdir(parents=True)
    path = entities / 'alpha-project.md'
    old = claims.Claim(id='clm_old', text='alpha-project runs on primary-machine',
                       subject='alpha-project', predicate='runs-on', object='primary-machine')
    body = claims.write_claims('## Summary\nSynthetic project.\n\n## Related\n- [[primary-machine]]', [old])
    markdown_parser.write(path, {'id': 'alpha-project', 'name': 'alpha-project',
                                'type': 'project', 'confidence': 0.8, 'related': ['primary-machine'], 'human_edited': mode == 'human'}, body)
    conflict_resolver.apply_changes([{'id': 'alpha-project', 'action': 'update',
        'entity': {'name': 'alpha-project', 'type': 'project', 'confidence': 0.8},
        'synthesized_body': body if mode == 'synthesis' else None}], bank)
    actual = claims.parse_claims(markdown_parser.parse(path).body)
    assert actual == [old], 'Stage 5 must preserve claims before the claim pipeline can reconcile them'


def test_prose_rewrite_preserves_raw_unknown_claim_fields_and_rejects_synthesized_claims():
    original = "## Summary\nOriginal.\n\n```claims\n- id: legacy\n  future_field: retained\n```\n"
    rewritten = "## Summary\nUpdated.\n\n```claims\n- id: invented\n```\n"
    result = claims.preserve_claims_blocks(original, rewritten)
    assert "future_field: retained" in result
    assert "invented" not in result
    assert result.count("```claims") == 1
