"""Offline page-quality eval: what Sleep writes from recorded extractions.

Run: python -m benchmarks.system.page_quality --scratch <new-empty-directory> [--synthesis on|off|both]

Synthetic conversations (``fixtures/page_quality.json``) and a recorded Stage-1
answer for each run through the production Stage 1 post-processing (evidence,
section provenance, the date note), Stage 2 (`entity_resolver.resolve`),
Stage 3 (`conflict_resolver.resolve_and_prune`) and Stage 5's page writer
(`apply_changes`), batch by batch, in a scratch bank. No model is called: the
recorded answers stand in for extraction, and `FakeEngine` answers the judge,
merge and contradiction calls. A prompt change cannot be measured here — only
what the code does with the same answers. No claims, commits or indexes.

Reported per run: pages written and how many rest on one conversation, words,
facts, near-duplicate facts, assistant-said and conversation-about facts,
Summary words, fallback Summaries, "Undated background" bullets, the extracted
facts that reach no page or pending line, and model calls by stage per batch.
"""
from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import os
import re
import statistics
from pathlib import Path

FIXTURE = Path(__file__).with_name('fixtures') / 'page_quality.json'
_ASSISTANT = re.compile(r'\b(?:the )?assistant (?:suggested|recommended|said|described|explained|proposed)'
                        r'|\bwas described as\b', re.I)
_META = re.compile(r'\b(?:was|were) (?:mentioned|discussed|brought up)\b.*\bconversation\b'
                   r'|\basked (?:about|how|whether)\b', re.I)
_STOP = frozenset('a an the of and or for to in on at is are was were be by with its it that this as from'.split())


def _words(text: str) -> list[str]:
    return re.findall(r"[\w'@./-]+", text.lower())


def _content(text: str) -> set[str]:
    return {w.strip('.,') for w in _words(re.sub(r'\[\[([^\]|]+)(\|[^\]]+)?\]\]', r'\1', text))} - _STOP


def near_duplicate(a: str, b: str) -> bool:
    """The eval's own measure (independent of the writer's): text ratio >= 0.75,
    or one fact's content words (at least two) contained in the other's."""
    na, nb = ' '.join(_words(a)), ' '.join(_words(b))
    if difflib.SequenceMatcher(None, na, nb).ratio() >= 0.75:
        return True
    ca, cb = _content(a), _content(b)
    small, large = (ca, cb) if len(ca) <= len(cb) else (cb, ca)
    return len(small) >= 2 and small <= large


def _bullets(section: str) -> list[str]:
    return [line[2:].strip() for line in (section or '').splitlines() if line.startswith(('- ', '* '))]


def page_stats(body: str) -> dict:
    from api.services import claims, entity_body

    sections = entity_body.parse_sections(claims.strip_claims_block(body))
    sections.pop('Related', None)
    facts = _bullets(sections.get('Key Facts', ''))
    dup = set()
    for i, a in enumerate(facts):
        for b in facts[i + 1:]:
            if near_duplicate(a, b):
                dup.add(b)
    summary = sections.get('Summary', '')
    return {
        'words': len(_words(entity_body.render_sections(sections))),
        'facts': len(facts), 'near_dup_facts': len(dup),
        'assistant_facts': sum(bool(_ASSISTANT.search(f)) for f in facts),
        'meta_facts': sum(bool(_META.search(f)) for f in facts),
        'summary_words': len(_words(summary)),
        'fallback_summary': bool(re.fullmatch(r"[^.]{1,400} is an? [a-z ]+\.( Its present role for the owner is not established\.)?", summary.strip())),
        'undated_background': sum(b.startswith('Undated background') for b in _bullets(sections.get('History', ''))),
    }


