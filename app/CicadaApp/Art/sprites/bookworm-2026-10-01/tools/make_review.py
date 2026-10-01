#!/usr/bin/env python3
"""Build review plans and pixel-scale filmstrips from exported sheets (no drawing)."""
import json
from pathlib import Path
from PIL import Image, ImageDraw
ART=Path(__file__).resolve().parent.parent
RES=ART.parents[2]/'Sources/CicadaApp/Resources/sprites'
ORDER=['awake','reading','sleeping','digesting','happy','hungry','error','curious','small','small-dark']
plan=[]
keyframes={}
for state in ORDER:
    name='bookworm-'+state
    d=json.loads((RES/(name+'.json')).read_text())
    sheet=Image.open(RES/(name+'.png')).convert('RGBA')
    scale=8 if 'small' in state else 6
    keys=[]
    for tag in d['meta']['frameTags']:
        frames=[]
        for f in d['frames'][tag['from']:tag['to']+1]:
            r=f['frame'];frames.append((sheet.crop((r['x'],r['y'],r['x']+r['w'],r['y']+r['h'])),f['duration']))
        plan.append(dict(sheet=name,tag=tag['name'],first=tag['from']+1,ms=sum(ms for im,ms in frames),scale=scale))
        keys.append((tag['name'],frames[0][0]));keyframes[(state,tag['name'])]=frames[0][0]
        # Every frame at exact nearest-neighbour scale. Small pages keep the visual pass inspectable.
        for page,start in enumerate(range(0,len(frames),12)):
            chunk=frames[start:start+12];cw=chunk[0][0].width*scale+8;ch=chunk[0][0].height*scale+24
            out=Image.new('RGBA',(4*cw,((len(chunk)+3)//4)*ch),'#ECECEC');draw=ImageDraw.Draw(out)
            for i,(im,ms) in enumerate(chunk):
                x=i%4*cw;y=i//4*ch;draw.text((x+4,y+3),f'{start+i+1}: {ms}ms',fill='#292929')
                out.alpha_composite(im.resize((im.width*scale,im.height*scale),Image.Resampling.NEAREST),(x+4,y+20))
            directory=ART/'qa/filmstrips'/name;directory.mkdir(parents=True,exist_ok=True)
            out.save(directory/(tag['name']+f'-{page+1}@{scale}x.png'))
    for page,start in enumerate(range(0,len(keys),12),1):
        chunk=keys[start:start+12];cw=chunk[0][1].width*scale+8;ch=chunk[0][1].height*scale+24
        out=Image.new('RGBA',(4*cw,((len(chunk)+3)//4)*ch),'#ECECEC');draw=ImageDraw.Draw(out)
        for i,(label,im) in enumerate(chunk):
            x=i%4*cw;y=i//4*ch;draw.text((x+4,y+3),label,fill='#292929')
            out.alpha_composite(im.resize((im.width*scale,im.height*scale),Image.Resampling.NEAREST),(x+4,y+20))
        out.save(ART/'qa'/f'keys-{state}-{page}@{scale}x.png')
# Embed plan into a GUI script: native OpenFile/PlayAnimation actions, no document edits.
rows=['{sheet='+json.dumps(v['sheet'])+',tag='+json.dumps(v['tag'])+',first='+str(v['first'])+',ms='+str(v['ms'])+',scale='+str(v['scale'])+'}' for v in plan]
(ART/'qa/gui_review_plan.lua').write_text('return {\n'+',\n'.join(rows)+'\n}\n')
(ART/'qa/playback-plan.json').write_text(json.dumps(plan,indent=2)+'\n')
# Matching-size reference comparisons are review images, never sprite inputs.
comparisons=[('base','bookworm.png',keyframes[('awake','idle')]),
             ('happy','bookworm_happy.png',keyframes[('happy','idle')]),
             ('tired','bookworm_tired.png',keyframes[('hungry','idle')]),
             ('sad','bookworm_sad.png',keyframes[('awake','shake.center')]),
             ('worried','bookworm_worried.png',keyframes[('error','idle')])]
mad=Image.open(ART/'demo/bookworm-mad-demo@6x.gif').convert('RGBA')
comparisons.append(('mad','bookworm_mad.png',mad.resize((64,48),Image.Resampling.NEAREST)))
for label,ref,im in comparisons:
    raw=Image.open(ART/'reference'/ref).convert('RGBA')
    alpha=raw.getchannel('A').point(lambda a:255 if a>=128 else 0)
    bounds=alpha.getbbox();raw.putalpha(alpha);raw=raw.crop(bounds).resize((56,38),Image.Resampling.NEAREST)
    fitted=im.crop((4,10,60,48))
    out=Image.new('RGBA',(56*6*2+24,38*6+24),'#ECECEC');draw=ImageDraw.Draw(out)
    draw.text((4,3),label+' reference / saved-parts sprite',fill='#292929')
    out.alpha_composite(raw.resize((336,228),Image.Resampling.NEAREST),(4,20))
    out.alpha_composite(fitted.resize((336,228),Image.Resampling.NEAREST),(352,20))
    out.save(ART/'qa'/f'compare-{label}@6x.png')
print(f'{len(plan)} tag plans and all-frame filmstrips written')
