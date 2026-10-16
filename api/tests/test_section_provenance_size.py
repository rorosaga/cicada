"""Measured YAML size using the production emitter and synthetic fixtures."""
import math
import statistics
import time

import pytest
import yaml

from api.services import evidence, markdown_parser, section_provenance as sp
from api.services.claims import Evidence


def fixture(spans):
    texts = [f'Synthetic item {i:03d} records a distinct observation for the example project.' for i in range(150)]
    summary = 'Synthetic summary describes the example project and its recorded observations.'
    body = '## Summary\n' + summary + '\n\n## Key Facts\n' + '\n'.join('- ' + t for t in texts[:75])
    body += '\n\n## History\n' + '\n'.join('- ' + t for t in texts[75:])
    records = {}
    i = 0
    for key, items in sp.scan(body).items():
        for item in items:
            evs = []
            for j in range(spans):
                ep = (i + j * 23) % 80
                evs.append(Evidence(episode=f'ep_2026-10-07_{ep + 1:03d}',
                    hash=evidence.body_hash(f'synthetic source {ep} revision {j}'),
                    start=1000 + i * 80, end=1070 + i * 80, kind='user'))
            records.setdefault(key, {})[item.key] = (item.text_hash, evs)
            i += 1
    base = {'id': 'synthetic-project', 'name': 'Synthetic Project', 'type': 'project', 'version': 1,
            'source_episodes': [f'ep_2026-10-07_{i + 1:03d}' for i in range(80)]}
    return body, base, sp.encode(records)


@pytest.mark.parametrize('spans,budget,line_budget', [(1, 16 * 1024, 300), (3, 32 * 1024, 600)])
def test_scalar_storage_size_and_complete_round_trip(spans, budget, line_budget):
    body, base, compact = fixture(spans)
    fm = {sp.FIELD: compact}
    serialized = yaml.dump(fm, default_flow_style=False, sort_keys=False)
    whole = markdown_parser._render(base | fm, body)
    baseline = markdown_parser._render(base, body)
    assert len(serialized.encode()) <= budget
    assert len(serialized.splitlines()) <= line_budget
    decoded = sp.decode(yaml.safe_load(serialized)[sp.FIELD])
    assert sum(len(items) for items in decoded.values()) == 151
    assert sum(len(evs) for items in decoded.values() for _, evs in items.values()) == 151 * spans
    parses, dumps = [], []
    for _ in range(100):
        before = time.perf_counter()
        yaml.load(serialized, Loader=getattr(yaml, 'CSafeLoader', yaml.SafeLoader))
        parses.append((time.perf_counter() - before) * 1000)
        before = time.perf_counter()
        yaml.dump(fm, default_flow_style=False, sort_keys=False)
        dumps.append((time.perf_counter() - before) * 1000)
    added = len(whole.decode()) - len(baseline.decode())
    print({'spans': spans, 'source_pairs': len(compact['sources']), 'metadata_bytes': len(serialized.encode()),
           'metadata_lines': len(serialized.splitlines()), 'total_file_bytes': len(whole),
           'total_lines': len(whole.splitlines()), 'metadata_percent': round(100 * len(serialized.encode()) / len(whole), 2),
           'added_characters': added, 'estimated_tokens_characters_div_4': math.ceil(added / 4),
           'parse_median_ms': round(statistics.median(parses), 3), 'dump_median_ms': round(statistics.median(dumps), 3)})
