#!/usr/bin/env python3
"""Read-only prose inventory/candidates. Deliberately has no apply command."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bank', type=Path, required=True)
    parser.add_argument('--scratch', type=Path, required=True)
    parser.add_argument('--generate', action='store_true', help='make review candidates; never write the bank')
    parser.add_argument('--engine', choices=('local', 'byok', 'agent', 'codex'))
    parser.add_argument('--model')
    parser.add_argument('--max-pages', type=int, default=20)
    parser.add_argument('--entity-id', action='append', help='repeat to select a pilot by explicit ids')
    parser.add_argument('--max-calls', type=int, default=0)
    parser.add_argument('--token-budget', type=int, default=0)
    parser.add_argument('--max-output-tokens', type=int, default=1000)
    args = parser.parse_args(argv)
    if args.generate and (not args.engine or not args.model or args.max_calls < 1 or args.token_budget < 1):
        parser.error('--generate requires engine, model, positive max-calls and token-budget')
    bank, scratch = args.bank.absolute(), args.scratch.absolute()
    # Standard-library-only validation BEFORE imports that resolve Cicada paths.
    for path in (bank, scratch):
        if any(p.is_symlink() for p in (path, *path.parents)):
            parser.error('bank/scratch paths must not contain symlinks')
    bank, scratch = bank.resolve(strict=True), scratch.resolve()
    if bank == scratch or bank.is_relative_to(scratch) or scratch.is_relative_to(bank):
        parser.error('bank and scratch must be disjoint directories')
    scratch.mkdir(parents=True, exist_ok=True, mode=0o700)
    if any(p.is_symlink() for p in scratch.rglob('*')):
        parser.error('scratch must not contain symlinks')
    home = scratch / 'runtime'
    home.mkdir(exist_ok=True, mode=0o700)
    os.environ.update(HOME=str(home), CICADA_HOME=str(home), CICADA_MEMORY_PATH=str(bank),
                      CICADA_CAPTURE='off', CICADA_ALLOW_CONNECTOR_FETCH='off',
                      CICADA_ALLOW_FEED_FETCH='off', CICADA_ALLOW_LOGO_FETCH='off')
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from api.config import Settings
    from api.services.source_rewrite import generate_prose_candidates
    settings = Settings(_env_file=None, llm_mode=args.engine or 'local',
                        consolidation_model=args.model or '')
    if args.engine == 'local' and args.model:
        settings.ollama_model = args.model
    result = generate_prose_candidates(bank, scratch, generate=args.generate, settings=settings,
        engine_id=f'{args.engine}:{args.model}' if args.generate else '', max_pages=args.max_pages,
        max_calls=args.max_calls, token_budget=args.token_budget, max_output_tokens=args.max_output_tokens,
        entity_ids=args.entity_id)
    # stdout is ids/enums/counts; review prose exists only in private scratch files.
    print(json.dumps({'calls': result['calls'], 'reserved_tokens': result['reserved_tokens'],
                      'pages': [{k: v for k, v in p.items() if k in ('entity_id', 'status', 'reason')}
                                for p in result['pages']]}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
