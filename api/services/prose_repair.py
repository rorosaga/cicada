"""Read-only G194 inventory and resumable candidate generation. No apply path."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import uuid
from datetime import date

from api.services import claims, entity_body, entity_orientation as orientation
from api.services import markdown_parser, section_provenance, source_dates


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str) + '\n').encode()


def _no_symlinks(path: Path) -> None:
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('repair paths must not contain symlinks')


def paths(bank: Path, scratch: Path) -> tuple[Path, Path]:
    bank, scratch = Path(bank).absolute(), Path(scratch).absolute()
    _no_symlinks(bank)
    _no_symlinks(scratch)
    bank = bank.resolve(strict=True)
    scratch = scratch.resolve()
    if bank == scratch or bank.is_relative_to(scratch) or scratch.is_relative_to(bank):
        raise ValueError('bank and scratch must be disjoint directories')
    if not (bank / 'entities').is_dir():
        raise ValueError('bank must already contain entities')
    if scratch.exists():
        if not scratch.is_dir() or any(p.is_symlink() for p in scratch.rglob('*')):
            raise ValueError('scratch must be a directory without symlinks')
    scratch.mkdir(parents=True, exist_ok=True, mode=0o700)
    scratch.chmod(0o700)
    return bank, scratch


def _dirty(bank: Path) -> bool:
    if not (bank / '.git').exists():
        return False
    # Fixed read-only command; no locks or mutations, no model call while locked.
    result = subprocess.run(['git', '-C', str(bank), 'status', '--porcelain', '--untracked-files=all'],
                            capture_output=True, timeout=10, env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'})
    return result.returncode != 0 or bool(result.stdout.strip())


def _write(path: Path, value: dict) -> None:
    _no_symlinks(path)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.candidate-')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(_json(value))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _items(body: str) -> list[dict]:
    result = []
    for section, text in entity_body.parse_sections(claims.strip_claims_block(body)).items():
        if section not in ('Key Facts', 'History'):
            continue
        for item in entity_body._bullet_lines(text):
            result.append({'id': _hash((section + '\0' + item).encode()), 'section': section, 'text': item})
    return result


def _checkpoint(scratch: Path, manifest: dict) -> None:
    _write(scratch / 'manifest.json', manifest)
    _write(scratch / f"run-{manifest['run_id']}.json", manifest)


def _snapshot(bank: Path, path: Path, today: str) -> tuple[dict, dict]:
    _no_symlinks(path)
    raw = path.read_bytes()
    page = markdown_parser.parse(path)
    claims.raw_claim_entries(page.body)  # rejects repeated/malformed/open fences
    sections = entity_body.parse_sections(claims.strip_claims_block(page.body))
    if entity_body.has_human_prose(page.frontmatter, sections):
        raise ValueError('human_prose')
    if section_provenance.unavailable_sections(page.body, {}):
        raise ValueError('unreadable_prose')
    refs = page.frontmatter.get('source_episodes', []) or []
    if not isinstance(refs, list) or not all(isinstance(x, str) for x in refs):
        raise ValueError('invalid_sources')
    refs = set(refs)
    for entry in claims.raw_claim_entries(page.body):
        extra = entry.get('source_episodes', []) or []
        if not isinstance(extra, list) or not all(isinstance(x, str) for x in extra):
            raise ValueError('invalid_sources')
        refs.update(extra)
    sources, hashes = [], {}
    for source_id in sorted(refs):
        if not re.fullmatch(r'ep_[A-Za-z0-9_-]+', source_id):
            raise ValueError('invalid_source_id')
        source_path = bank / 'episodes' / f'{source_id}.md'
        _no_symlinks(source_path)
        source_raw = source_path.read_bytes()
        source = markdown_parser.parse(source_path)
        day = source_dates.episode_day({'id': source_id, **source.frontmatter})
        sources.append({'id': source_id, 'date': day.isoformat() if day else None, 'text': source.body})
        hashes[source_id] = _hash(source_raw)
    if not sources or not any(s['text'].strip() for s in sources):
        raise ValueError('missing_sources')
    data = orientation.context(page.body, name=str(page.frontmatter.get('name', path.stem)),
        entity_type=str(page.frontmatter.get('type', 'concept')), fields={}, today=today,
        source_dates=sorted({s['date'] for s in sources if s['date']}), sources=sources)
    data['items'] = _items(page.body)
    if orientation.bounded_prompt(data, repair=True) is None:
        raise ValueError('oversized_context')
    return {'page_hash': _hash(raw), 'source_hashes': hashes,
            'body': page.body, 'frontmatter': page.frontmatter}, data


def _candidate(snapshot: dict, data: dict, result: dict) -> tuple[dict, str]:
    if not isinstance(result, dict) or not orientation.valid_summary(result.get('summary')):
        raise ValueError('invalid_output')
    edits = result.get('dated_edits', [])
    if not isinstance(edits, list):
        raise ValueError('invalid_output')
    items = {i['id']: i for i in data['items']}
    sources = {s['id']: s for s in data['sources']}
    replacements = {}
    for edit in edits:
        if not isinstance(edit, dict):
            raise ValueError('invalid_output')
        item, source = items.get(edit.get('id')), sources.get(edit.get('source_id'))
        if not item or not source or not source['date'] or item['id'] in replacements:
            raise ValueError('invalid_output')
        if '\n' in item['text'] or sum(i['text'].splitlines()[0] == item['text'] for i in data['items']) != 1:
            raise ValueError('invalid_output')
        # Date annotation only: never authorize arbitrary fact rewriting from
        # a clipped paragraph. Require the complete original wording in source.
        if (edit.get('text') != source['date'] + ': ' + item['text']
                or item['text'] not in source['text'] or source_dates.parse_day(item['text'])):
            raise ValueError('invalid_output')
        replacements[item['id']] = edit['text']
    body = orientation.compose(snapshot['body'], {'type': data['type']}, result['summary'])
    sections = entity_body.parse_sections(claims.strip_claims_block(body))
    for item_id, replacement in replacements.items():
        item = items[item_id]
        sections[item['section']] = re.sub(
            r'(?m)^([ \t]*[-*][ \t]+)' + re.escape(item['text']) + r'$',
            lambda match: match[1] + replacement, sections[item['section']], count=1)
    body = claims.preserve_claims_blocks(snapshot['body'], entity_body.render_sections(sections))
    fm = copy.deepcopy(snapshot['frontmatter'])
    fm['layout_version'] = 2
    section_provenance.refresh(fm, snapshot['body'], body, {}, synthesized=True)
    return fm, body


def run(bank: Path, scratch: Path, *, generate: bool = False, settings=None, llm_fn=None,
        engine_id: str = '', max_pages: int = 20, max_calls: int = 0,
        token_budget: int = 0, max_output_tokens: int = 1000, today: str | None = None,
        entity_ids: list[str] | None = None) -> dict:
    """Free inventory by default. Generation requires explicit finite budgets.

    The input reservation is UTF-8 byte count (a conservative tokenizer bound)
    plus 1024 envelope tokens and max_output_tokens. This is a reservation,
    not a measured token charge; each invocation retains its own manifest.
    Providers receive max_tokens; call count remains the hard engine-independent cap.
    """
    if min(max_pages, max_output_tokens) < 1 or min(max_calls, token_budget) < 0:
        raise ValueError('budgets must be finite nonnegative integers')
    if generate and not engine_id:
        raise ValueError('generation requires an explicit engine identity')
    bank, scratch = paths(bank, scratch)
    if entity_ids is not None and (not entity_ids or len(set(entity_ids)) != len(entity_ids)
            or not all(isinstance(i, str) and re.fullmatch(r'[A-Za-z0-9_-]+', i) for i in entity_ids)):
        raise ValueError('entity selection requires unique safe ids')
    today = today or date.today().isoformat()
    date.fromisoformat(today)
    manifest = {'v': 1, 'run_id': uuid.uuid4().hex, 'mode': 'generate' if generate else 'inventory', 'calls': 0,
                'reserved_tokens': 0, 'pages': []}
    dirty = _dirty(bank)
    selected = ([bank / 'entities' / f'{i}.md' for i in entity_ids] if entity_ids is not None
                else sorted((bank / 'entities').glob('*.md')))
    for path in selected[:max_pages]:
        record = {'entity_id': path.stem, 'status': 'deferred'}
        manifest['pages'].append(record)
        if dirty:
            record['reason'] = 'dirty_bank'
            continue
        if not re.fullmatch(r'[A-Za-z0-9_-]+', path.stem):
            record['reason'] = 'invalid_entity_id'
            continue
        try:
            snapshot, data = _snapshot(bank, path, today)
        except (OSError, ValueError, claims.MalformedClaimsBlockError):
            record['reason'] = 'unsafe_or_incomplete_input'
            continue
        record.update(page_hash=snapshot['page_hash'], source_hashes=snapshot['source_hashes'])
        if not generate:
            record['status'] = 'eligible'
            continue
        prompt = orientation.bounded_prompt(data, repair=True)
        input_hash = _hash(_json({'snapshot': snapshot, 'prompt': prompt, 'engine_id': engine_id,
                                'max_output_tokens': max_output_tokens, 'version': orientation.PROMPT_VERSION}))
        destination = scratch / f'{path.stem}.candidate.json'
        try:
            cached = json.loads(destination.read_text())
            if cached.get('input_hash') == input_hash and cached.get('candidate_hash') == _hash(
                    _json({'body': cached['body'], 'frontmatter': cached['frontmatter']})):
                record.update(status='cached', candidate=str(destination))
                continue
        except (OSError, ValueError, KeyError, TypeError):
            pass
        reserve = len(prompt.encode()) + 1024 + max_output_tokens
        if manifest['calls'] >= max_calls or manifest['reserved_tokens'] + reserve > token_budget:
            record['reason'] = 'budget'
            continue
        if llm_fn is None:
            if settings is None or settings.llm_mode == 'auto':
                raise ValueError('generation requires explicit settings with no auto engine')
            from api.services.providers import resolve_llm_fn
            llm_fn = resolve_llm_fn(settings, model=settings.effective_consolidation_model,
                                    stage='rewrite', is_async=False)
        manifest['calls'] += 1
        manifest['reserved_tokens'] += reserve
        record['status'] = 'generating'
        _checkpoint(scratch, manifest)
        record['status'] = 'deferred'
        try:
            response = llm_fn(messages=[{'role': 'user', 'content': prompt}],
                             response_format={'type': 'json_object'}, max_tokens=max_output_tokens)
            text = (response['choices'][0]['message']['content'] if isinstance(response, dict)
                    else response.choices[0].message.content)
            if not isinstance(text, str) or len(text.encode()) > max_output_tokens * 16:
                raise ValueError('invalid_output')
            fm, body = _candidate(snapshot, data, json.loads(text))
        except (ValueError, TypeError, KeyError, AttributeError, IndexError):
            record['reason'] = 'invalid_output'
            continue
        except Exception:
            # Checkpoint prior pages, stop this run, never retry or choose another engine.
            record['reason'] = 'engine_failure'
            _checkpoint(scratch, manifest)
            raise
        try:
            latest, _ = _snapshot(bank, path, today)
        except (OSError, ValueError, claims.MalformedClaimsBlockError):
            latest = None
        if latest != snapshot or _dirty(bank):
            record['reason'] = 'changed_input'
            continue
        candidate = {'v': 1, 'entity_id': path.stem, 'input_hash': input_hash,
                     'page_hash': snapshot['page_hash'], 'source_hashes': snapshot['source_hashes'],
                     'engine_id': engine_id, 'prompt_version': orientation.PROMPT_VERSION,
                     'frontmatter': fm, 'body': body}
        candidate['candidate_hash'] = _hash(_json({'body': body, 'frontmatter': fm}))
        _write(destination, candidate)
        record.update(status='candidate', candidate=str(destination))
        _checkpoint(scratch, manifest)
    _checkpoint(scratch, manifest)
    return manifest
