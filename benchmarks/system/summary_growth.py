"""Offline G194 before/after diagnostic at production Stage 3/5 seams.

Run: python -m benchmarks.system.summary_growth --scratch <new-empty-directory>
No capture, extraction, indexing or external provider latency is measured.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import statistics
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scratch', type=Path, required=True)
    args = parser.parse_args()
    root = args.scratch.resolve()
    root.mkdir(parents=True, exist_ok=False)
    os.environ.update(HOME=str(root / 'home'), CICADA_HOME=str(root / 'config'),
                      CICADA_MEMORY_PATH=str(root / 'bank'), LITELLM_MODE='PRODUCTION')
    (root / 'home').mkdir()
    # Imports follow the scratch bootstrap: no owner settings or bank access.
    from api.config import Settings
    from api.services import conflict_resolver as cr, markdown_parser as md
    from benchmarks.system.engine import FakeEngine

    output = {'pages': 2000, 'batch_size': 25, 'runs': []}
    for workload in ('summary_only', 'legacy_description', 'facts_only'):
        for enabled in (False, True):
            bank = root / f'{workload}-{enabled}'
            (bank / 'entities').mkdir(parents=True)
            os.environ['CICADA_MEMORY_PATH'] = str(bank)
            settings = Settings(_env_file=None, summary_synthesis_enabled=enabled, llm_mode='local')
            engine = FakeEngine()
            # Inject beneath the real provider wrapper; preserve its accounting.
            cr.litellm.acompletion = engine.completion(stage='merge', is_async=True)
            original_resolve = cr.resolve_llm_fn
            def resolve(settings, *, stage, **kwargs):
                kwargs['completion'] = engine.completion(stage=stage, is_async=True)
                return original_resolve(settings, stage=stage, **kwargs)
            cr.resolve_llm_fn = resolve
            ids = [f'project-{i:04}' for i in range(2000)]
            for entity_id in ids:
                md.write(bank / 'entities' / f'{entity_id}.md',
                         {'name': entity_id, 'type': 'project', 'last_referenced': '2026-01-15'},
                         '## Summary\nA synthetic notes application.\n\n## Key Facts\n- Uses local storage.')
            batches = []
            try:
                for batch in range(80):
                    start = time.perf_counter()
                    # A complete 2,000-page read, as the drain's page snapshot.
                    existing = [{'id': p.stem, 'frontmatter': (page := md.parse(p)).frontmatter,
                                 'body': page.body} for p in sorted((bank / 'entities').glob('*.md'))]
                    changes = []
                    for entity_id in ids[batch * 25:(batch + 1) * 25]:
                        fields = {'name': entity_id, 'type': 'project', 'key_facts': ['Uses a desktop client.']}
                        if workload != 'facts_only':
                            fields['description' if workload == 'legacy_description' else 'summary'] = 'A synthetic desktop notes application.'
                        changes.append({'id': entity_id, 'action': 'update', 'entity': fields,
                                        'source_episode_days': ['2026-10-01'],
                                        'source_episode_timestamps': ['2026-10-01T12:00:00Z']})
                    before = len(engine.calls)
                    prepared = asyncio.run(cr.resolve_and_prune(changes, existing, settings, decay=False))
                    cr.apply_changes(prepared, bank)
                    batches.append({'batch': batch + 1, 'calls': len(engine.calls) - before,
                                    'wall_seconds': time.perf_counter() - start})
            finally:
                cr.resolve_llm_fn = original_resolve
            times = sorted(b['wall_seconds'] for b in batches)
            output['runs'].append({'workload': workload, 'enabled': enabled, 'batches': batches,
                                   'total_calls': len(engine.calls), 'median_seconds': statistics.median(times),
                                   'p95_seconds': times[75], 'total_seconds': sum(times)})
    (root / 'results.json').write_text(json.dumps(output, indent=2) + '\n')
    print(json.dumps([{k: v for k, v in r.items() if k != 'batches'} for r in output['runs']], indent=2))


if __name__ == '__main__':
    main()
