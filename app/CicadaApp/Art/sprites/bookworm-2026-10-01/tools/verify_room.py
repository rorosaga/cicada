"""Independent room contracts, occlusion, motion, exports and QA renders."""
import json
import hashlib
import math
import re
import tempfile
from pathlib import Path
from PIL import Image, ImageChops, ImageDraw
from verify import ART, RES, check, run, export, crop_frame, contact, verify_gif, write_palette_gif
from night_palette import palette_data, allowed_colors

BASES=['sunny','cloudy','windy','rainy','curtains']
TIMES=['day','dusk','night']
WEATHER=[base+'-'+time for base in BASES for time in TIMES]
SKYFX=['mist-day','mist-dusk','mist-night','rainbow-day','rainbow-dusk','shootingstar-night']
CLOCK=['face','face-night','hour','hour-night','minute','minute-night','second','second-night']
CONTRACT = {
 'room-backdrop':((110,64),['dark','lit','night-dark','night-lit'],['glow']),
 'room-window':((40,38),['idle','night-dark','night-lit'],['glass']),
 'room-weather':((36,32),WEATHER,[]),
 'room-skyfx':((36,32),SKYFX,[]),
 'room-clock':((15,15),CLOCK,[]),
 'room-lamp':((18,50),['dark','lit','night-dark','night-lit'],['ink','shade']),
 'room-fly':((20,26),['buzz'],['ink']),
 'room-beanbag':((62,12),['idle','night-dark','night-lit'],['ink','seat']),
 'room-plant':((12,22),['idle','night-dark','night-lit'],['ink']),
 'room-mug':((8,9),['idle','night-dark','night-lit'],['ink']),
 'room-spines':((24,12),['chat','page','note','video','other'],[])}
WEATHER_MS={base+'-'+time:([500]*36 if base=='sunny' else [200]*72 if base=='cloudy' else [120]*36 if base=='windy' else [80]*48 if base=='rainy' else [600,300]*4) for base in BASES for time in TIMES}
WEATHER_MS['sunny-dusk']=[300]*36;WEATHER_MS['sunny-night']=[200]*24
FX_MS={tag:([300]*36 if tag.startswith('mist') else [600]*12 if tag.startswith('rainbow') else [250]*48) for tag in SKYFX}
CLOCK_MS={tag:[1000]*(1 if tag.startswith('face') else 60) for tag in CLOCK}
FLY_MS=[1200,80,60,60,90,90,80,60,60,60,80,90,60,60,70,90,80,60,60,70,90,80,60,60,70,90,80,60,70,90,600]+[70]*8+[120]

def load(name):
 d=json.loads((RES/f'{name}.json').read_text());sheet=Image.open(RES/f'{name}.png').convert('RGBA')
 return d,[crop_frame(sheet,f) for f in d['frames']]

def tag_images(data, images, name):
 t=next(t for t in data['meta']['frameTags'] if t['name']==name)
 return images[t['from']:t['to']+1]

def points(im):
 return {(x,y) for y in range(im.height) for x in range(im.width) if im.getpixel((x,y))[3]}

def scene_points(im,x,y):
 return {(x+px,y+im.height-1-py) for px,py in points(im)}

def bbox(points_):
 check(points_,'empty bounds');x,y=zip(*points_)
 return dict(x=min(x),y=min(y),w=max(x)-min(x)+1,h=max(y)-min(y)+1)

