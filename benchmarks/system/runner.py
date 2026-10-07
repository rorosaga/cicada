"""Standard-library-only launcher: establish isolation BEFORE importing Cicada."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

MARKER = 'cicada-system-benchmark-v1'
REPO = Path(__file__).resolve().parents[2]


def _no_symlinks(path: Path, *, allow_internal: bool = False) -> None:
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('benchmark paths must not contain a symlink')
    if path.exists():
        for child in path.rglob('*'):
            if child.is_symlink() and not (allow_internal and child.resolve().is_relative_to(path)):
                raise ValueError('benchmark directories must not contain an escaping symlink')


def _owned(value: str, marker: str, *, parent: Path | None = None) -> Path:
    if value == 'temp':
        path = Path(tempfile.mkdtemp(prefix='cicada_bench_', dir=parent)).resolve()
        (path / marker).write_text(json.dumps({'kind': MARKER}) + '\n')
    else:
        path = Path(value).expanduser().absolute()
        _no_symlinks(path, allow_internal=marker == '_bench_home.yaml')
        path = path.resolve(strict=True)
        try:
            data = json.loads((path / marker).read_text())
        except (OSError, ValueError) as exc:
            raise ValueError(f'path requires a runner-owned {marker} marker (use temp)') from exc
        if data != {'kind': MARKER}:
            raise ValueError(f'invalid {marker} ownership marker')
    if marker == '_bench_home.yaml' and (path / '.env').exists():
        raise ValueError('benchmark home must not contain .env')
    return path


def prepare_paths(bank_dir: str, home_dir: str, *, parent: Path | None = None) -> tuple[Path, Path]:
    # Validate an explicit bank first: refusal has no import or home side effect.
    bank = _owned(bank_dir, '_bench.yaml', parent=parent)
    home = _owned(home_dir, '_bench_home.yaml', parent=parent)
    if bank == home or bank.is_relative_to(home) or home.is_relative_to(bank):
        raise ValueError('bank and benchmark home must be disjoint directories')
    return bank, home


def isolated_env(bank: Path, home: Path, engine: str) -> dict[str, str]:
    # Do not copy os.environ and then attempt to enumerate every possible secret.
    env = {k: os.environ[k] for k in ('PATH', 'TMPDIR', 'LANG', 'LC_ALL', 'SYSTEMROOT') if k in os.environ}
    env.update({
        'HOME': str(home), 'CICADA_HOME': str(home),
        'CICADA_MEMORY_PATH': str(bank), 'CICADA_CAPTURE': 'off',
        'CICADA_LLM_MODE': 'codex' if engine == 'codex' else 'local',
        'CICADA_EMBEDDING_MODE': 'local', 'PYTHON_DOTENV_DISABLED': '1',
        'CICADA_ALLOW_CONNECTOR_FETCH': 'off', 'CICADA_ALLOW_FEED_FETCH': 'off',
        'CICADA_ALLOW_LOGO_FETCH': 'off', 'CICADA_TELEMETRY': 'off',
        'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
        'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
        'PYTHONPATH': str(REPO), 'PYTHONHASHSEED': '0',
    })
    return env


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bank-dir', required=True, help='temp or an existing runner-owned marked directory')
    p.add_argument('--home', required=True, help='temp or an existing marked benchmark home')
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--clock', required=True, help='aware ISO-8601 timestamp; fixture dates are relative to it')
    p.add_argument('--model', required=True)
    p.add_argument('--effort', required=True, choices=('low', 'medium', 'high', 'xhigh', 'max'))
    p.add_argument('--preset', choices=('small',), default='small')
    p.add_argument('--engine', choices=('fake', 'codex'), default='fake')
    p.add_argument('--validate-only', action='store_true')
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        clock = datetime.fromisoformat(args.clock.replace('Z', '+00:00'))
        if clock.tzinfo is None:
            raise ValueError('--clock must include a timezone')
        if not args.model.strip() or args.model.startswith('-'):
            raise ValueError('--model must be an explicit model id')
        bank, home = prepare_paths(args.bank_dir, args.home)
        config_path = args.config.expanduser().absolute()
        _no_symlinks(config_path)
        config_path = config_path.resolve(strict=True)
        if config_path.is_relative_to(bank) or config_path.is_relative_to(home):
            raise ValueError('config must be outside both bank and home')
        config = json.loads(config_path.read_text())
        if not isinstance(config, dict) or set(config) != {'batch_size', 'embedding_model'} or type(config['batch_size']) is not int or config['batch_size'] != 2:
            raise ValueError('small config requires batch_size=2 and embedding_model only')
        if not isinstance(config['embedding_model'], str) or not config['embedding_model'].strip():
            raise ValueError('embedding_model must be explicit')
        if args.engine == 'fake' and (args.model != 'deterministic-v1' or config['embedding_model'] != 'fake-hash-v1'):
            raise ValueError('fake engine requires --model deterministic-v1 and embedding_model=fake-hash-v1')
        if args.engine == 'codex' and config['embedding_model'] == 'fake-hash-v1':
            raise ValueError('subscription runs require a real local embedding model')
        launch = {**vars(args), 'bank_dir': str(bank), 'home': str(home),
                  'config': config, 'clock': clock.isoformat()}
        if args.validate_only:
            print(json.dumps({'validated': True, **launch}, sort_keys=True))
            return 0
        # No private state is consulted to populate credentials. The later pilot
        # must sign in explicitly in this isolated home using Cicada's adapter.
        return subprocess.run(
            [sys.executable, '-P', '-m', 'benchmarks.system.workload'],
            input=json.dumps(launch), text=True, cwd=home,
            env=isolated_env(bank, home, args.engine), check=False,
        ).returncode
    except (OSError, ValueError) as exc:
        print(f'benchmark refused: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