def run(root: Path, synthesis: bool) -> dict:
    from api.config import Settings
    from api.services import (conflict_resolver as cr, entity_extractor as ex, entity_resolver as er,
                              markdown_parser as md, providers, vector_index)
    from benchmarks.system.engine import FakeEngine

    data = json.loads(FIXTURE.read_text())
    bank = root / f'bank-synthesis-{"on" if synthesis else "off"}'
    (bank / 'entities').mkdir(parents=True)
    (bank / 'episodes').mkdir()
    os.environ['CICADA_MEMORY_PATH'] = str(bank)
    for page in data['seed_pages']:
        fm = {'status': 'active', 'created': '2026-01-10', 'last_referenced': '2026-01-10',
              'source_episodes': ['ep_2026-01-10_001', 'ep_2026-01-11_001'], 'layout_version': 2, **page['frontmatter']}
        md.write(bank / 'entities' / f"{page['id']}.md", fm, page['body'])
    settings = Settings(_env_file=None, summary_synthesis_enabled=synthesis, llm_mode='local',
                        sleep_resolve_concurrency=1)

    engine = FakeEngine()
    recorded: dict[str, dict] = {}
    calls: list[str] = []
    sizes: list[tuple[str, int]] = []  # (stage, prompt characters) per call
    batch_number = [0]
    answers = data.get('merge_answers', {})

    def completion(stage):
        inner = engine.completion(stage=stage, is_async=True)

        async def call(**kwargs):
            calls.append(stage)
            sizes.append((stage, sum(len(str(m.get('content') or '')) for m in kwargs.get('messages') or [])))
            if stage == 'extraction':
                text = kwargs['messages'][-1]['content']
                # The longest recorded conversation inside the message: a resumed one contains its first read.
                found = max((c for c in recorded if c.strip() in text), key=len, default=None)
                if found is None:
                    raise AssertionError('no recorded extraction for this chunk')
                from types import SimpleNamespace
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                    content=json.dumps(recorded[found])))])
            text = kwargs['messages'][-1]['content']
            if stage == 'merge' and 'SECTION-AWARE ORIENTATION' in text:
                # A recorded answer for this page and batch, when the fixture has one.
                incoming = json.loads(text.partition('\nINPUT:\n')[2])
                answer = answers.get(f"{incoming['name']}|{batch_number[0]}")
                if answer:
                    facts = [str(f) for f in incoming['incoming'].get('key_facts') or []]
                    sentences = incoming.get('orientation_sentences') or []
                    payload = {'summary': answer['summary'],
                               'restated': [i for i, f in enumerate(facts) if f in answer['restated']],
                               'covered': [i for i, t in enumerate(sentences) if t in answer.get('covered', [])]}
                    from types import SimpleNamespace
                    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                        content=json.dumps(payload)))])
            return await inner(**kwargs)
        return call

    original = providers.resolve_llm_fn

    def resolve(settings, *, stage=None, **kwargs):
        kwargs['completion'] = completion(stage)
        return original(settings, stage=stage, **kwargs)

    providers.resolve_llm_fn = resolve
    cr.resolve_llm_fn = resolve
    vector_index.SqliteVecIndexer.rebuild_pending_index = lambda self: 0
    vector_index.SqliteVecIndexer._rebuild_pending_index = lambda self, entries: None

    extracted_facts: list[tuple[str, str]] = []  # (entity name, fact)
    per_batch = []
    try:
        for number, batch in enumerate(data['batches'], start=1):
            batch_number[0] = number
            episodes = []
            for item in batch:
                md.write(bank / 'episodes' / f"{item['id']}.md",
                         {'id': item['id'], 'timestamp': item['timestamp'], 'processed': False}, item['content'])
                recorded[item['content']] = item['extraction']
                episodes.append({'id': item['id'], 'content': item['content'], 'timestamp': item['timestamp'],
                                 'origin': 'synthetic'})
                for entity in item['extraction']['entities']:
                    extracted_facts += [(entity['name'], f) for f in entity['key_facts']]
            before = len(calls)
            extraction = asyncio.run(ex.extract(episodes, settings))
            existing = [{'id': p.stem, 'frontmatter': (page := md.parse(p)).frontmatter, 'body': page.body}
                        for p in sorted((bank / 'entities').glob('*.md'))]
            result = asyncio.run(er.resolve(extraction, existing, settings))
            changes = asyncio.run(cr.resolve_and_prune(result['changes'], existing, settings, decay=False))
            cr.apply_changes(changes, bank)
            counted, chars = {}, {}
            for stage in calls[before:]:
                counted[stage] = counted.get(stage, 0) + 1
            for stage, size in sizes[before:]:
                chars[stage] = chars.get(stage, 0) + size
            per_batch.append({'batch': number, 'conversations': len(batch),
                              'updates': sum(c['action'] == 'update' for c in result['changes']),
                              'creates': sum(c['action'] == 'create' for c in result['changes']),
                              'calls': counted, 'prompt_chars': chars})
    finally:
        providers.resolve_llm_fn = original
        cr.resolve_llm_fn = original

    seeds = {p['id'] for p in data['seed_pages']}
    pages = {}
    for path in sorted((bank / 'entities').glob('*.md')):
        parsed = md.parse(path)
        stats = page_stats(parsed.body)
        stats['conversations'] = len(parsed.frontmatter.get('source_episodes') or [])
        stats['seed'] = path.stem in seeds
        pages[path.stem] = {'name': parsed.frontmatter.get('name'), **stats, 'body': parsed.body}
    pending_text = (bank / 'pending_entities.jsonl').read_text() if (bank / 'pending_entities.jsonl').exists() else ''
    pending = [json.loads(line) for line in pending_text.splitlines() if line.strip()]

    try:  # the writer's own rules, when this checkout has them (the eval also runs on older code)
        from api.services import fact_policy
    except ImportError:
        fact_policy = None
    lost, kept, covered, held = [], 0, 0, 0
    narration, restated = [], []
    by_name = {str(p['name']).lower(): p for p in pages.values()}
    for name, fact in extracted_facts:
        page = by_name.get(name.lower())
        on_page = _bullets(page_body_section(page['body'], 'Key Facts')) + [
            page_body_section(page['body'], 'Summary')] + _bullets(page_body_section(page['body'], 'History')) if page else []
        norm = ' '.join(_words(fact))
        if any(' '.join(_words(x)) == norm or norm in ' '.join(_words(x)) for x in on_page):
            kept += 1
        elif any(near_duplicate(fact, x) for x in on_page):
            covered += 1
        elif any(str(line.get('name', '')).lower() == name.lower() and fact in json.dumps(line) for line in pending):
            held += 1
        elif fact_policy is not None and fact_policy.about_the_conversation(fact):
            narration.append(f'{name}: {fact}')
        elif fact_policy is not None and fact_policy.covered(fact, on_page):
            restated.append(f'{name}: {fact}')
        elif page and synthesis and any(f in answers.get(f'{page["name"]}|{b}', {}).get('restated', [])
                                         for f in [fact] for b in range(1, 10)):
            restated.append(f'{name}: {fact} (recorded answer)')
        else:
            lost.append(f'{name}: {fact}')
    written = {k: v for k, v in pages.items() if not v['seed']}
    one = [k for k, v in written.items() if v['conversations'] == 1]
    summary = {
        'synthesis': 'on' if synthesis else 'off',
        'pages_written': len(written), 'one_conversation_pages': len(one),
        'written': sorted(written), 'pending_names': sorted(line.get('name') for line in pending),
        'median_words': statistics.median([v['words'] for v in written.values()]) if written else 0,
        'facts': sum(v['facts'] for v in pages.values()),
        'near_dup_facts': sum(v['near_dup_facts'] for v in pages.values()),
        'assistant_facts': sum(v['assistant_facts'] for v in pages.values()),
        'meta_facts': sum(v['meta_facts'] for v in pages.values()),
        'fallback_summaries': sum(v['fallback_summary'] for v in pages.values()),
        'undated_background': sum(v['undated_background'] for v in pages.values()),
        'max_summary_words': max((v['summary_words'] for v in pages.values()), default=0),
        'extracted_facts': len(extracted_facts), 'facts_kept': kept, 'facts_covered_by_near_duplicate': covered,
        'facts_on_pending_line': held, 'facts_dropped_as_narration': narration,
        'facts_folded_as_restatement': restated, 'facts_lost': lost,
        'batches': per_batch,
        'pages': {k: {kk: vv for kk, vv in v.items() if kk != 'body'} for k, v in pages.items()},
    }
    (root / f'pages-{summary["synthesis"]}.md').write_text(
        '\n\n'.join(f'# {k}\n{v["body"]}' for k, v in pages.items()) + '\n')
    return summary


def page_body_section(body: str, title: str) -> str:
    from api.services import claims, entity_body

    return entity_body.parse_sections(claims.strip_claims_block(body)).get(title, '')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scratch', type=Path, required=True)
    parser.add_argument('--synthesis', choices=('on', 'off', 'both'), default='both')
    args = parser.parse_args()
    root = args.scratch.resolve()
    root.mkdir(parents=True, exist_ok=False)
    os.environ.update(HOME=str(root / 'home'), CICADA_HOME=str(root / 'config'),
                      CICADA_MEMORY_PATH=str(root / 'bank'), LITELLM_MODE='PRODUCTION',
                      CICADA_ALLOW_LOGO_FETCH='off', CICADA_ALLOW_CONNECTOR_FETCH='off')
    (root / 'home').mkdir()
    modes = {'on': [True], 'off': [False], 'both': [False, True]}[args.synthesis]
    results = [run(root, mode) for mode in modes]
    (root / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    for r in results:
        print(json.dumps({k: v for k, v in r.items() if k != 'pages'}, indent=1))


if __name__ == '__main__':
    main()
