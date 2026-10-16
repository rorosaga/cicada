"""Deterministic engine at the production provider seam, without access to gold.

Only a deliberately small synthetic sentence grammar is understood. This is
an integrity diagnostic, not a substitute for an actual model evaluation.
"""
from __future__ import annotations

import hashlib
import json
import re
from types import SimpleNamespace

FACT = re.compile(r'\b([a-z]+-project) (uses|status|runs-on) ([a-z][a-z0-9-]*)\.')


def facts(text):
    return [m.groups() for m in FACT.finditer(text)]


def extraction(text):
    rows = facts(text)
    entities = {}
    relationships = []
    for subject, predicate, obj in rows:
        for name, kind in ((subject, 'project'), (obj, 'concept' if predicate == 'status' else 'tool')):
            entities[name] = {
                'name': name, 'type': kind, 'aliases': [], 'confidence': 0.8,
                'summary': f'{name} is discussed in synthetic design conversations.',
                'description': f'{name} is discussed in synthetic design conversations.',
                'key_facts': [f'{s} {p} {o}.' for s, p, o in rows if s == name],
                'history_entries': [], 'tags': ['synthetic'], 'decay_class': 'active',
            }
        relationships.append({'source': subject, 'target': obj, 'label': predicate,
                              'evidence_quote': f'{subject} {predicate} {obj}.', 'confidence': 0.8})
    return {'entities': list(entities.values()), 'relationships': relationships}


def answer(prompt):
    """Answer from exposed context only; never read files or gold answers."""
    from api.services.claims import parse_claims

    question, _, context = prompt.partition('\n\n')
    subject_match = re.search(r'([a-z]+-project)', question)
    subject = subject_match.group(1) if subject_match else ''
    predicate = 'status' if 'status' in question else 'uses'
    claims = []
    for block in re.findall(r'```claims\n.*?```', context, flags=re.S):
        claims.extend(parse_claims(block))
    current = [c for c in claims if c.subject == subject and c.predicate == predicate
               and not c.valid_to and not c.superseded_by]
    if current:
        chosen = max(current, key=lambda c: (c.origin == 'manual_edit', c.valid_from or '', c.id))
        value = chosen.object
    else:
        matching = [obj for s, p, obj in facts(context) if s == subject and p == predicate]
        value = matching[-1] if matching else None
    ids = re.findall(r'### entity_id: ([^\n]+)', context)
    return {'answer': f'{subject} {predicate} {value}.' if value else 'Unknown.',
            'confidence': 0.9 if value else 0.0, 'cite_ids': ids[:1] if value else [],
            'gaps': [] if value else ['No supporting fact in the exposed context.']}


class FakeEngine:
    def __init__(self):
        self.calls = []
        self.mode = None
        self.remaining = 0
        self.on_extract = None

    def arm(self, mode, skills_call=1):
        self.mode, self.remaining = mode, skills_call

    def completion(self, *, stage=None, is_async=False):
        """Transport stub injected beneath the real production provider wrapper."""

        def call(*, model, messages, **unused):
            import time
            from api.services import agent_engine, engine_errors, sleep_cycle

            start = time.perf_counter()
            event = {'stage': stage, 'model': model, 'tokens': None,
                     'ok': False, 'retry': False, 'scope': agent_engine.current_scope()}
            self.calls.append(event)
            try:
                text = messages[-1]['content']
                agent_engine.record_model_used(model)
                if stage == 'skills' and self.mode:
                    self.remaining -= 1
                    if self.remaining <= 0:
                        mode, self.mode = self.mode, None
                        event['injected'] = mode
                        if mode == 'pause':
                            agent_engine.trip_breaker('Synthetic plan window exhausted.', resets_at=1900000000)
                            raise engine_errors.EngineThrottled('Synthetic plan window exhausted.', resets_at=1900000000)
                        if mode == 'failure':
                            raise engine_errors.EngineUnavailable('Synthetic engine unavailable.')
                        if mode == 'cancel':
                            sleep_cycle.request_cancel()
                if stage == 'extraction':
                    if self.on_extract:
                        callback, self.on_extract = self.on_extract, None
                        callback()
                    payload = extraction(text)
                elif stage == 'skills':
                    payload = {'skills': []}
                elif stage == 'disambiguation':
                    payload = {'decision': 'different', 'reason': 'Distinct synthetic identifiers.'}
                elif stage == 'conflict':
                    payload = {'has_unresolvable_contradiction': False}
                elif stage == 'merge':
                    if 'SECTION-AWARE ORIENTATION' in text:
                        data = json.loads(text.partition('\nINPUT:\n')[2])
                        payload = {'summary': data['incoming'].get('summary')
                                   or data['existing_sections'].get('Summary')
                                   or "This entity's present role is unknown."}
                    else:
                        # Legacy synthesis output is prose. Claim reconciliation
                        # remains the production writer; never emit a claims block.
                        existing = text.partition('EXISTING PAGE BODY:\n')[2].partition('\n\nNEW INFORMATION TO INTEGRATE:')[0]
                        from api.services import claims, entity_body
                        sections = entity_body.parse_sections(claims.strip_claims_block(existing))
                        sections['Summary'] = sections.get('Summary', '') + '\n' + text.partition('Description: ')[2].partition('\nNew history')[0]
                        payload = entity_body.render_sections(sections)
                elif stage in ('ask', 'answer_control'):
                    payload = answer(text)
                else:
                    raise AssertionError(f'unexpected generative stage {stage}')
                content = payload if isinstance(payload, str) else json.dumps(payload)
                event['ok'] = True
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
            except Exception as exc:
                event['error'] = type(exc).__name__
                raise
            finally:
                event['wall_seconds'] = time.perf_counter() - start

        async def async_call(**kwargs):
            return call(**kwargs)

        return async_call if is_async else call


def embed(texts, *, is_query=False):
    """Stable local feature hashing. Diagnostic vectors, NOT a learned model."""
    import numpy as np

    vectors = np.zeros((len(texts), 64), dtype=np.float32)
    for row, text in enumerate(texts):
        for token in re.findall(r'[a-z0-9-]+', text.lower()):
            digest = hashlib.sha256(token.encode()).digest()
            vectors[row, int.from_bytes(digest[:2], 'little') % 64] += 1
        norm = np.linalg.norm(vectors[row])
        if norm:
            vectors[row] /= norm
    return vectors
