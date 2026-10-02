"""Shared palette schema reader: authoring keys and keyless derived light bands."""
import json
import re
from pathlib import Path

ART = Path(__file__).resolve().parent.parent
BANDS = ['shadow', 'moon-edge', 'moon', 'lamp-edge', 'lamp-low', 'lamp-mid', 'lamp-hot']

def rgba(hex_):
    assert re.fullmatch(r'#[0-9A-F]{6}', hex_), 'invalid declared palette hex'
    return tuple(bytes.fromhex(hex_[1:])) + (255,)

def palette_data():
    data = json.loads((ART / 'palette.json').read_text())
    night = data['night']
    assert night['version'] == 1 and night['bands'] == BANDS, 'night palette schema/bands'
    assert set(night['ramps']) == {c['key'] for c in data['colors']}, 'night ramp key coverage'
    assert all(len(ramp) == len(BANDS) for ramp in night['ramps'].values()), 'night ramp band coverage'
    assert night['glyphs']['question']['box']=={'x':45,'y':16,'w':4,'h':9}, 'question mark registration'
    scenery=data['scenery']
    assert scenery['version']==1 and set(scenery['ramps'])=={'dusk','night'}, 'scenery palette schema'
    assert all(set(ramp)==set(night['ramps']) for ramp in scenery['ramps'].values()), 'scenery ramp key coverage'
    assert len({c['id'] for c in scenery['colors']})==len(scenery['colors']), 'scenery colour ids'
    assert data['clock']['version']==1 and set(data['clock']['colors'])=={'face','face-night','rim','rim-night','second','second-night'}, 'clock palette schema'
    return data

def allowed_colors(data):
    return ({rgba(c['hex']) for c in data['colors']} | {rgba(h) for r in data['night']['ramps'].values() for h in r}
            | {rgba(h) for h in data['night']['glyphs']['question']['colors'].values()}
            | {rgba(h) for r in data['scenery']['ramps'].values() for h in r.values()}
            | {rgba(c['hex']) for c in data['scenery']['colors']}
            | {rgba(h) for h in data['clock']['colors'].values()})
