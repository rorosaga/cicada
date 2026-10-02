local H=require('ase_helpers');local R=require('room_common')
local ART=(app.params or {}).art or app.fs.joinPath(H.scriptDir(),'..');R.context(ART)
local C=require('scenery_common').context(ART)
local s=H.newSprite(36,32,R.pal,{'sky','far','near','fx','glass'});local rec=H.recorder(s)
local frames={};local motion={tags={}}
local function wrapped(dst,src,x,y)
 -- Horizontal wrapping at the jamb; never interpolate or blend a pixel.
 for it in src:pixels() do if app.pixelColor.rgbaA(it())>0 then dst:drawPixel((x+it.x)%36,(y+it.y)%32,it()) end end
end
local pos=C.pos
local function sky(tag)
 local im=H.image(36,32);local group='weather.sky.'..tag
 local bands=({night={0,1,2},dawn={0,1,2},clear={0,1,2},fair={0,1,1},overcast={0,1,1},storm={0,1,1}})[tag]
 if tag=='curtains' then R.rect(im,0,0,36,32,'weather.curtain.0');return im end
 R.rect(im,0,0,36,10,group..'.'..bands[1]);R.rect(im,0,10,36,12,group..'.'..bands[2]);R.rect(im,0,22,36,10,group..'.'..bands[3]);return im
end
local round=R.part('cloud.round',12,4);local thin=R.part('cloud.thin',13,2)
local sun=R.part('sun',7,7);local moon=R.part('moon',7,8)
local rayPos={{{0,-5},{0,5},{-5,0},{5,0}},{{-4,-4},{4,-4},{-4,4},{4,4}},{{-2,-5},{5,-2},{2,5},{-5,2}}}
local function rays(im,phase,cx,cy)
 for _,p in ipairs(rayPos[phase+1]) do R.px(im,cx+p[1],cy+p[2],'celestial.sun.0') end
