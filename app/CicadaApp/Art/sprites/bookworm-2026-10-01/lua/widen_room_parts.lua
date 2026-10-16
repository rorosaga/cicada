-- 2026-10-16 (the Sleep room after #305): the room's wall, floor and trim span the whole 160-column lattice.
-- The backdrop used to stop at column 110 and leave the pile's 50 columns to the card behind it; with the card
-- gone, the pile stood on bare page ground. This one-off widens the SAVED parts (which own the pixels) once:
-- columns 0-107 are kept as authored, 108-157 continue the wall, floor and skirting from column 107 with the
-- same seams at the same spacing, and the corner trim (old 108-109) moves to 158-159. The glow is unchanged.
-- Idempotent: a 160-wide parts file is left alone.
local H=require('ase_helpers');local R=require('room_common')
local ART=(app.params or {}).art or app.fs.joinPath(H.scriptDir(),'..');R.context(ART)
local path=app.fs.joinPath(ART,'parts/room-parts.aseprite')
local s=assert(app.open(path))
if s.width==160 then s:close();print('room parts already 160 wide');return end
assert(s.width==110 and s.height==64,'unexpected room parts canvas '..s.width..'x'..s.height)
local OLD,NEW,EDGE=110,160,108   -- EDGE: the first column of the old corner trim
local frames={}
for _,t in ipairs(s.tags) do
  if t.name=='wall' or t.name=='floor' or t.name=='trim' or t.name=='glow' then
    frames[t.name]={frame=t.fromFrame.frameNumber,image=H.flatten(s,t.fromFrame.frameNumber)}
  end
end
for _,name in ipairs({'wall','floor','trim','glow'}) do assert(frames[name],'missing part '..name) end
s:crop(0,0,NEW,s.height)
local function widened(old)
  local im=H.image(NEW,old.height)
  for y=0,old.height-1 do
    for x=0,EDGE-1 do im:drawPixel(x,y,old:getPixel(x,y)) end
    for x=EDGE,NEW-(OLD-EDGE)-1 do im:drawPixel(x,y,old:getPixel(EDGE-1,y)) end
    for x=EDGE,OLD-1 do im:drawPixel(x+NEW-OLD,y,old:getPixel(x,y)) end
  end
  return im
end
local function seam(im,x,y,len,color) for i=0,len-1 do im:drawPixel(x+i,y,color) end end
-- Wall: plaster seams every 19 columns (3, 22, … 98) carry on at 117 and 136 on every seam row.
local wall=widened(frames.wall.image)
local plain=frames.wall.image:getPixel(0,4)
for y=0,63 do
  local mark=frames.wall.image:getPixel(3,y)
  if mark~=plain and app.pixelColor.rgbaA(mark)>0 and frames.wall.image:getPixel(0,y)==plain then
    for _,x in ipairs({117,136}) do seam(wall,x,y,4,mark) end
  end
end
-- Floor: the boards' butt joints carry on in each course (upper course 17, 46, 80 → 114, 148; lower 31 → 131).
local floor=widened(frames.floor.image)
local joint=frames.floor.image:getPixel(17,57)
for y=57,59 do for _,x in ipairs({114,148}) do floor:drawPixel(x,y,joint) end end
for y=61,63 do floor:drawPixel(131,y,joint) end
-- Trim: the skirting runs to the corner, the corner post stands at 158-159.
local trim=widened(frames.trim.image)
local glow=H.image(NEW,64);H.paste(glow,frames.glow.image,0,0)
local layer=s.layers[1]
for name,im in pairs({wall=wall,floor=floor,trim=trim,glow=glow}) do s:newCel(layer,frames[name].frame,im,Point(0,0)) end
H.assertPalette(s,R.pal);s:saveAs(path);s:close()
print('room parts widened to 160 columns')
