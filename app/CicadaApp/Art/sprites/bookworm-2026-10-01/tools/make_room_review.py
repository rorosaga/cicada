#!/usr/bin/env python3
"""Review renders only, sourced from the bundled sheets; never edits their pixels."""
import json
from pathlib import Path
from PIL import Image, ImageDraw
ART=Path(__file__).resolve().parent.parent
RES=ART.parents[2]/'Sources/CicadaApp/Resources/sprites'
OUT=ART/'qa/composites'
WEATHER={'awake':'curtains','reading':'fair','sleeping':'night','digesting':'dawn','happy':'clear','hungry':'overcast','error':'storm'}
data={p.stem:json.loads(p.read_text()) for p in RES.glob('*.json') if p.name!='sprites.manifest.json'}
sheets={s:Image.open(RES/(s+'.png')).convert('RGBA') for s in data}
plan=json.loads((ART/'room-plan.json').read_text())

def frame(sheet,tag,index=0):
 t=next(t for t in data[sheet]['meta']['frameTags'] if t['name']==tag)
 r=data[sheet]['frames'][t['from']+index]['frame']
 return sheets[sheet].crop((r['x'],r['y'],r['x']+r['w'],r['y']+r['h']))

def composite(mood,lit):
 im=Image.new('RGBA',(160,64),'#ECECEC')
 for l in plan['layers']:
  if l['prop']=='fly' and not lit:continue
  tag=('lit' if lit else 'dark') if l['prop'] in ['backdrop','lamp'] else WEATHER[mood] if l['prop']=='pane' else 'buzz' if l['prop']=='fly' else 'idle'
  im.alpha_composite(frame(l['sheet'],tag),(l['x'],64-l['y']-l['h']))
 im.alpha_composite(frame('bookworm-'+mood,'idle'),(36,7))
 # Placeholder review pile; tint its body, light and shade masks individually.
 for i,kind in enumerate(['chat','page','note','video','other']):
  book=Image.new('RGBA',(24,12))
  for mask,color in zip(range(3),['#718391','#B1C2C9','#415663']):
   m=frame('room-spines',kind,mask).getchannel('A');book.alpha_composite(Image.composite(Image.new('RGBA',(24,12),color),Image.new('RGBA',(24,12)),m))
  w=42-i*3;spine=Image.new('RGBA',(w,7))
  spine.alpha_composite(book.crop((0,0,20,12)).resize((w-4,7),Image.Resampling.NEAREST))
  spine.alpha_composite(book.crop((20,2,24,9)),(w-4,0))
  im.alpha_composite(spine,(113,56-i*9))
 return im

def main():
 OUT.mkdir(parents=True,exist_ok=True)
 for mood in WEATHER:
  board=Image.new('RGBA',(1304,544),'#ECECEC');draw=ImageDraw.Draw(board)
  for row,k in enumerate([3,4]):
   for col,lit in enumerate([False,True]):
    im=composite(mood,lit).resize((160*k,64*k),Image.Resampling.NEAREST)
    im.save(OUT/f'{mood}-{"lit" if lit else "dark"}@{k}x.png')
    x,y=col*652,row*256;draw.text((x+6,y+5),f'{mood} / {WEATHER[mood]} / {"lit" if lit else "dark"} / {k}x',fill='black');board.alpha_composite(im,(x+6,y+22))
  board.save(OUT/f'{mood}-review.png')
 # The fly in its actual registration, with the lamp eight rows below its top.
 for page in range(4):
  board=Image.new('RGBA',(704,918),'#ECECEC');draw=ImageDraw.Draw(board)
  for j,fr in enumerate(data['room-fly']['frames'][page*12:(page+1)*12]):
   i=page*12+j;im=Image.new('RGBA',(20,34));im.alpha_composite(frame('room-lamp','lit'),(0,8))
   im.alpha_composite(frame('room-fly','buzz',i));x=(j%4)*176+4;y=(j//4)*306
   draw.text((x,y+3),f"{i+1}: {fr['duration']} ms",fill='black')
   board.alpha_composite(im.resize((160,272),Image.Resampling.NEAREST),(x,y+23))
  board.save(ART/f'qa/room-fly/buzz-lamp-frames-{page+1}@8x.png')
 board=Image.new('RGBA',(800,342),'#70818B');draw=ImageDraw.Draw(board)
 for k,kind in enumerate(['chat','page','note','video','other']):
  for j,label in enumerate(['body','light','shade']):
   x=k*160+4;y=j*114+20;draw.text((x,y-17),kind+'/'+label,fill='white')
   board.alpha_composite(frame('room-spines',kind,j).resize((144,72),Image.Resampling.NEAREST),(x,y))
 board.save(ART/'qa/room-spines-masks@6x.png')
 board=Image.new('RGBA',(7*54,58),'#ECECEC');draw=ImageDraw.Draw(board)
 for j,(mood,weather) in enumerate(WEATHER.items()):
  x=j*54+4;draw.text((x,3),weather,fill='black');board.alpha_composite(frame('room-weather',weather),(x,22))
 board.save(ART/'qa/room-weather-keys@1x.png')
 board=Image.new('RGBA',(328,86),'#ECECEC');draw=ImageDraw.Draw(board)
 for j,lit in enumerate([False,True]):
  x=j*164;draw.text((x+4,3),'Lit' if lit else 'Dark',fill='black');board.alpha_composite(composite('reading',lit),(x+4,20))
 board.save(ART/'qa/room-lamp-glow@1x.png')
 print('28 room composites at 3x/4x, seven review boards, 40 fly frames at 8x and all 15 spine masks at 6x')
if __name__=='__main__':main()
