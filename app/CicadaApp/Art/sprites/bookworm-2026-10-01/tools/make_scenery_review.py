"""Offline pixel composites; no app, browser, bank or GUI is involved."""
import json
from functools import lru_cache
from PIL import Image, ImageDraw
from verify import ART

@lru_cache(maxsize=None)
def sheet(name):
    from verify_room import load
    return load(name)

def frame(name,tag,index=0):
    from verify_room import tag_images
    d,frames=sheet(name);images=tag_images(d,frames,tag)
    return images[index%len(images)]

def render_room(mood,time,base,lit,overlay=None,index=0):
    plan=json.loads((ART/'room-plan.json').read_text())
    dark=time=='night' or base=='rainy';im=Image.new('RGBA',(160,64))
    for l in plan['layers']:
        prop=l['prop']
        if prop=='fly' and not lit:continue
        if prop=='clock':
            suffix='-night' if dark else ''
            for tag,i in [('face',0),('hour',50),('minute',8),('second',30)]:
                im.alpha_composite(frame(l['sheet'],tag+suffix,i),(l['x'],64-l['y']-l['h']))
            continue
        if prop=='skyfx':
            if not overlay:continue
            tag=overlay
        elif prop=='pane':tag=base+'-'+time
        elif prop=='fly':tag='buzz'
        elif dark:tag='night-lit' if lit else 'night-dark'
        else:tag=('lit' if lit else 'dark') if prop in ('lamp','backdrop') else 'idle'
        im.alpha_composite(frame(l['sheet'],tag,index),(l['x'],64-l['y']-l['h']))
    name='bookworm-'+mood+('-night-'+('lit' if lit else 'dark') if dark else '')
    im.alpha_composite(frame(name,'idle',index),(36,7))
    return im

def board(pictures,path,scale,cols):
    w=max(im.width for _,im in pictures)*scale+12;h=max(im.height for _,im in pictures)*scale+24
    out=Image.new('RGBA',(w*cols,h*((len(pictures)+cols-1)//cols)),'#171B2B');draw=ImageDraw.Draw(out)
    for i,(label,im) in enumerate(pictures):
        x=i%cols*w;y=i//cols*h;draw.text((x+6,y+4),label,fill='#DADFFF')
        out.alpha_composite(im.resize((im.width*scale,im.height*scale),Image.Resampling.NEAREST),(x+6,y+20))
    out.save(path)

def make_review():
    from verify_night import STATES
    directory=ART/'qa/scenery';directory.mkdir(exist_ok=True)
    rooms=[]
    for time in ('day','dusk','night'):
        for base in ('sunny','rainy'):
            for lit in (False,True):
                label=f'{time}-{base}-'+('lit' if lit else 'dark');im=render_room('reading',time,base,lit)
                for scale in (1,3,6):im.resize((160*scale,64*scale),Image.Resampling.NEAREST).save(directory/f'room-{label}@{scale}x.png')
                rooms.append((label,im))
    board(rooms,directory/'room-matrix@3x.png',3,4)
    keys=[]
    for base in ('sunny','cloudy','windy','rainy','curtains'):
        for time in ('day','dusk','night'):
            tag=base+'-'+time;im=frame('room-weather',tag);im.resize((216,192),Image.Resampling.NEAREST).save(directory/f'weather-{tag}@6x.png');keys.append((tag,im))
    board(keys,directory/'weather-keys@6x.png',6,3)
    short={'sunny':'Su','cloudy':'Cl','windy':'Wi','rainy':'Ra','curtains':'Cu'}
    native=[(short[label.split('-')[0]]+'-'+{'day':'D','dusk':'Du','night':'N'}[label.split('-')[1]],im) for label,im in keys]
    board(native,directory/'weather-keys@1x.png',1,3)
    overlay_pictures=[]
    for overlay in ('mist-day','mist-dusk','mist-night','rainbow-day','rainbow-dusk','shootingstar-night'):
        time=overlay.rsplit('-',1)[-1]
        for base in ('sunny','rainy'):
            im=render_room('sleeping' if overlay.startswith('mist') else 'digesting',time,base,True,overlay)
            label=base+'-'+overlay;im.resize((480,192),Image.Resampling.NEAREST).save(directory/f'overlay-{label}@3x.png');overlay_pictures.append((label,im))
    board(overlay_pictures,directory/'overlay-matrix@3x.png',3,4)
    clocks=[]
    for dark in (False,True):
        suffix='-night' if dark else ''
        for hour,minute,second in [(0,0,0),(3,15,30),(10,8,45),(6,42,12)]:
            im=frame('room-clock','face'+suffix).copy()
            for tag,i in [('hour',(hour%12)*5+minute//12),('minute',minute),('second',second)]:im.alpha_composite(frame('room-clock',tag+suffix,i))
            clocks.append((f'{"night" if dark else "day"} {hour:02}:{minute:02}:{second:02}',im))
    board(clocks,directory/'clock-dials@6x.png',6,4)
    for lit in (False,True):
        pictures=[]
        for state in STATES:
            name=f'bookworm-{state}-night-'+('lit' if lit else 'dark');d,ims=sheet(name)
            idle=next(t for t in d['meta']['frameTags'] if t['name']=='idle')
            indices=[idle['from'],idle['from']+(idle['to']-idle['from'])//3,idle['from']+2*(idle['to']-idle['from'])//3,idle['to']]
            if state=='happy':
                cheer=next(t for t in d['meta']['frameTags'] if t['name']=='cheer.center');indices[-1]=cheer['from']+2
            for i in indices:pictures.append((f'{state} #{i}',ims[i]))
            board(pictures[-4:],directory/f'worm-{state}-{"lit" if lit else "dark"}@6x.png',6,4)
        board(pictures,directory/('worm-states-'+('lit' if lit else 'dark')+'@6x.png'),6,4)
    (directory/'render-paths.json').write_text(json.dumps(sorted(str(p.relative_to(ART)) for p in directory.glob('*.png')),indent=2)+'\n')
    print('scenery review: 12 room combinations, 15 sky keys, 12 overlay composites, 64 night worm samples')

if __name__=='__main__':make_review()
