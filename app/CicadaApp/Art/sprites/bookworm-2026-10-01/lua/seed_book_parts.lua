-- 2026-10-16 (owner pick "A · Stack"): the waiting pile is pixel-art books, not tinted spine slabs. This one-off adds
-- the books to the SAVED room parts (which own the pixels) and retires the spine masks with their sheet:
--   book.<kind>.<rows>  a book lying flat, spine to the viewer, its page block at the right end, 24 columns wide,
--                       for kind chat|message|page|note|video|other and rows 7|9|11|13 (the count steps).
-- Columns 0-3 are the leading cap (outline, lit edge, the left band), 4-15 the tileable middle (every column the
-- same), 16-23 the trailing cap (the right band, the hinge, three page columns, the outline). Every colour is an
-- existing palette key. Idempotent: a parts file that already holds the books is left alone.
local H=require('ase_helpers');local R=require('room_common')
local ART=(app.params or {}).art or app.fs.joinPath(H.scriptDir(),'..');R.context(ART)
local path=app.fs.joinPath(ART,'parts/room-parts.aseprite')
local s=assert(app.open(path))
for _,t in ipairs(s.tags) do
  if t.name:match('^book%.') then s:close();print('book parts already seeded');return end
end
local KINDS={chat={'book.cover1.light','book.cover1.mid','book.cover1.dark'},
  message={'room.leaf.2','room.leaf.1','room.leaf.0'},
  page={'book.cover3.light','book.cover3.mid','book.cover3.dark'},
  note={'room.bag.2','room.bag.1','room.bag.0'},
  video={'book.cover2.light','book.cover2.mid','book.cover2.dark'},
  other={'room.lamp.2','room.lamp.1','room.lamp.0'}}
local ORDER={'chat','message','page','note','video','other'}
local ROWS={7,9,11,13}
local W=24
-- Keep every other part's pixels: compare by name after the edit.
local before={}
for _,t in ipairs(s.tags) do
  if not t.name:match('^spine%.') then before[t.name]=H.flatten(s,t.fromFrame.frameNumber) end
end
-- Retire the spine masks, last frame first so earlier frame numbers hold.
local spines={}
for _,t in ipairs(s.tags) do
  if t.name:match('^spine%.') then
    assert(t.fromFrame.frameNumber==t.toFrame.frameNumber,'a part is one frame')
    spines[#spines+1]={tag=t,frame=t.fromFrame.frameNumber}
  end
end
table.sort(spines,function(a,b) return a.frame>b.frame end)
for _,p in ipairs(spines) do
  for _,t in ipairs(s.tags) do
    assert(t==p.tag or t.fromFrame.frameNumber~=p.frame,'frame '..p.frame..' is shared by '..t.name)
  end
  s:deleteTag(p.tag);s:deleteFrame(p.frame)
end
local function book(kind,rows)
  local L,M,D=table.unpack(KINDS[kind])
  local im=H.image(s.width,s.height)
  for y=0,rows-1 do
    for x=0,W-1 do
      local corner=(x==0 or x==W-1) and (y==0 or y==rows-1)
      if not corner then
        local role
        if x==0 or x==W-1 or y==0 or y==rows-1 then role='worm.outline'
        elseif y==1 then role=L
        elseif y==rows-2 then role=D
        elseif x>=W-4 then role=((y-2)%2==0) and 'book.page.cream' or 'book.page.grey'
        elseif x==W-5 then role=D
        elseif x==2 or x==W-8 then role=L
        else role=M end
        R.px(im,x,y,role)
      end
    end
  end
  return im
end
local layer=s.layers[1]
for _,kind in ipairs(ORDER) do
  for _,rows in ipairs(ROWS) do
    local frame=s:newEmptyFrame();H.setDuration(frame,1000)
    s:newCel(layer,frame.frameNumber,book(kind,rows),Point(0,0))
    local t=s:newTag(frame.frameNumber,frame.frameNumber);t.name='book.'..kind..'.'..rows
  end
end
for _,t in ipairs(s.tags) do
  if before[t.name] then
    local now=H.flatten(s,t.fromFrame.frameNumber)
    assert(now:isEqual(before[t.name]),'part changed: '..t.name)
    before[t.name]=nil
  end
end
assert(next(before)==nil,'a part went missing')
H.assertPalette(s,R.pal);s:saveAs(path);s:close()
print('room parts: '..#spines..' spine masks retired, '..(#ORDER*#ROWS)..' books seeded')
