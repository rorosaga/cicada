#!/usr/bin/env python3
"""List Run B deliverables and persistent QA writes, excluding build/cache files."""
from pathlib import Path

ART=Path(__file__).resolve().parent.parent
ROOT=ART.parents[4]
RES=ART.parents[2]/'Sources/CicadaApp/Resources/sprites'

def main():
    cutoff=min(p.stat().st_mtime for p in (ART/'qa').glob('run-b-*') if p.is_file())
    paths=[]
    for directory in [ART,RES]:
        for path in directory.rglob('*'):
            if not path.is_file() or '__pycache__' in path.parts or 'reference' in path.parts:
                continue
            if path.stat().st_mtime>=cutoff:
                paths.append(path.relative_to(ROOT).as_posix())
    inventory=(ART/'RUN_B_FILES.txt').relative_to(ROOT).as_posix()
    paths=sorted(set(paths)|{inventory})
    heading='Run B: authored, exported and persistent QA files. Worktree-relative paths.\n'
    heading+='Frozen worm sheet exports were regenerated with identical bytes; their pixels were not changed.\n'
    heading+='References, compiler outputs, Python caches and removed temporary verifier files are excluded.\n\n'
    (ART/'RUN_B_FILES.txt').write_text(heading+'\n'.join(paths)+'\n')
    print(f'Run B inventory: {len(paths)} persistent files')

if __name__=='__main__':main()
