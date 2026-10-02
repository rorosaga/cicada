-- Separate dial and whole-pixel hands. The app chooses an angle; these are not loops.
local H=require('ase_helpers');local R=require('room_common')
local ART=assert((app.params or {}).art);R.context(ART)
local data=H.readJson(app.fs.joinPath(ART,'palette.json'))
local colors={};for key,hex in pairs(data.clock.colors) do colors[key]=app.pixelColor.rgba(H.hex(hex)) end
local s=H.newSprite(15,15,R.pal,{'dial','hand'});local rec=H.recorder(s);local frames={}
local function endpoint(i,length)
 local a=i*math.pi/30
 return 7+math.floor(math.sin(a)*length+.5),7+math.floor(-math.cos(a)*length+.5)
end
for _,night in ipairs({false,true}) do
 local suffix=night and '-night' or '';local ink=night and app.pixelColor.rgba(H.hex(data.night.ramps.K[1])) or R.pal.px.K
 local dial=H.image(15,15)
 for p in dial:pixels() do
  local distance=(p.x-7)^2+(p.y-7)^2
  if distance<=49 then p(colors[(distance<=36 and 'face' or 'rim')..suffix]) end
 end
 for i=0,55,5 do local x,y=endpoint(i,5);dial:drawPixel(x,y,ink) end
 dial:drawPixel(7,7,ink)
 rec:start('face'..suffix);rec:frame(1000,{dial=dial});rec:stop();frames[#frames+1]={parts={}}
end
for _,kind in ipairs({'hour','minute','second'}) do
 for _,night in ipairs({false,true}) do
  local suffix=night and '-night' or ''
  local hex=kind=='second' and data.clock.colors['second'..suffix] or night and data.night.ramps.K[1] or R.pal.hex.K
  local pal=H.palette({{'k',hex}});rec:start(kind..suffix)
  for i=0,59 do
   local im=H.image(15,15);local x,y=endpoint(i,({hour=3,minute=5,second=6})[kind])
   H.line(im,7,7,x,y,pal,'k');rec:frame(1000,{hand=im});frames[#frames+1]={parts={{part=kind,x=x,y=y}}}
  end
  rec:stop()
 end
end
rec:apply();H.applyUsedPalette(s);R.finish(s,'room-clock',frames)
print('clock: day/night dials and 60 angles for each black/black/red hand')
