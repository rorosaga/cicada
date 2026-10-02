local H=require('ase_helpers');local R=require('room_common')
local ART=(app.params or {}).art or app.fs.joinPath(H.scriptDir(),'..');R.context(ART)
dofile(app.fs.joinPath(ART,'lua/seed_room_parts.lua'))
local function static(name,w,h,layers,tags,slices)
 local s=H.newSprite(w,h,R.pal,layers);local rec=H.recorder(s);local frames={}
 for _,tag in ipairs(tags) do rec:start(tag.name);local cels={};local parts={}
  for layer,part in pairs(tag.parts) do cels[layer]=R.part(part,w,h);parts[#parts+1]={part=part,layer=layer,x=0,y=0} end
  rec:frame(1000,cels);frames[#frames+1]={parts=parts};rec:stop()
 end
 rec:apply();if name~='room-backdrop' and name~='room-window' then H.addSlice(s,'ink',H.spriteInk(s)) end
 for key,rect in pairs(slices or {}) do H.addSlice(s,key,rect) end
 if #tags==2 then H.addSlice(s,name=='room-backdrop' and 'glow' or 'shade',R.diff(H.flatten(s,1),H.flatten(s,2))) end
 R.finish(s,name,frames)
end
static('room-backdrop',110,64,{'wall','floor','trim','glow'},
 {{name='dark',parts={wall='wall',floor='floor',trim='trim'}},{name='lit',parts={wall='wall',floor='floor',trim='trim',glow='glow'}}})
static('room-window',40,38,{'frame','sill'},{{name='idle',parts={frame='window.frame',sill='window.sill'}}},{glass={x=2,y=2,w=36,h=32}})
static('room-lamp',18,50,{'lamp','light'},{{name='dark',parts={lamp='lamp.dark'}},{name='lit',parts={lamp='lamp.dark',light='lamp.light'}}})
static('room-beanbag',62,12,{'bag'},{{name='idle',parts={bag='bag'}}},{seat={x=4,y=2,w=54,h=1}})
static('room-plant',12,22,{'plant'},{{name='idle',parts={plant='plant'}}})
static('room-mug',8,9,{'mug'},{{name='idle',parts={mug='mug'}}})
-- x/y are top-left on the 20x26 canvas. Holds make this small route dart,
-- hesitate, loop back across itself, descend behind the shade and land on its rim.
local path={
 {8,7,1200,false},{8,6,80,true},
 {9,5,60},{10,4,60},{11,3,90},{12,3,90},{13,4,80},{13,5,60},
 {12,6,60},{11,6,60},{10,5,80},{10,4,90},{11,3,60},{12,2,60},
 {13,2,70},{14,1,90},{15,2,80},{16,3,60},{15,4,60},{15,5,70},
 {14,6,90},{14,7,80},{15,8,60},{16,9,60},{17,10,70},{18,11,90},
 {18,12,80},{17,13,60},{17,14,70},{16,15,90},
 {16,16,600,false},
 {15,15,70},{14,14,70},{13,13,70},{12,12,70},{11,11,70},{10,10,70},{9,9,70},{8,8,70},
 {8,7,120,false}}
assert(#path==40)
local shade=R.part('lamp.dark',18,50)
local s=H.newSprite(20,26,R.pal,{'fly'});local rec=H.recorder(s);rec:start('buzz');local frames={}
for i,p in ipairs(path) do
 local x,y,ms,glint=table.unpack(p);if glint==nil then glint=i%2==0 end
 -- Fly scene y=32+26-1-y; lamp scene y=50-1-r, so lamp r=y-8.
 local behind=y>=8 and y<20 and x<18 and app.pixelColor.rgbaA(shade:getPixel(x,y-8))>0
 local im=H.image(20,26)
 if not behind then R.px(im,x,y,'fly.body.0');if glint then R.px(im,x-1,y-1,'fly.wing.0') end end
 rec:frame(ms,{fly=im});frames[i]={parts={{part='fly',x=x,y=y}},glint=glint,hidden=behind}
end
rec:stop();rec:apply();H.addSlice(s,'ink',H.spriteInk(s));R.finish(s,'room-fly',frames)
H.writeJson(app.fs.joinPath(ART,'room-plan.json'),{
 cols=160,rows=64,origin='bottom-left',layers={
 {prop='backdrop',sheet='room-backdrop',x=0,y=0,w=110,h=64,z=0},
 {prop='pane',sheet='room-weather',x=20,y=27,w=36,h=32,z=1},
 {prop='window',sheet='room-window',x=18,y=23,w=40,h=38,z=2},
 {prop='plant',sheet='room-plant',x=21,y=0,w=12,h=22,z=3},
 {prop='lamp',sheet='room-lamp',x=0,y=0,w=18,h=50,z=4},
 {prop='fly',sheet='room-fly',x=0,y=32,w=20,h=26,z=5},
 {prop='beanbag',sheet='room-beanbag',x=36,y=0,w=62,h=12,z=6},
 {prop='mug',sheet='room-mug',x=100,y=0,w=8,h=9,z=7}},
 worm={x=36,y=9,w=64,h=48},pile={x=110,y=0,w=50,h=52}})
print('room: props, glow, fly and plan built')
