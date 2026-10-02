-- One-time hand correction record: run in the Aseprite GUI console under the
-- shared lock. Native 1px Pencil, exact palette colours; saved parts are truth.
local folder=app.fs.filePath(debug.getinfo(1,'S').source:sub(2));package.path=folder..'/?.lua;'..package.path
local H=require('ase_helpers');local E=require('error_eyes')
local ART=(app.params or {}).art or app.fs.joinPath(folder,'..')
local pal=H.paletteFromJson(app.fs.joinPath(ART,'palette.json'))
local s=app.open(app.fs.joinPath(ART,'parts/worm-parts.aseprite'));app.sprite=s
local frame={};local ranges={}
for _,t in ipairs(s.tags) do frame[t.name]=t.fromFrame.frameNumber;ranges[#ranges+1]={t.name,t.fromFrame.frameNumber,t.fromFrame.frameNumber} end
local function choose(n,clear)
 if not frame[n] then local f=s:newEmptyFrame();frame[n]=f.frameNumber;ranges[#ranges+1]={n,f.frameNumber,f.frameNumber} end
 app.sprite=s;app.frame=s.frames[frame[n]];app.layer=s.layers[1]
 if clear then H.setCel(s,s.layers[1],frame[n],H.image(64,48)) end
end
local function dot(x,y,k) app.useTool{tool='pencil',brush=Brush(1),color=pal.color[k],points={Point(x,y)}} end
local function line(x0,y0,x1,y1,k) app.useTool{tool='pencil',brush=Brush(1),color=pal.color[k],points={Point(x0,y0),Point(x1,y1)}} end
local function rect(x,y,w,h,k) for yy=y,y+h-1 do line(x,yy,x+w-1,yy,k) end end
local function stamp(rows,x,y,map) for j,r in ipairs(rows) do for i=1,#r do local k=r:sub(i,i);if k~='.' then dot(x+i-1,y+j-1,map and map[k] or k) end end end end
app.transaction('Worm review A2 A3 A4 A5 A6 native pencil corrections',function()
 for _,v in ipairs({'sit','sit.in1','sit.in2','sit.tail1','slump','slump.in1','slump.in2','crouch','stretch1','stretch2'}) do
  choose('body.'..v..'/torso')
  if v:find('slump') then
   line(37,32,39,32,'G');dot(31,33,'G');line(35,33,36,33,'G');line(40,33,41,33,'G')
  elseif v=='sit.in1' or v=='sit.in2' then line(37,30,39,30,'G') end
  if v=='crouch' then dot(24,46,'K') end
  choose('body.'..v..'/tail');local taildy=v=='sit.tail1' and -1 or 0
  line(55,32+taildy,57,32+taildy,'K');dot(58,33+taildy,'K')
  choose('body.'..v..'/head')
  local dy=v:find('slump') and 2 or (v=='crouch' and 1 or (v=='stretch1' and -1 or (v=='stretch2' and -2 or 0)))
  if v:find('in2') then dy=dy-1 end
  rect(22,18+dy,1,7,'K');rect(23,18+dy,1,7,'G');rect(30,18+dy,1,7,'G');rect(31,18+dy,1,7,'K')
  rect(10,17+dy,1,6,'K');rect(11,17+dy,1,6,'G')
  dot(19,19+dy,'K');dot(18,20+dy,'L');dot(35,18+dy,'K')
 end
 local function eyes(n,dx,dy,kind)
  choose('eyes.'..n,true);rect(11,17,4,6,'G');rect(23,18,8,7,'G')
  if kind=='error' then E.room(dot)
  elseif kind=='closed' then stamp({'j..j','.jj.'},11,20);stamp({'j......j','.jjjjjj.'},23,21)
  elseif kind=='happy' then line(12,19,13,19,'K');dot(11,20,'K');dot(14,20,'K');line(25,20,28,20,'K');dot(24,21,'K');dot(29,21,'K')
  else
   local k='K';local leftdx=dx<0 and -1 or 0
   rect(14+leftdx,19+math.max(0,dy),1,4,k);rect(13+leftdx,20+math.max(0,dy),1,2,k)
   if kind=='wide' then stamp({'.KK.','KKKK','KKKK','.KK.'},26+dx,19,{K=k}) else rect(26+dx,20+dy,3,3,k) end
   stamp({'W.','WW'},11,17);stamp({'.WW','WW.'},23,18)
   if kind=='wide' then dot(25,19,'W') end
   if kind=='half' or kind=='blink.half' then
    rect(11,17,4,kind=='half' and 2 or 3,'j');rect(23,18,8,kind=='half' and 2 or 4,'j')
    if kind=='half' then dot(23,19,'G');dot(30,19,'G') end
   end
  end
 end
 for _,g in ipairs({'center','left','right'}) do
  local dx=g=='left' and -2 or (g=='right' and 1 or 0)
  eyes(g,dx,0);eyes(g..'.far',dx,-1)
  eyes(g=='center' and 'up' or 'up.'..g,dx,-1);if g~='center' then eyes('up.'..g..'.far',dx,-2) end
  eyes(g=='center' and 'error' or 'error.'..g,dx,0,'error')
  eyes(g=='center' and 'half' or 'half.'..g,dx,0,'half');eyes('half.'..g..'.far',dx,-1,'half')
  -- Wide pupil fits only centrally/right-0. Hungry perk retains its gaze and lid.
  eyes('wide.'..g,math.max(-2,math.min(0,dx)),0,'wide')
 end
 eyes('up.center.far',0,-2);eyes('wide',0,0,'wide');eyes('blink.half',0,0,'blink.half');eyes('closed',0,0,'closed');eyes('happy',0,0,'happy')
 for row=0,2 do for i=0,3 do local suffix=row==0 and '' or (row==1 and 'b' or 'c');local name='down.l'..i..suffix
  eyes(name,i-2,row==0 and 1 or 2)
  if row==2 then rect(23,18,8,1,'j');rect(11,17,4,1,'j') end
 end end
 local brows={
 happy={{13,8,'KKK'},{12,9,'KKKKK'},{11,10,'KK...KK'},{11,11,'K.....K'},{28,6,'KKKK'},{27,7,'KKKKKK'},{26,8,'KK....KK'},{33,9,'K'},{34,10,'K'}},
 tired={{12,10,'KKKKKK'},{10,11,'KKKKKKK'},{29,8,'KKKK'},{31,9,'KKKK'},{33,10,'KKK'}},
 sad={{19,8,'KK'},{18,9,'KKKK'},{16,10,'KKKK'},{15,11,'KKK'},{27,6,'KK'},{27,7,'KKKK'},{29,8,'KKKK'},{30,9,'KKK'}},
 worried={{18,8,'KK'},{17,9,'KKK'},{16,10,'KKKK'},{15,11,'KKK'},{25,12,'KKKK'}},
 mad={{12,8,'KKK'},{12,9,'KDDK'},{13,10,'KKDDK'},{14,11,'KKDDK'},{16,12,'KKDK'},{18,13,'KK'},{30,8,'KKK'},{30,9,'KDDK'},{28,10,'KDDKK'},{26,11,'KDKK'}},none={}}
 brows.curious={};for _,p in ipairs(brows.happy) do if p[1]<20 then brows.curious[#brows.curious+1]=p end end;for _,p in ipairs(brows.tired) do if p[1]>20 then brows.curious[#brows.curious+1]=p end end
 for _,n in ipairs({'none','happy','sad','tired','worried','mad','curious'}) do for _,offset in ipairs({0,-1}) do
  choose('brows.'..n..(offset==0 and '' or '+1'),true);for _,p in ipairs(brows[n]) do stamp({p[3]},p[1],p[2]+offset+(n=='mad' and (p[1]<20 and -1 or -3) or 0)) end
 end end
 local mouths={talk1={26,29,{'rrr','rrr','KKK'}},talk2={26,29,{'rrrr','rrrr','rrrr','.KK.'}},gulpOpen={25,29,{'rrrrr','rrrrr','rrrrr','rrrrr','.KKK.'}},yawn={24,29,{'.rrrr.','rrrrrr','rrrrrr','rrrrrr','.rrrr.','..KK..'}},chew1={26,29,{'rrr','KKK'}},chew2={26,29,{'rrrr','rrrr','.KK.'}}}
 for n,p in pairs(mouths) do choose('mouth.'..n,true);stamp(p[3],p[1],p[2]) end
 local drop={'..K..','.KSK.','KSSSK','KWSSK','KSSSK','.KKK.'}
 for i=1,8 do choose('fx.sweat.d'..i,true)
  if i==1 then stamp({'KS'},33,11) elseif i==2 then stamp({'KSS','KSS'},33,11)
  elseif i<=6 then stamp(drop,35,9+i-3)
  elseif i==7 then stamp({'..K..','.KSK.','.KSK.','.KSK.','..K..'},35,13)
  else stamp({'S','S'},37,16) end
 end
end)
-- Recreate tags last: newly appended parts must not grow the old last tag.
for i=#s.tags,1,-1 do s:deleteTag(s.tags[i]) end
for _,t in ipairs(ranges) do H.tag(s,t[1],t[2],t[3]) end
H.assertPalette(s,pal);app.command.SaveFile();choose('eyes.center');if app.isUIAvailable then app.editor.zoom=8;app.refresh() end
print('Worm fix face saved: native palette Pencil; '..#s.tags..' parts')
