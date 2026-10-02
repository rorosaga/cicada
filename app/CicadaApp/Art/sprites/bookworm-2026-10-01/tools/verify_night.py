"""Independent all-frame dark-room contracts: colour only, never changed animation."""
import hashlib
import json
import tempfile
from pathlib import Path
from PIL import Image
from night_palette import palette_data, allowed_colors, rgba
from verify import ART, RES, BANNED, check, export

ROOM = ['room-backdrop', 'room-window', 'room-plant', 'room-lamp', 'room-beanbag', 'room-mug']
STATES = ['awake','sleeping','digesting','happy','curious','hungry','reading','error']
NIGHT = [f'bookworm-{state}-night-{light}' for state in STATES for light in ('dark','lit')]

def luma(p):return .2126*p[0]+.7152*p[1]+.0722*p[2]

def mean_channels(im):
    pixels=[p for p in im.get_flattened_data() if p[3]]
    check(pixels,'empty measured region')
    return {'luma':sum(luma(p) for p in pixels)/len(pixels),'warmth':sum(p[0]-p[2] for p in pixels)/len(pixels)}

def verify_night(report):
    from verify_room import load, tag_images
    data=palette_data();allowed=allowed_colors(data)
    check(not (BANNED & {r*65536+g*256+b for r,g,b,_ in allowed}), 'reserved derived hue')
    day_colors={rgba(c['hex']):c['key'] for c in data['colors']}
    ramps={k:[rgba(h) for h in r] for k,r in data['night']['ramps'].items()}
    light=json.loads((ART/'room-light-map.json').read_text())
    check((light['version'],light['cols'],light['rows'],light['origin'])==(1,160,64,'top-left'),'light-map lattice')
    for source,legal in [('moon',set('012')),('lamp',set('03456'))]:
        check(len(light[source])==64 and all(len(r)==160 and set(r)<=legal and set(r[110:])=={'0'} for r in light[source]),'light-map bands/pile')
        check(set(''.join(light[source]))==legal,'every light band used')
    plan=json.loads((ART/'room-plan.json').read_text())
    placements={l['sheet']:(l['x'],64-l['y']-l['h']) for l in plan['layers']}

    baseline=json.loads((ART/'day-art-contract.json').read_text())['sheets']
    check(len(baseline)==18,'day baseline coverage')
    for name,contract in baseline.items():
        if name=='room-weather':continue
        d,ims=load(name);ranges={t['name']:t for t in d['meta']['frameTags']}
        tags={t:{'ms':[f['duration'] for f in d['frames'][ranges[t]['from']:ranges[t]['to']+1]],
                 'pixels':[hashlib.sha256(im.tobytes()).hexdigest() for im in tag_images(d,ims,t)]} for t in contract['tags']}
        check(hashlib.sha256(json.dumps(tags,sort_keys=True,separators=(',',':')).encode()).hexdigest()==contract['dayTagsSha256'],name+': day art/timing unchanged')
        if name not in ROOM:
            for ext in ('png','json'):check(hashlib.sha256((RES/f'{name}.{ext}').read_bytes()).hexdigest()==contract[ext+'Sha256'],name+': original bytes unchanged')
    d,ims=load('room-weather')
    for tag,hash_ in baseline['room-weather']['preservedDayTags'].items():
        t=next(t for t in d['meta']['frameTags'] if t['name']==tag)
        actual={'ms':[f['duration'] for f in d['frames'][t['from']:t['to']+1]],'pixels':[hashlib.sha256(im.tobytes()).hexdigest() for im in tag_images(d,ims,tag)]}
        if tag=='rainy-day':
            # Dated 2026-10-02 timing amendment: strictly pin the new holds, then compare every
            # original pixel against the unchanged historical hash (which includes 80 ms holds).
            check(actual['ms']==[100]*48,'rainy-day: amended 100 ms holds')
            actual['ms']=[80]*48
        check(hashlib.sha256(json.dumps(actual,sort_keys=True,separators=(',',':')).encode()).hexdigest()==hash_,tag+': day sky unchanged')
    for tag in ('rainy-dusk','rainy-night'):
        t=next(t for t in d['meta']['frameTags'] if t['name']==tag)
        check([f['duration'] for f in d['frames'][t['from']:t['to']+1]]==[100]*48,tag+': amended 100 ms holds')

    def relight(im,position,lit,state=None):
        x,y=position;out=Image.new('RGBA',im.size)
        for py in range(im.height):
            for px in range(im.width):
                p=im.getpixel((px,py))
                if p[3]:
                    band=int(light['moon'][y+py][x+px])
                    if lit:band=max(band,int(light['lamp'][y+py][x+px]))
                    color=ramps[day_colors[p]][band]
                    q=data['night']['glyphs']['question'];box=q['box']
                    if state=='curious' and box['x']<=px<box['x']+box['w'] and box['y']<=py<box['y']+box['h']:
                        if day_colors[p]=='K':color=rgba(q['colors']['outline'])
                        if day_colors[p]=='W':color=rgba(q['colors']['core'])
                        check(luma(color)>=140,'question glyph readable')
                    out.putpixel((px,py),color)
        return out

    for p in RES.glob('*.json'):
        if p.name=='sprites.manifest.json':continue
        if p.stem not in ROOM+NIGHT:
            check(not any(t['name'].startswith('night-') for t in json.loads(p.read_text())['meta']['frameTags']),'unexpected night tag: '+p.stem)
    verified=0;glyphs=0;minimum_lid_contrast=255;minimum_page_contrast=255;counts={}
    with tempfile.TemporaryDirectory(dir=ART/'qa',prefix='night-verify-') as td:
        for state in STATES:
            day,original=load('bookworm-'+state)
            for lit in (False,True):
                name=f'bookworm-{state}-night-'+('lit' if lit else 'dark');night,frames=load(name)
                packed=Image.open(RES/f'{name}.png').convert('RGBA')
                check(packed.size==(night['meta']['size']['w'],night['meta']['size']['h']) and max(packed.size)<=2048,name+': packed size/texture budget')
                check(all(p[3] in (0,255) and (not p[3] or p in allowed) for p in packed.get_flattened_data()),name+': entire packed palette/alpha')
                for f in night['frames']:
                    r=f['frame']
                    check(0<=r['x'] and 0<=r['y'] and r['x']+r['w']<=packed.width and r['y']+r['h']<=packed.height,name+': packed frame bounds')
                check(night['meta']['frameTags']==day['meta']['frameTags'],name+': exact tags/ranges/direction')
                check(night['meta']['slices']==day['meta']['slices'],name+': exact slices')
                check(len(frames)==len(original),name+': frame count')
                check([f['duration'] for f in night['frames']]==[f['duration'] for f in day['frames']],name+': durations')
                check(all(f['sourceSize']=={'w':64,'h':48} and not f['trimmed'] and not f['rotated'] and f['frame']['w']==64 and f['frame']['h']==48 for f in night['frames']),name+': canvas')
                check(all(p[3] in (0,255) and (not p[3] or p in allowed) for im in frames for p in im.get_flattened_data()),name+': palette/alpha')
                for i,(a,b) in enumerate(zip(original,frames)):
                    check(b.tobytes()==relight(a,(36,7),lit,state).tobytes(),name+f': frame {i} relight')
                    check(a.getchannel('A').tobytes()==b.getchannel('A').tobytes(),name+': all-frame ruling-9 ink parity')
                    for y in range(48):
                        for x in range(64):
                            key=day_colors.get(a.getpixel((x,y)))
                            if key in ('Z','Y','X','q','Q'):
                                check(a.getpixel((x,y))==b.getpixel((x,y)),name+f': state glyph frame {i}');glyphs+=1
                            if key=='S':check(luma(b.getpixel((x,y)))>=60,name+': sweat readable')
                            if key=='P' and state=='reading':
                                neighbours=[b.getpixel((xx,yy)) for xx,yy in [(x-1,y),(x+1,y),(x,y-1),(x,y+1)] if 0<=xx<64 and 0<=yy<48 and day_colors.get(a.getpixel((xx,yy)))=='C']
                                if neighbours:
                                    contrast=max(luma(p)-luma(b.getpixel((x,y))) for p in neighbours)
                                    check(contrast>=8,name+f': open-book line contrast frame {i}')
                                    minimum_page_contrast=min(minimum_page_contrast,contrast)
                            if key=='j':
                                neighbours=[b.getpixel((xx,yy)) for xx,yy in [(x-1,y),(x+1,y),(x,y-1),(x,y+1)] if 0<=xx<64 and 0<=yy<48 and day_colors.get(a.getpixel((xx,yy))) in ('G','g')]
                                if neighbours:
                                    contrast=max(luma(p)-luma(b.getpixel((x,y))) for p in neighbours)
                                    check(contrast>=12,name+f': closed-eye contrast frame {i}');minimum_lid_contrast=min(minimum_lid_contrast,contrast)
                            if key=='K' and state=='error':
                                neighbours=[b.getpixel((xx,yy)) for xx,yy in [(x-1,y),(x+1,y),(x,y-1),(x,y+1)] if 0<=xx<64 and 0<=yy<48 and day_colors.get(a.getpixel((xx,yy)))=='G']
                                if neighbours:check(max(luma(p)-luma(b.getpixel((x,y))) for p in neighbours)>=18,name+': X/outline contrast')
                    verified+=1
                export(ART/'src'/f'{name}.aseprite',Path(td),name)
                for ext in ('png','json'):check((Path(td)/f'{name}.{ext}').read_bytes()==(RES/f'{name}.{ext}').read_bytes(),name+': deterministic '+ext)
                report['sheets'][name]={'frames':len(frames),'tags':len(night['meta']['frameTags']),**{ext+'Sha256':hashlib.sha256((RES/f'{name}.{ext}').read_bytes()).hexdigest() for ext in ('png','json')}}
                counts[name]=len(frames)
    for name in ROOM:
        d,ims=load(name)
        for lit in (False,True):
            base=('lit' if lit else 'dark') if name in ('room-backdrop','room-lamp') else 'idle'
            t=next(t for t in d['meta']['frameTags'] if t['name']==base);nt=next(t for t in d['meta']['frameTags'] if t['name']==('night-lit' if lit else 'night-dark'))
            check([f['duration'] for f in d['frames'][t['from']:t['to']+1]]==[f['duration'] for f in d['frames'][nt['from']:nt['to']+1]],name+': night timing')
            for a,b in zip(tag_images(d,ims,base),tag_images(d,ims,nt['name'])):check(b.tobytes()==relight(a,placements[name],lit).tobytes(),name+': exact night relight')
    from make_scenery_review import render_room, make_review
    renders={label:render_room('sleeping',time,base,lit) for label,time,base,lit in [('night-dark','night','sunny',False),('night-lit','night','sunny',True),('day-lit','day','sunny',True)]}
    regions={'lamp-wall':(0,14,18,34),'far-wall':(85,0,106,30),'plant':(21,42,33,64),'near-seat':(36,55,58,64),'near-worm':(42,25,58,42),'far-worm':(82,40,99,54),'sill':(18,37,58,41),'moon-floor':(30,58,65,64)}
    measured={label:{r:mean_channels(im.crop(rect)) for r,rect in regions.items()} for label,im in renders.items()}
    dark,lit,day=(measured[k] for k in ('night-dark','night-lit','day-lit'))
    for region in ('lamp-wall','plant','near-seat','near-worm'):
        check(lit[region]['luma']>dark[region]['luma']+8,region+': lamp luminance rise')
        check(lit[region]['warmth']>dark[region]['warmth']+12,region+': lamp warmth rise')
    for region in ('far-wall','far-worm'):
        check(lit[region]==dark[region],region+': outside pool unchanged')
        check(lit[region]['luma']<day[region]['luma']*.4,region+': room dark away from lamp')
    check(dark['sill']['luma']>dark['far-wall']['luma']+8,'window spill readable')
    check(dark['sill']['warmth']<0 and dark['moon-floor']['warmth']<0,'window spill cool')
    bd=load('room-backdrop');means={tag:sum(luma(p) for p in tag_images(*bd,tag)[0].get_flattened_data())/(110*64) for tag in ('dark','lit','night-dark','night-lit')}
    check(means['night-dark']<means['night-lit']<means['lit']*.6,'room well below day luminance')
    mug=load('room-mug');unlit_mug=tag_images(*mug,'night-dark')[0]
    check(max(luma(p) for p in unlit_mug.get_flattened_data() if p[3])<90,'far mug rim must not glow like the shade')
    report['night']={'framesVerified':verified,'framesPerSheet':counts,'stateGlyphPixelsVerified':glyphs,'minimumLidContrast':minimum_lid_contrast,'minimumPageLineContrast':minimum_page_contrast,'regions':measured,'backdropLuminance':means,'authoringKeys':len(data['colors']),'declaredRGBs':len(allowed),'daySheetsUnchanged':17,'preservedDaySkies':len(baseline['room-weather']['preservedDayTags']),'adaptedDaySkies':list(baseline['room-weather']['adaptedDayTags']),'unmodifiedSheetPairsByteIdentical':11}
    make_review()
    print(f'night: {verified} frames across sixteen worm sheets, marks/timing/alpha/ink/relight, six prop pairs and region checks OK')
