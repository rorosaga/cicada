local H=require('ase_helpers');local R=require('room_common')
local ART=(app.params or {}).art or app.fs.joinPath(H.scriptDir(),'..');R.context(ART)
local s=app.open(app.fs.joinPath(ART,'parts/room-parts.aseprite'))
local dimensions={wall={160,64},floor={160,64},trim={160,64},glow={160,64},
 ['window.frame']={40,38},['window.sill']={40,38},['lamp.dark']={18,50},['lamp.light']={18,50},
 bag={62,12},plant={12,22},mug={8,9},['cloud.round']={12,4},['cloud.thin']={13,2},sun={7,7},moon={7,8}}
for i=0,2 do dimensions['tree.'..i]={14,14} end
-- 2026-10-16: the pile's books (seed_book_parts.lua) replaced the spine masks.
for _,kind in ipairs({'chat','message','page','note','video','other'}) do
 for _,rows in ipairs({7,9,11,13}) do dimensions['book.'..kind..'.'..rows]={24,rows} end
end
H.assertPalette(s,R.pal)
local checked=0
for _,tag in ipairs(s.tags) do
 local size=assert(dimensions[tag.name],'Unknown room part '..tag.name)
 local image=H.flatten(s,tag.fromFrame.frameNumber)
 if tag.name:match('^tree%.') then
  local ink=H.inkBounds(image)
  assert(ink.x>=1 and ink.x+ink.w<=13 and ink.y==0 and ink.h==14,'Tree must remain inside cols 1-12 and rows 18-31 after placement')
 end
 for pixel in image:pixels() do
  assert(app.pixelColor.rgbaA(pixel())==0 or (pixel.x<size[1] and pixel.y<size[2]),
   string.format('Stray pixel: %s at (%d,%d)',tag.name,pixel.x,pixel.y))
 end
 checked=checked+1
end
s:close();print('room parts: '..checked..' palette-locked tags; unused master-canvas area transparent')
