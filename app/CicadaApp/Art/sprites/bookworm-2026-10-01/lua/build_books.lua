-- The waiting pile's books (2026-10-16, owner pick "A · Stack"). One 24 x 13 sheet: for every kind a day tag and a
-- night tag of four frames, one per count step (7, 9, 11, 13 rows, drawn from the top row down). The app joins the
-- leading cap (columns 0-3), the middle column repeated to the book's width, and the trailing cap (16-23).
-- Night: the pile's columns are in the shadow band of both light sources (room-light-map.json, verified here), so a
-- night book is its day pixels through the palette's band-0 ramp, with the lamp lit or not.
local H=require('ase_helpers');local R=require('room_common')
local ART=(app.params or {}).art or app.fs.joinPath(H.scriptDir(),'..');R.context(ART)
local KINDS={'chat','message','page','note','video','other'}
local ROWS={7,9,11,13}
local plan=H.readJson(app.fs.joinPath(ART,'room-plan.json'))
local map=H.readJson(app.fs.joinPath(ART,'room-light-map.json'))
for row=64-plan.pile.y-plan.pile.h+1,64-plan.pile.y do
  for _,source in ipairs({'moon','lamp'}) do
    local band=map[source][row]:sub(plan.pile.x+1,plan.pile.x+plan.pile.w)
    assert(band==string.rep('0',plan.pile.w),'the pile column left the shadow band ('..source..' row '..row..')')
  end
end
local data=H.readJson(app.fs.joinPath(ART,'palette.json'))
local shadow={}
for _,c in ipairs(data.colors) do
  shadow[app.pixelColor.rgba(H.hex(c.hex))]=app.pixelColor.rgba(H.hex(assert(data.night.ramps[c.key],'ramp '..c.key)[1]))
end
local function night(im)
  local out=H.image(im.width,im.height)
  for p in im:pixels() do
    if app.pixelColor.rgbaA(p())>0 then out:drawPixel(p.x,p.y,assert(shadow[p()],'undeclared day pixel')) end
  end
  return out
end
local s=H.newSprite(24,13,R.pal,{'book'});local rec=H.recorder(s);local frames={}
for _,kind in ipairs(KINDS) do
  local days={}
  rec:start(kind)
  for i,rows in ipairs(ROWS) do
    local part='book.'..kind..'.'..rows
    days[i]=R.part(part,24,13)
    rec:frame(1000,{book=days[i]});frames[#frames+1]={parts={{part=part,x=0,y=0}}}
  end
  rec:stop()
  rec:start(kind..'-night')
  for i=1,#ROWS do rec:frame(1000,{book=night(days[i])});frames[#frames+1]={parts={}} end
  rec:stop()
end
rec:apply();R.finish(s,'room-books',frames);print('books: six kinds, four count steps, day and night')
