"""Child-only production workload. Launch through runner, never _bootstrap."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time
import uuid

from .runner import REPO, _no_symlinks, prepare_paths

FIXTURES = Path(__file__).parent / 'fixtures'


def git(bank, *args):
    return subprocess.run(['git', '-C', str(bank), *args], text=True, capture_output=True, check=True).stdout.strip()


def disk_bytes(path):
    return sum(p.stat().st_size for p in path.rglob('*') if p.is_file())


def all_claims(bank):
    from api.services import claims, markdown_parser
    return [claim for path in (bank / 'entities').glob('*.md')
            for claim in claims.parse_claims(markdown_parser.parse(path).body)]


def initialize(bank):
    from api.services import bank_registry, markdown_parser, predicates
    if (bank / '.git').exists():
        raise ValueError('small preset requires an empty marked bank; reuse via a fresh temp bank')
    if set(p.name for p in bank.iterdir()) != {'_bench.yaml'}:
        raise ValueError('small preset refuses pre-existing bank contents')
    for name in ('entities', 'episodes', 'inbox'):
        (bank / name).mkdir()
    (bank / '.gitignore').write_text('\n'.join(bank_registry.DERIVED_ARTIFACTS) + '\n')
    predicates.install_predicate_map(bank)
    git(bank, 'init', '-q')
    git(bank, 'config', 'user.name', 'Cicada Benchmark')
    git(bank, 'config', 'user.email', 'benchmark@cicada.local')
    git(bank, 'add', '-A')
    git(bank, 'commit', '-q', '-m', 'Synthetic benchmark seed\n\nCicada-Author: cicada')


def draft(row, clock):
    from api.services.episode_staging import EpisodeDraft, Turn
    day = (clock + timedelta(days=row['day'])).date().isoformat()
    return EpisodeDraft(title='Synthetic design discussion', source_id=row['source_id'],
                        timestamp=f'{day}T10:00:00+00:00', original_date=day,
                        source='import', origin='chatgpt',
                        extra={'session_id': 'ses_bench_' + row['source_id'].replace(':', '_')},
                        turns=[Turn(text=text, ts=f'{day}T10:{i:02d}:00+00:00') for i, text in enumerate(row['turns'])])


def stage(bank, rows, clock):
    from api.services import episode_staging, git_service
    result = episode_staging.stage([draft(row, clock) for row in rows], bank / 'episodes')
    if result.paths:
        message = git_service.build_commit_message('Synthetic intake', [], authors=['user'])
        git_service.commit_paths_sync(bank, message, result.paths)
    return result


def snapshot(bank):
    from api.services import markdown_parser
    return {p.stem: {'processed': bool(markdown_parser.parse(p).frontmatter.get('processed')),
                     'hash': hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in (bank / 'episodes').glob('*.md')}


def owned_commits(bank):
    commits = []
    valid = True
    for sha in git(bank, 'rev-list', '--reverse', 'HEAD').splitlines():
        message = git(bank, 'show', '-s', '--format=%B', sha)
        paths = git(bank, 'diff-tree', '--root', '--no-commit-id', '--name-only', '-r', sha).splitlines()
        authors = [line.partition(': ')[2] for line in message.splitlines() if line.startswith('Cicada-Author: ')]
        if not authors:
            valid = False
        if '_state.md' in paths and paths != ['_state.md']:
            valid = False
        if message.startswith('Sleep cycle') and '(decay)' not in message:
            if not any(line.startswith('Cicada-Session: ') for line in message.splitlines()):
                valid = False
            if any(p.startswith('episodes/') for p in paths) and not any(a != 'cicada' for a in authors):
                valid = False
        if message.startswith('Expiry') and authors != ['cicada']:
            valid = False
        commits.append({'sha': sha, 'subject': message.splitlines()[0], 'authors': authors, 'paths': paths})
    return valid, commits


def controls(bank, questions, raw, settings, clock, after=False):
    from api.services import ask_service, providers, vector_index
    out = []
    indexer = vector_index.SqliteVecIndexer(bank)
    for row in questions:
        question = row['question']
        started = time.perf_counter()
        if after:
            response = ask_service.answer_query(bank, question, top_k=6,
                                               llm_fn=ask_service._default_llm_fn(settings))
            exposed = 'ask_service.answer_query:claim-first+entity-fallback'
        else:
            if raw is None:
                hits = indexer.search_episodes(question, top_k=6)
                context = '\n\n'.join(hit['text'][:3000] for hit in hits)
                exposed = 'SqliteVecIndexer.search_episodes:top_k=6,3000chars/hit'
            else:
                context = raw
                exposed = 'raw conversations:full-context'
            prompt = f'QUESTION:\n{question}\n\nCONTEXT:\n{context}'
            fn = providers.resolve_llm_fn(settings, stage='answer_control', is_async=False)
            resp = fn(messages=[{'role': 'system', 'content': ask_service.ASK_SYSTEM_PROMPT},
                                {'role': 'user', 'content': prompt}], response_format={'type': 'json_object'})
            response = json.loads(resp.choices[0].message.content)
        answer = response['answer']
        grounded = None
        if after and row['claim'] is not None:
            from api.services import evidence
            cited = {citation.get('claim_id') for citation in response.get('citations', [])}
            grounded = any(c.id in cited and (c.subject, c.predicate, c.object) == tuple(row['claim'])
                           and any(e.kind != 'reasoning' and evidence.span_status(
                               evidence.source_text(bank, e.episode) or '', end=e.end, hash=e.hash) in ('current', 'grown')
                               for e in c.evidence) for c in all_claims(bank))
        # Exact equality evaluates this finite fake grammar; no overlap grade.
        # Real-model responses stay ungraded for manual grounded assessment.
        if settings.litellm_model == 'deterministic-v1':
            if row['claim'] is None:
                correct = answer == 'Unknown.' or bool(response.get('gaps')) and not response.get('used_entities')
            else:
                correct = answer == row['answer'] and (grounded is not False)
        else:
            correct = None
        out.append({'id': row['id'], 'question': question, 'response': response,
                    'correct': correct, 'grounded': grounded,
                    'irrelevant_citations_on_abstention': len(response.get('citations', [])) if row['claim'] is None else None,
                    'surface': exposed, 'wall_seconds': time.perf_counter() - started})
    return out


async def subscription_preflight(model, *, snapshot_fn=None):
    """Require positive plan auth and model-roster evidence before ANY paid call."""
    from api.services import codex_app_server, codex_engine
    snap = await (snapshot_fn or codex_app_server.snapshot)(fresh=True)
    if snap is None or not snap.signed_in or snap.account_type != 'chatgpt':
        raise ValueError('benchmark requires verified subscription authentication in its isolated home')
    if model not in snap.models:
        raise ValueError('requested model is not on the live subscription roster')
    async def pinned_snapshot(**kwargs):
        return snap
    ok, detail, _ = await codex_engine.preflight(snapshot_fn=pinned_snapshot)
    if not ok:
        raise ValueError(detail)
    # Never serialize the snapshot wholesale: it includes an account email.
    return {'account_type': snap.account_type, 'plan': snap.plan,
            'models': list(snap.models), 'windows': list(snap.windows),
            'used_percent': snap.used_percent, 'resets_at': snap.resets_at,
            'as_of': snap.as_of}


async def execute(args, manifest):
    from api.config import Settings
    from api.services import (agentic_write, claims, evidence, git_service, markdown_parser,
                              search_index, sleep_cycle, sleep_paused, vector_index)
    from .engine import FakeEngine
    from .runtime import Runtime

    bank, home = Path(args['bank_dir']), Path(args['home'])
    clock = datetime.fromisoformat(args['clock']).astimezone(timezone.utc)
    # Explicit aliases for the memory root: never rely on a silently ignored
    # Settings(memory_path=...) / Settings(memory_root=...) keyword.
    settings = Settings(_env_file=None, CICADA_MEMORY_PATH=str(bank),
                        llm_mode='codex' if args['engine'] == 'codex' else 'local',
                        litellm_model=args['model'], consolidation_model=args['model'],
                        ollama_model=args['model'],
                        litellm_disambiguation_model=args['model'],
                        codex_model=args['model'], codex_disambiguation_model=args['model'],
                        codex_reasoning_effort=args['effort'],
                        embedding_mode='local', embedding_model_local=args['config']['embedding_model'],
                        sleep_max_episodes_per_cycle=2, link_enrich_enabled=False)
    if settings.memory_path != bank:
        raise RuntimeError('active bank differs from explicit benchmark bank')
    # Same pins for default read-service settings, with no dotenv inheritance.
    for name in ('LITELLM_MODEL', 'CONSOLIDATION_MODEL', 'LITELLM_DISAMBIGUATION_MODEL',
                 'CODEX_MODEL', 'CODEX_DISAMBIGUATION_MODEL'):
        os.environ['CICADA_' + name] = args['model']
    os.environ['CICADA_OLLAMA_MODEL'] = args['model']
    os.environ['CICADA_CODEX_REASONING_EFFORT'] = args['effort']
    os.environ['CICADA_EMBEDDING_MODEL_LOCAL'] = args['config']['embedding_model']
    fake = FakeEngine() if args['engine'] == 'fake' else None
    if fake is None:
        manifest['subscription_preflight'] = await subscription_preflight(args['model'])
    corpus = json.loads((FIXTURES / 'conversations.json').read_text())
    gold = json.loads((FIXTURES / 'gold_answers.json').read_text())
    checks = manifest['integrity']
    runtime = Runtime(clock, settings, fake)
    manifest['model_calls'] = fake.calls if fake else runtime.calls
    manifest['timings'] = runtime.timings
    manifest['embedding_calls'] = runtime.embedding_calls

    async def drain(label, continued=None):
        cycle_id = 'sleep_bench_' + label
        with runtime.frozen():
            await sleep_cycle.run(settings, cycle_id, user_triggered=True, drain=True, continue_from=continued)
        state = sleep_cycle.get_sleep_state()
        ds = state.drain
        leg = {'label': label, 'cycle_id': cycle_id, 'error': state.error,
               'stop': ds.stop.reason if ds and ds.stop else None,
               'filed': ds.filed if ds else 0, 'finished': ds.finished if ds else True,
               'queued': [e['id'] for e in sleep_cycle._get_unprocessed_episodes(bank)],
               'index_warning': state.index_warning}
        manifest['runs'].append(leg)
        if leg['error'] or leg['stop'] or leg['index_warning']:
            manifest['failures'].append(leg)
        return leg

    with runtime:
        with runtime.frozen():
            initialize(bank)
            imported = stage(bank, corpus['fresh'], clock)
            start = time.perf_counter()
            vector_index.SqliteVecIndexer(bank).index_episodes()
            search_index.refresh(bank)
            runtime.timings.append({'stage': 'index', 'cycle': 'before_sleep', 'wall_seconds': time.perf_counter() - start, 'ok': True})
            raw = '\n\n'.join(markdown_parser.parse(p).body for p in sorted((bank / 'episodes').glob('*.md')))
            manifest['controls']['full_context'] = controls(bank, gold['questions'], raw, settings, clock)
            manifest['controls']['before_sleep'] = controls(bank, gold['questions'], None, settings, clock)
        await drain('fresh')
        with runtime.frozen():
            manifest['controls']['after_sleep'] = controls(bank, gold['questions'], None, settings, clock, after=True)
            before = snapshot(bank)
            head = git(bank, 'rev-parse', 'HEAD')
            repeated = stage(bank, corpus['fresh'], clock)
            checks['idempotent_reimport'] = repeated.skipped == 2 and before == snapshot(bank) and head == git(bank, 'rev-parse', 'HEAD')
            stage(bank, [corpus['continued']], clock)
        await drain('continued')
        with runtime.frozen():
            stage(bank, [corpus['temporal']], clock)
        await drain('temporal_change')
        with runtime.frozen():
            revised = stage(bank, [corpus['revised']], clock)
        if fake:
            row = {**corpus['revised'], 'turns': corpus['revised']['turns'] + [corpus['during_read']]}
            def edit_while_reading():
                stage(bank, [row], clock)
            fake.on_extract = edit_while_reading
        await drain('revised')
        ep_id = revised.episode_ids[corpus['revised']['source_id']]
        checks['revision_safe_retirement'] = (not snapshot(bank)[ep_id]['processed']) if fake else None
        await drain('revision_requeued')
        checks['revision_recovered'] = all(x['processed'] for x in snapshot(bank).values())
        # A human correction through the production manual-write seam, committed
        # alone; subsequent extraction cannot withdraw it.
        with runtime.frozen():
            agentic_write.write_claim(bank, 'alpha-project', 'status', 'reviewing',
                         observer='owner', object_kind='literal', origin='manual_edit', authored_by='user',
                         today=runtime.clock.date(), text='alpha-project status reviewing.')
            agentic_write.write_claim(bank, 'alpha-project', 'availability', 'temporary',
                         observer='owner', object_kind='literal', origin='manual_edit', authored_by='user',
                         today=runtime.clock.date(), expected_end=runtime.clock.date().isoformat())
            git_service.commit_paths_sync(bank, git_service.build_commit_message('Synthetic correction', [], authors=['user']), ['entities/alpha-project.md'])
        ids_before = {c.id for c in all_claims(bank)}
        if fake:
            for mode in ('pause', 'cancel', 'failure'):
                rows = [{**row, 'source_id': row['source_id'] + ':' + mode} for row in corpus['recovery']]
                with runtime.frozen():
                    stage(bank, rows, clock)
                fake.arm(mode, skills_call=2)  # retain batch one, stop inside batch two
                stopped = await drain(mode)
                record = sleep_paused.get_paused(bank)
                manifest['resume_lineage'].append({'reason': mode, 'run_id': record.get('run_id') if record else None,
                                                   'parent_leg': mode, 'resume_leg': mode + '_resume',
                                                   'filed_at_stop': stopped['filed']})
                resumed = await drain(mode + '_resume', record)
                checks['recovered_' + mode] = bool(record) and stopped['filed'] >= 2 and resumed['finished'] and not resumed['queued']
        runtime.clock += timedelta(days=1)
        await drain('clock_advance')  # idle run must still execute the real expiry tail
        current = all_claims(bank)
        checks['human_correction_preserved'] = any(c.origin == 'manual_edit' and c.predicate == 'status'
                                                   and c.object == 'reviewing' and not c.valid_to for c in current)
        checks['fixed_clock_expiry'] = any(c.predicate == 'availability' and c.valid_to == clock.date().isoformat() for c in current)
        actual = {(c.subject, c.predicate, c.object) for c in current if not c.valid_to}
        checks['no_lost_claims'] = set(map(tuple, gold['required_final_claims'])).issubset(actual) if fake else None
        checks['temporal_history_preserved'] = any(c.subject == 'beta-project' and c.object == 'primary-machine' and c.valid_to for c in current) and any(c.subject == 'beta-project' and c.object == 'secondary-machine' and not c.valid_to for c in current)
        checks['retained_claim_ids'] = ids_before.issubset({c.id for c in current})
        spans = [e for c in current for e in c.evidence if e.kind != 'reasoning']
        span_states = [evidence.span_status(evidence.source_text(bank, e.episode) or '', end=e.end, hash=e.hash) for e in spans]
        manifest['evidence'] = {'span_count': len(spans), 'states': span_states,
                                'note': 'Revised-source spans may be stale; the production reader must report this honestly.'}
        checks['has_grounded_spans'] = bool(spans)
        checks['all_processed_episodes_cited'] = {ep for ep, state in snapshot(bank).items() if state['processed']}.issubset({e.episode for e in spans})
        checks['unique_claim_ids'] = len({c.id for c in current}) == len(current)
        checks['owned_commits'], manifest['commits'] = owned_commits(bank)
        checks['clean_bank'] = not git(bank, 'status', '--porcelain')
        indexer = vector_index.SqliteVecIndexer(bank)
        for kind in ('entities', 'episodes', 'claims'):
            info = indexer.index_info(kind)
            conn = indexer._connect()
            try:
                if kind == 'claims':
                    info['authoritative_current_count'] = sum(not c.valid_to and not c.superseded_by for c in current)
                info['count'] = conn.execute(f'SELECT count(*) FROM meta_{kind}').fetchone()[0]
            finally:
                conn.close()
            manifest['index'][kind] = info
        manifest['model_calls'] = fake.calls if fake else runtime.calls
        manifest['timings'] = runtime.timings
        manifest['embedding_calls'] = runtime.embedding_calls
        manifest['clock']['modules'] = runtime.clock_modules
        manifest['clock']['final'] = runtime.clock.isoformat()
    manifest['throughput'] = {'unique_episodes': len(snapshot(bank)),
        'input_bytes_on_disk': sum(p.stat().st_size for p in (bank / 'episodes').glob('*.md')),
        'attempted_extraction_calls': sum(c['stage'] == 'extraction' for c in manifest['model_calls'])}
    manifest['latency'] = {}
    for control, rows in manifest['controls'].items():
        values = sorted(row['wall_seconds'] for row in rows)
        manifest['latency'][control] = {'samples': len(values), 'p50_seconds': values[len(values)//2],
                                       'p95_seconds': values[-1], 'method': 'nearest-rank; service call wall time; no HTTP transport'}
    manifest['imports'] = sorted(name for name in sys.modules if name.startswith('benchmarks.'))
    if fake:
        checks['controls_correct'] = all(row['correct'] for rows in manifest['controls'].values() for row in rows)


def main():
    args = json.loads(sys.stdin.read())
    bank, home = Path(args['bank_dir']), Path(args['home'])
    # Defend the child entry point with the launcher's canonical ownership checks.
    bank, home = prepare_paths(str(bank), str(home))
    if os.environ.get('CICADA_HOME') != str(home) or os.environ.get('HOME') != str(home) or os.environ.get('CICADA_CAPTURE') != 'off':
        raise ValueError('launch through the isolated system runner')
    output = home / 'results'
    _no_symlinks(output)
    output.mkdir(mode=0o700, exist_ok=True)
    path = output / (uuid.uuid4().hex + '.json')
    started, cpu_start = time.perf_counter(), time.process_time()
    disk_start = disk_bytes(bank) + disk_bytes(home)
    manifest = {
        'schema': 1, 'code_revision': git(REPO, 'rev-parse', 'HEAD'),
        'code_dirty': bool(git(REPO, 'status', '--porcelain')),
        'code_hashes': {str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in [*Path(__file__).parent.glob('*.py'), REPO / 'api/services/claims.py', REPO / 'api/services/conflict_resolver.py']},
        'system': {'os': platform.platform(), 'machine': platform.machine(), 'processor': platform.processor(), 'cpu_count': os.cpu_count()},
        'engine': {'kind': args['engine'], 'production_route': 'codex' if args['engine'] == 'codex' else 'local-with-fake-completion', 'auth': 'none' if args['engine'] == 'fake' else 'subscription-only',
                   'model': args['model'], 'effort': args['effort']},
        'engine_stage_pins': {'consolidation': args['model'], 'disambiguation': args['model'], 'answers': args['model'], 'judge': None},
        'diagnostics': {'recovery_injections': {
            'kinds': ['pause', 'cancel', 'failure'] if args['engine'] == 'fake' else [],
            'subscription_transport_verified': False,
            'scope': 'Sleep resume after synthetic stage faults; not subscription breaker or semaphore validation'}},
        'embedding_model': args['config']['embedding_model'], 'settings': args['config'],
        'clock': {'initial': args['clock'], 'scope': 'benchmark-service-boundaries'},
        'dataset_hashes': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(FIXTURES.glob('*.json'))},
        'preset': args['preset'], 'integrity': {}, 'controls': {}, 'runs': [], 'index': {},
        'failures': [], 'resume_lineage': [], 'model_calls': [], 'timings': [],
        'grading': {'method': 'structural-exact-and-evidence' if args['engine'] == 'fake' else 'manual-ungraded',
                    'quality_claim': False, 'judge_calls': 0},
        'measurement': {'warm_cold': 'cold derived indexes at start; warmed in subsequent legs',
                        'stage_times': 'inclusive wrappers; nested index/commit times overlap Stage 5',
                        'memory': 'resource.getrusage(RUSAGE_SELF).ru_maxrss; no model-child RSS',
                        'provider_wait': 'included in model-call wall time; local/provider split unknown',
                        'retries': 'fake scenarios inject stage failures; transport retries unknown for subscription'},
        'out_of_scope': ['scenario-3', 'scenario-6', 'LoCoMo', 'LongMemEval', 'real-app-responsiveness'],
    }
    exit_code = 0
    try:
        asyncio.run(execute(args, manifest))
        if any(value is False for value in manifest['integrity'].values()):
            exit_code = 1
    except Exception as exc:
        import traceback
        traceback.print_exc()
        manifest['failures'].append({'fatal': type(exc).__name__, 'message': str(exc)})
        exit_code = 1
    finally:
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        manifest['resources'] = {'wall_seconds': time.perf_counter() - started,
                                 'cpu_seconds': time.process_time() - cpu_start,
                                 'child_cpu_seconds': resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime + resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime,
                                 'peak_rss_bytes': rss if sys.platform == 'darwin' else rss * 1024,
                                 'disk_growth_bytes': disk_bytes(bank) + disk_bytes(home) - disk_start}
        if 'throughput' in manifest:
            manifest['throughput']['unique_episodes_per_wall_second'] = manifest['throughput']['unique_episodes'] / manifest['resources']['wall_seconds']
        manifest['result'] = 'passed' if exit_code == 0 else 'failed'
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True, default=str) + '\n')
        path.chmod(0o600)
        print(json.dumps({'manifest': str(path), 'result': manifest['result']}))
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