def verify_room(report,palette):
 legal=set('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!#$%&()*+,-/:;<=>?@[]^{}~')
 check(len(palette)<=87 and all(c['key'] in legal for c in palette),'palette key budget')
 check(len({c['hex'] for c in palette})==len(palette),'duplicate palette RGB')
 colors={tuple(bytes.fromhex(c['hex'][1:]))+(255,):c['role'] for c in palette}
 data=palette_data();allowed=allowed_colors(data)
 for c in palette:
  for ramp in data['scenery']['ramps'].values():colors[tuple(bytes.fromhex(ramp[c['key']][1:]))+(255,)]=c['role']
 for c in data['scenery']['colors']:colors[tuple(bytes.fromhex(c['hex'][1:]))+(255,)]=c['role']
 registry=json.loads((ART/'qa/room-registry.json').read_text())['sheets'];all_data={}
 from verify_night import STATES, NIGHT
 expected={f'bookworm-{s}' for s in STATES}|set(NIGHT)|{'bookworm-small'}|set(CONTRACT)
 check({p.stem for p in RES.glob('*.png')}==expected,'complete PNG coverage')
 check({p.stem for p in RES.glob('*.json') if p.name!='sprites.manifest.json'}==expected,'complete JSON coverage')
 with tempfile.TemporaryDirectory(dir=ART/'qa',prefix='room-verify-') as td:
  for name,(canvas,required_tags,required_slices) in CONTRACT.items():
   data,ims=load(name);all_data[name]=(data,ims)
   raw=(RES/f'{name}.json').read_text();check('/Users/' not in raw and '/private/' not in raw,name+': machine path')
   sheet=Image.open(RES/f'{name}.png').convert('RGBA');check(sheet.size==(data['meta']['size']['w'],data['meta']['size']['h']),name+': PNG size')
   check(max(sheet.size)<=2048,name+': side budget')
   check(all(p[3] in (0,255) and (not p[3] or p in allowed) for p in sheet.get_flattened_data()),name+': palette/alpha')
   check([t['name'] for t in data['meta']['frameTags']]==required_tags,name+': exact tags')
   for f in data['frames']:
    r=f['frame'];check(0<=r['x'] and 0<=r['y'] and r['x']+r['w']<=sheet.width and r['y']+r['h']<=sheet.height,name+': bounds')
    check((r['w'],r['h'])==canvas and (f['sourceSize']['w'],f['sourceSize']['h'])==canvas and not f['trimmed'] and not f['rotated'],name+': canvas/trim')
   slices={s['name']:s['keys'][0]['bounds'] for s in data['meta']['slices']}
   check(set(slices)==set(required_slices),name+': exact slices')
   check(all(len(s['keys'])==1 and s['keys'][0]['frame']==0 for s in data['meta']['slices']),name+': slice keys')
   if 'ink' in slices: check(slices['ink']==bbox(set.union(*(points(im) for im in ims))),name+': ink union')
   if name in ['room-lamp','room-backdrop']:
    changed={(x,y) for y in range(canvas[1]) for x in range(canvas[0]) if ims[0].getpixel((x,y))!=ims[1].getpixel((x,y))}
    check(slices['shade' if name=='room-lamp' else 'glow']==bbox(changed),name+': minimal difference slice')
   regtags={t['name']:t for t in registry[name]['tags']};keys=[]
   for t in data['meta']['frameTags']:
    label=name+'/'+t['name'];check(t['direction']=='forward' and t['from']<=t['to'] and t.get('repeat',0)==0,label+': direction')
    ms=[f['duration'] for f in data['frames'][t['from']:t['to']+1]];images=tag_images(data,ims,t['name'])
    want=WEATHER_MS[t['name']] if name=='room-weather' else FX_MS[t['name']] if name=='room-skyfx' else CLOCK_MS[t['name']] if name=='room-clock' else (FLY_MS if name=='room-fly' else [1000]*(3 if name=='room-spines' else 1))
    check(ms==want,label+': exact timing')
    check(ms==[f['ms'] for f in regtags[t['name']]['frames']],label+': registry timing')
    check([f['index'] for f in regtags[t['name']]['frames']]==list(range(t['from'],t['to']+1)),label+': registry indices')
    if len(ms)>1 and name not in ('room-spines','room-clock'): check(all(40<=m<=4000 for m in ms) and 400<=sum(ms)<=30000,label+': caps')
    if name in ('room-weather','room-skyfx'):check(len({im.tobytes() for im in images})>1,label+': actual pixel motion')
    out=ART/'qa'/name;out.mkdir(exist_ok=True);gif=out/f'{t["name"]}@6x.gif'
    if name!='room-clock':
     write_palette_gif(gif,images,ms,6);verify_gif(gif,images,ms,6)
    keys.append((t['name'],images[0]))
    # Every frame is inspectable; filmstrip pages avoid oversized unreadable boards.
    for start in range(0,len(images),12):
     cw,ch=canvas[0]*6+12,canvas[1]*6+26;b=Image.new('RGBA',(cw*4,ch*math.ceil(len(images[start:start+12])/4)),'#ECECEC');dr=ImageDraw.Draw(b)
     for j,im in enumerate(images[start:start+12]):
      x,y=j%4*cw,j//4*ch;dr.text((x+6,y+4),f'{start+j+1}: {ms[start+j]} ms',fill='black');b.alpha_composite(im.resize((canvas[0]*6,canvas[1]*6),Image.Resampling.NEAREST),(x+6,y+22))
     b.save(out/f'{t["name"]}-frames-{start//12+1}@6x.png')
   contact(name,keys)
   export(ART/'src'/f'{name}.aseprite',Path(td),name)
   for ext in ['png','json']:check((Path(td)/f'{name}.{ext}').read_bytes()==(RES/f'{name}.{ext}').read_bytes(),name+': deterministic '+ext)
   report['sheets'][name]={'frames':len(ims),'tags':len(required_tags),'pngSha256':hashlib.sha256((RES/f'{name}.png').read_bytes()).hexdigest(),'jsonSha256':hashlib.sha256((RES/f'{name}.json').read_bytes()).hexdigest()}
   print(f'{name}: {len(required_tags)} tags, {len(ims)} frames, contracts/GIFs/determinism OK')
 plan=json.loads((ART/'room-plan.json').read_text());check((plan['cols'],plan['rows'],plan['origin'])==(160,64,'bottom-left'),'room lattice')
 layers=plan['layers'];check([l['z'] for l in layers]==list(range(10)),'draw order')
 check([l['prop'] for l in layers]==['backdrop','clock','pane','skyfx','window','plant','lamp','fly','beanbag','mug'],'layer order')
 for l in layers:check(0<=l['x'] and 0<=l['y'] and l['x']+l['w']<=110 and l['y']+l['h']<=64,'plan bounds/pile')
 check(plan['worm']==dict(x=36,y=9,w=64,h=48) and plan['pile']==dict(x=110,y=0,w=50,h=52),'worm/pile plan')
 window,win=all_data['room-window'];glass=window['meta']['slices'][0]['keys'][0]['bounds'];check(glass==dict(x=2,y=2,w=36,h=32),'glass slice')
 check((18+glass['x'],23+38-glass['y']-glass['h'])==(20,27),'glass registration')
 bag=all_data['room-beanbag'][0];seat=next(s for s in bag['meta']['slices'] if s['name']=='seat')['keys'][0]['bounds'];check(seat['h']==1 and 12-1-seat['y']==9,'seat baseline')
 lamp=all_data['room-lamp'][1][0];lamp_scene=scene_points(lamp,0,0)
 fly=all_data['room-fly'][1]
 for i,im in enumerate(fly):
  pp=scene_points(im,0,32);check(len(pp)<=2 and (i!=0 or len(pp)>=1),'fly 0-2 pixels/key frame')
  check(all(not(20<=x<56 and 27<=y<59) and x<110 for x,y in pp),'fly glass/pile')
  record=registry['room-fly']['tags'][0]['frames'][i];p=record['parts'][0]
  check(bool(pp)!=record['hidden'],'fly shade occlusion agrees with saved frame')
  next_p=registry['room-fly']['tags'][0]['frames'][(i+1)%len(fly)]['parts'][0]
  check(abs(next_p['x']-p['x'])<=1 and abs(next_p['y']-p['y'])<=1,'fly continuous path including seam')
 check(any((x+dx,y+dy) in lamp_scene for x,y in scene_points(fly[0],0,32) for dx,dy in [(1,0),(-1,0),(0,1),(0,-1)]),'fly landed beside shade')
 report['flyPixels']=[len(points(im)) for im in fly]
 wd,weather=all_data['room-weather'];frame_mask=scene_points(win[0],18,23);visibility={}
 # Every mood, pose, beat, cover and transition is now reachable in every scenery.
 mask=set(frame_mask)
 for state in ['awake','sleeping','digesting','happy','curious','hungry','reading','error']:
  _,frames=load('bookworm-'+state)
  for im in frames:mask|=scene_points(im,36,9)
 from verify_clock import verify_clock
 verify_clock(report,all_data['room-clock'],plan,mask,lamp_scene)
 for tag in WEATHER:
  ratios=[]
  for i,im in enumerate(tag_images(wd,weather,tag)):
   celestial=set();cloud=set()
   for x,y in points(im):
    role=colors[im.getpixel((x,y))];p=(20+x,27+31-y)
    if role.startswith('celestial.'):celestial.add(p)
    if role.startswith('cloud.'):cloud.add(p)
   check(not(celestial&mask),f'{tag} frame {i}: celestial occluded {celestial&mask}')
   if cloud:check(len(cloud-mask)/len(cloud)>=.5,f'{tag} frame {i}: clouds hidden');ratios.append(len(cloud-mask)/len(cloud))
  visibility[tag]={'celestialVisible':True,'cloudMinVisible':min(ratios) if ratios else None}
 check(len({tag_images(wd,weather,t)[0].tobytes() for t in WEATHER})==15,'distinct scenery key frames')
 night_key=tag_images(wd,weather,'sunny-night')[0]
 check(sum(colors[p].startswith('celestial.moon.') for p in night_key.get_flattened_data())>=12,'night key moon')
 check(sum(colors[p].startswith('celestial.star.') for p in night_key.get_flattened_data())>=4,'night key stars')
 cloudy_key=tag_images(wd,weather,'cloudy-night')[0]
 check(sum(colors[p].startswith('cloud.') for p in cloudy_key.get_flattened_data())>=200,'cloudy night deck')
 curtain_values=[sum(.2126*p[0]+.7152*p[1]+.0722*p[2] for p in tag_images(wd,weather,'curtains-'+time)[0].get_flattened_data())/(36*32) for time in TIMES]
 check(curtain_values[0]>curtain_values[1]>curtain_values[2],'curtain time lighting')
 rain_stats={}
 for tag in ['rainy-day','rainy-dusk','rainy-night']:
  rain=tag_images(wd,weather,tag);values=[sum(.2126*p[0]+.7152*p[1]+.0722*p[2] for p in im.get_flattened_data())/(36*32) for im in rain];mean=sum(values)/len(values)
  check(max(abs(v-mean)/mean for v in values)<=.02,tag+': no luminance flash')
  rain_stats[tag]={'mean':mean,'min':min(values),'max':max(values),'maxDeviation':max(abs(v-mean)/mean for v in values)}
 report['rainLuminance']=rain_stats;report['visibility']=visibility
 fd,fx=all_data['room-skyfx'];fx_visibility={}
 for tag in SKYFX:
  ratios=[]
  for i,im in enumerate(tag_images(fd,fx,tag)):
   pp=points(im);check(len(pp)<=36*32*.35,tag+': overlay whiteout')
   scene=scene_points(im,20,27)
   celestial={(20+x,58-y) for x,y in pp if colors[im.getpixel((x,y))].startswith('celestial.')}
   check(not(celestial&mask),tag+': celestial hidden behind worm/frame')
   if pp:check(len(scene-mask)/len(scene)>=.5,tag+': overlay unreadable');ratios.append(len(scene-mask)/len(scene))
   time=tag.rsplit('-',1)[-1]
   for base in BASES:
    key=tag_images(wd,weather,base+'-'+time)[0]
    key_celestial={p for p in points(key) if colors[key.getpixel(p)].startswith('celestial.')}
    if key_celestial:check(len(key_celestial-pp)>=max(1,len(key_celestial)//4),tag+': hides base celestial key')
  fx_visibility[tag]={'minVisible':min(ratios) if ratios else 1,'maxOpaquePixels':max(len(points(im)) for im in tag_images(fd,fx,tag))}
 shooting=tag_images(fd,fx,'shootingstar-night');check(sum(not points(im) for im in shooting)>=len(shooting)*.75,'shooting star mostly empty')
 report['overlayVisibility']=fx_visibility
 motion=json.loads((ART/'room-motion.json').read_text())['tags'];check([t['tag'] for t in motion]==WEATHER+SKYFX,'motion tag coverage')
 for t in motion:
  n=len((WEATHER_MS|FX_MS)[t['tag']]);check(t['elements'],'motion moving element')
  for e in t['elements']:
   check(len(e['positions'])==len(e['steps'])==n,'motion step count')
   check(any(p!=e['positions'][0] for p in e['positions']),'motion element never changes')
   for i,(p,step) in enumerate(zip(e['positions'],e['steps'])):
    q=e['positions'][(i+1)%n]
    for axis in ['x','y']:
     w=e['wrap'][axis];check(type(w)==int and w>=0,'motion wrap');check(type(p[axis])==type(step[axis])==int,'motion integer')
     got=p[axis]+step[axis];check((got%w==q[axis]%w) if w else got==q[axis],f'motion seam {t["tag"]}/{e["name"]}/{i}')
    # Rain independently follows the specified -1,-1,-1,0 / +4 cadence, including the seam.
    if e['name'].startswith('rain.'):check(step==dict(x=-1 if i%4!=3 else 0,y=4),'rain cadence')
    if e['name'].startswith('cloud.'):
     slow=t['tag'].startswith('cloudy-') and e['name'].startswith('cloud.far.')
     check(step==dict(x=int(not slow or i%2==1),y=0),'cloud cadence including seam')
    if e['name'].startswith('leaf.'):
     check(step['x']==1,'leaf horizontal drift')
     check(step['y'] in (0,-1) or (p['x']==35 and q['x']==0 and step['y']==11),'leaf height reset at jamb')
 sd,spines=all_data['room-spines'];marks=[]
 for kind in ['chat','page','note','video','other']:
  masks=tag_images(sd,spines,kind)
  for im in masks:
   check(len({p for p in im.get_flattened_data() if p[3]})==1,'single mask colour')
   for x in range(20):check(len({im.getpixel((x,y)) for y in range(1,11)})==1,'spine vertical stretch')
   for y in range(12):check(len({im.getpixel((x,y)) for x in range(4,20)})==1,'spine horizontal stretch')
  marks.append(tuple(any(m.getpixel((x,y))[3] for m in masks[1:]) for y in range(4,7) for x in range(20,24)))
 check(len(set(marks))==5,'spine middle-three-row marks')
 report['paletteColors']=len(palette);report['bytes']=sum(p.stat().st_size for p in RES.iterdir() if p.suffix in ['.png','.json'])
 manifest=json.loads((RES/'sprites.manifest.json').read_text());entries=manifest['assets']
 check(len(entries)==len(expected) and {a['id'] for a in entries}==expected,'manifest complete coverage')
 for a in entries:
  required=['id','png','json','role','generator','script','source','authoring','date','licence','processing','pngSha256','jsonSha256']
  check(all(isinstance(a.get(k),str) and a[k] for k in required),'manifest required provenance')
  check(a['role'] in ['worm','worm-small','room','weather','skyfx','fly','spines'],'manifest role')
  check(bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}',a['date'])),'manifest date')
  for ext in ['png','json']:
   check(a[ext]==a['id']+'.'+ext,'manifest relative basename')
   check(a[ext+'Sha256']==hashlib.sha256((RES/a[ext]).read_bytes()).hexdigest(),'manifest hash '+a[ext])
   check(bool(re.fullmatch('[0-9a-f]{64}',a[ext+'Sha256'])),'manifest sha256 format')
  check((ART/a['source']).is_file() and (ART/a['script']).is_file(),'manifest source and script')
 for p in [*RES.glob('*.json'),ART/'palette.json',ART/'room-plan.json',ART/'room-motion.json']:
  check('/Users/' not in p.read_text() and '/private/' not in p.read_text(),'machine path in '+p.name)
 check(report['bytes']<=6*1024*1024,'sprite byte budget');report['roomChecks']='passed'
 decoded=sum(Image.open(p).width*Image.open(p).height for p in RES.glob('*.png'))
 check(decoded<=8388608,'decoded pixel budget');report['decodedPixels']=decoded
 print('room visibility, fly, storm, seams, spines, plan and budgets: OK')
