#!/usr/bin/env python3
"""Record and compare all delivered files around two full export_all.sh runs."""
import argparse
import hashlib
import json
from pathlib import Path

ART=Path(__file__).resolve().parent.parent
RES=ART.parents[2]/'Sources/CicadaApp/Resources/sprites'
REPO=ART.parents[4]
OUTPUT=ART/'qa/scenery-rebuild.json'

def snapshot():
    files=[*ART.glob('src/*.aseprite'),*ART.glob('parts/*.aseprite'),
           *RES.glob('*.png'),*RES.glob('*.json'),
           *(ART/name for name in ['palette.json','authoring-provenance.json','room-light-map.json','room-plan.json','room-motion.json','day-art-contract.json','preview.html','menubar.aseprite'])]
    return {str(p.relative_to(REPO)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['record','compare']);args=parser.parse_args()
    current=snapshot()
    if args.action=='record':
        OUTPUT.write_text(json.dumps({'firstExport':current},indent=2)+'\n')
        print(f'First complete export recorded: {len(current)} files')
    else:
        data=json.loads(OUTPUT.read_text());previous=data['firstExport']
        differences=sorted(p for p in previous.keys()|current.keys() if previous.get(p)!=current.get(p))
        data.update(secondExport=current,byteIdentical=not differences,filesCompared=len(current),differences=differences)
        OUTPUT.write_text(json.dumps(data,indent=2)+'\n')
        assert not differences,'Rebuild differs: '+', '.join(differences)
        print(f'Two complete exports: {len(current)} files byte-identical')

if __name__=='__main__':main()
