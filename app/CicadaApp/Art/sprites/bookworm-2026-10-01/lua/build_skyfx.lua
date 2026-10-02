-- Transparent Sleep moments, composed over the base weather and under the frame.
local H=require('ase_helpers');local R=require('room_common')
local ART=assert((app.params or {}).art);R.context(ART)
local C=require('scenery_common').context(ART)
local s=H.newSprite(36,32,R.pal,{'moment'});local rec=H.recorder(s);local records={}
local motion=H.readJson(app.fs.joinPath(ART,'room-motion.json'))
for _,time in ipairs({'day','dusk','night'}) do
  local name='mist-'..time;local n=36;rec:start(name)
  motion.tags[#motion.tags+1]={tag=name,elements={C.pos('mist.drift',n,function(i)return i,0 end,36,0)}}
  for i=0,n-1 do
    local im=H.image(36,32);local col=C.colors['mist.'..time]
    -- Two interrupted thin wisps: upper-right and lower-left clear panes, never a whiteout.
    for x=0,35 do
      local t=(x-i)%36
      if x>=20 and x<=34 and (t<13 or (t>=22 and t<29)) then im:drawPixel(x,6,col) end
      if x>=1 and x<=15 and ((t>=5 and t<=17) or t>=31) then
        im:drawPixel(x,23,col);if t%9>=3 and t%9<=5 then im:drawPixel(x,24,col) end
      end
    end
    rec:frame(300,{moment=im});records[#records+1]={note=name..'.'..i}
  end
  rec:stop()
end
for _,time in ipairs({'day','dusk'}) do
  local name='rainbow-'..time;local n=12;rec:start(name)
  -- A restrained two-position, one-pixel bright edge breath; the arc itself remains complete.
  motion.tags[#motion.tags+1]={tag=name,elements={C.pos('rainbow.edge.phase',n,function(i)return ({0,1,2,1})[math.floor(i/3)%4+1],0 end,0,0)}}
  for i=0,n-1 do
    local im=H.image(36,32)
    for y=3,19 do for x=1,35 do
      local distance=(x-20)^2+(y-18)^2
      local radius=math.floor(math.sqrt(distance)+.5)
      if radius>=10 and radius<=14 and y<=18 then
        local band=14-radius;local color=C.colors['rainbow.'..time..'.'..band]
        im:drawPixel(x,y,color)
      end
    end end
    -- A quiet edge glint cycles inside the arc, using its declared outer palette band.
    local phase=({0,1,2,1})[math.floor(i/3)%4+1]
    im:drawPixel(18+phase,7,C.colors['rainbow.'..time..'.1'])
    rec:frame(600,{moment=im});records[#records+1]={note=name..'.'..i}
  end
  rec:stop()
end
do
  local name='shootingstar-night';local n=48;rec:start(name)
  motion.tags[#motion.tags+1]={tag=name,elements={C.pos('shootingstar.phase',n,function(i)return i,0 end,48,0)}}
  for i=0,n-1 do
    local im=H.image(36,32)
    if i<8 then
      local x=5+i;local y=3+math.floor(i/2)
      im:drawPixel(x,y,C.colors.shootingstar)
      im:drawPixel(x-1,y-1,C.colors.shootingstar)
      im:drawPixel(x-2,y-1,app.pixelColor.rgba(H.hex(R.pal.hex[R.key('celestial.star.1')])) )
    end
    rec:frame(250,{moment=im});records[#records+1]={note=name..'.'..i}
  end
  rec:stop()
end
rec:apply();H.applyUsedPalette(s);R.finish(s,'room-skyfx',records)
H.writeJson(app.fs.joinPath(ART,'room-motion.json'),motion)
print('skyfx: three mist loops, two rainbow arcs, one occasional shooting star')