end
local rainPoints={{1,1},{8,3},{17,0},{27,2},{34,5},{3,8},{12,6},{20,9},{29,7},{6,13},{15,11},{24,14},{33,12},{0,18},{9,17},{18,16},{28,19},{35,21},{4,24},{13,22},{22,25},{31,23},{7,29},{16,27},{25,30},{34,28},{2,31},{11,1},{21,4},{30,10},{5,20},{19,31}}
local stars={{2,3},{5,11},{14,2},{14,12},{22,2},{27,4},{33,2},{24,9},{2,13}}
for _,base in ipairs({'sunny','cloudy','windy','rainy','curtains'}) do
for _,time in ipairs({'day','dusk','night'}) do
 local spec=({sunny={'clear',36,500},cloudy={'fair',72,200},windy={'overcast',36,120},rainy={'storm',48,80},curtains={'curtains',8,0}})[base]
 if base=='sunny' and time=='dusk' then spec={'dawn',36,300} end
 if base=='sunny' and time=='night' then spec={'night',24,200} end
 local tag,n,ms=table.unpack(spec);local name=base..'-'..time;local m={tag=name,elements={}};motion.tags[#motion.tags+1]=m
 local function add(name,fn,wx,wy) m.elements[#m.elements+1]=pos(name,n,fn,wx,wy) end
 if tag=='night' then for j,p in ipairs(stars) do add('star.'..j..'.phase',function(i)return (math.floor((i+(j-1)*2)/6))%4,0 end,4,0) end
 elseif tag=='dawn' or tag=='clear' then add('cloud.a',function(i)return (19+i)%36,tag=='dawn' and 3 or 1 end,36,0);add('cloud.b',function(i)return (2+i)%36,tag=='dawn' and 7 or 10 end,36,0);add('rays.phase',function(i)return math.floor(i/(tag=='dawn' and 3 or 4))%(tag=='dawn' and 2 or 3),0 end,tag=='dawn' and 2 or 3,0)
 elseif tag=='fair' then add('cloud.near',function(i)return (4+i)%36,6 end,36,0);add('cloud.far.a',function(i)return (23+math.floor(i/2))%36,3 end,36,0);add('cloud.far.b',function(i)return (1+math.floor(i/2))%36,5 end,36,0)
 elseif tag=='overcast' then add('cloud.streak',function(i)return (2+i)%36,6 end,36,0);add('cloud.streak.second',function(i)return (23+i)%36,time=='night' and 5 or 11 end,36,0);add('tree.lean',function(i)return ({0,1,2,1})[math.floor(i/3)%4+1],0 end,0,0)
  -- A leaf resets its height only in the blank edge interval (x=34,35,0).
  -- Visible travel is +1 x each frame, -1 y every third frame.
  for j=1,3 do add('leaf.'..j,function(i)local t=(i+j*12)%36;return t,29-math.floor(t/3) end,36,0) end
 elseif tag=='storm' then
  for j=0,31 do add('rain.'..j,function(i)return (rainPoints[j+1][1]-math.floor((i+1)*3/4))%36,(rainPoints[j+1][2]+i*4)%32 end,36,32) end
  for j=0,3 do add('glass.drop.'..j,function(i)local t=(i+j*12)%48;return 3+j*8, t<8 and 12 or (12+math.floor((t-8)/2)) end,0,0) end
 else add('hem',function(i)return 0,({0,1,2,1,0,-1,-2,-1})[i+1] end,0,0) end
 if time=='night' and (base=='cloudy' or base=='windy') then
  for j,p in ipairs(stars) do add('star.'..j..'.phase',function(i)return math.floor((i+(j-1)*2)/3)%4,0 end,4,0) end
 end
 rec:start(name)
 for i=0,n-1 do
  local far=H.image(36,32);local near=H.image(36,32);local fx=H.image(36,32);local glass=H.image(36,32)
  if tag=='night' then
   H.paste(far,moon,7,3)
   for j,p in ipairs(stars) do local phase=math.floor((i+(j-1)*2)/6)%4;local col=phase==2 and 'celestial.star.1' or 'celestial.star.0'
    R.px(fx,p[1],p[2],col)
    if phase==0 then R.px(fx,p[1]-1,p[2],col);R.px(fx,p[1]+1,p[2],col);R.px(fx,p[1],p[2]-1,col);R.px(fx,p[1],p[2]+1,col) end
   end
  elseif tag=='dawn' then
   -- The horizon is in the upper-left pane, before the transom. Lower half is sky glow.
   local half=H.image(7,4);H.paste(half,sun,0,0);H.paste(far,half,5,9)
   R.line(far,0,13,16,13,'weather.sky.dawn.2');R.line(far,1,14,15,14,'weather.sky.dawn.2')
   R.px(fx,4,8,'celestial.sun.0');R.px(fx,12,8,'celestial.sun.0');R.px(fx,8+(math.floor(i/3)%2),7,'celestial.sun.1')
   wrapped(near,thin,(19+i)%36,3);wrapped(near,thin,(2+i)%36,7)
  elseif tag=='clear' or tag=='fair' then
   if time=='night' then H.paste(far,moon,7,3) else H.paste(far,sun,5,4) end
   if time=='night' and base=='cloudy' then
    for x=0,35 do R.rect(far,x,5+math.floor(x/8)%3,1,8,'cloud.0') end
   end
   if tag=='clear' then rays(fx,math.floor(i/4)%3,8,7);wrapped(near,round,(19+i)%36,1);wrapped(near,round,(2+i)%36,10)
   else wrapped(far,thin,(23+math.floor(i/2))%36,3);wrapped(far,thin,(1+math.floor(i/2))%36,5);wrapped(near,round,(4+i)%36,6) end
   for x=0,35 do local y=29+(x%9<3 and 1 or (x%9<6 and 0 or 2));R.rect(far,x,y,1,32-y,'room.leaf.1') end
  elseif tag=='overcast' then
   wrapped(far,thin,(2+i)%36,6);wrapped(far,thin,(23+i)%36,time=='night' and 5 or 11)
   local lean=({0,1,2,1})[math.floor(i/3)%4+1];H.paste(near,R.part('tree.'..lean,14,14),0,18)
   for j=1,3 do local t=(i+j*12)%36;local x,y=t,29-math.floor(t/3)
    if x>0 and x<34 then R.px(fx,x,y,'room.leaf.2');R.px(fx,x+1,y,'room.leaf.1') end
   end
  elseif tag=='storm' then
   -- Heavy static banks. Rain is behind glass, glass tracks are brighter and slower.
   for x=0,35 do R.rect(far,x,0,1,4+(math.floor(x/4)%3),'weather.sky.storm.0') end
   for j=0,31 do local x=(rainPoints[j+1][1]-math.floor((i+1)*3/4))%36;local y=(rainPoints[j+1][2]+i*4)%32
    R.px(fx,x,y,'weather.rain.0');R.px(fx,(x-1)%36,(y+1)%32,'weather.rain.0')
   end
   for j=0,3 do local t=(i+j*12)%48;local x=3+j*8;local y=t<8 and 12 or (12+math.floor((t-8)/2))
    R.px(glass,x,y,'weather.rain.1');if t>=4 then R.px(glass,x,y+1,'weather.rain.1') end
    if t>=8 then R.px(glass,x,y-1,'weather.rain.0') end
   end
  else
   local hem=({0,1,2,1,0,-1,-2,-1})[i+1]
   R.rect(near,0,0,17,28,'weather.curtain.1');R.rect(near,19,0,17,28,'weather.curtain.1')
   for x=0,35 do if x~=17 and x~=18 then
    local endY=29+((x%6<3) and hem or -hem);R.rect(near,x,0,1,math.min(32,endY),'weather.curtain.'..(x%6<2 and 0 or 1))
   end end
   R.line(glass,17,0,17,31,'room.lampWarm.1')
  end
  if time=='night' and (base=='cloudy' or base=='windy') then
   if base=='windy' then H.paste(far,moon,7,3) end
   for j,p in ipairs(stars) do
    local phase=math.floor((i+(j-1)*2)/3)%4;local col=phase==2 and 'celestial.star.1' or 'celestial.star.0'
    R.px(fx,p[1],p[2],col)
    if phase==0 then R.px(fx,p[1]-1,p[2],col);R.px(fx,p[1]+1,p[2],col);R.px(fx,p[1],p[2]-1,col);R.px(fx,p[1],p[2]+1,col) end
   end
   -- Stars are behind the passing cloud deck, visible only through clear sky.
   local cloud0=R.pal.px[R.key('cloud.0')];local cloud1=R.pal.px[R.key('cloud.1')]
   local star0=R.pal.px[R.key('celestial.star.0')];local star1=R.pal.px[R.key('celestial.star.1')]
   for p in fx:pixels() do
    if p()==star0 or p()==star1 then
     local a,b=far:getPixel(p.x,p.y),near:getPixel(p.x,p.y)
     if a==cloud0 or a==cloud1 or b==cloud0 or b==cloud1 then p(0) end
    end
   end
  end
  local duration=tag=='curtains' and ({600,300,600,300,600,300,600,300})[i+1] or ms
  rec:frame(duration,{sky=C.tint(sky(tag),time),far=C.tint(far,time),near=C.tint(near,time),fx=C.tint(fx,time),glass=C.tint(glass,time)});frames[#frames+1]={note=name..'.'..i,parts={{part=name,x=0,y=0}}}
 end
 rec:stop()
end
end
rec:apply();H.applyUsedPalette(s);H.writeJson(app.fs.joinPath(ART,'room-motion.json'),motion);R.finish(s,'room-weather',frames)
print('weather: fifteen time/base loops with exact periodic positions')
