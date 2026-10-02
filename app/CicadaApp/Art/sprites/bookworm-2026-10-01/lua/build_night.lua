-- G176: deterministic relighting of saved day sources, never a GUI or a clock.
local H=require('ase_helpers')
local ART=assert((app.params or {}).art)
-- Room relights always start at the saved day parts, never at previously appended night ranges.
dofile(app.fs.joinPath(ART,'lua/build_room.lua'))
local data=H.readJson(app.fs.joinPath(ART,'palette.json'))
local pal=H.paletteFromJson(app.fs.joinPath(ART,'palette.json'))
local map=H.readJson(app.fs.joinPath(ART,'room-light-map.json'))
assert(map.cols==160 and map.rows==64 and map.origin=='top-left')
local ramps={}
for _,c in ipairs(data.colors) do
  local day=app.pixelColor.rgba(H.hex(c.hex))
  local ramp=assert(data.night.ramps[c.key],'missing night ramp '..c.key)
  assert(#ramp==#data.night.bands)
  ramps[day]={}
  for i,hex in ipairs(ramp) do ramps[day][i]=app.pixelColor.rgba(H.hex(hex)) end
end
local function relight(im,x,y,lit,state)
  local out=H.image(im.width,im.height)
  for p in im:pixels() do
    if app.pixelColor.rgbaA(p())>0 then
      local band=tonumber(map.moon[y+p.y+1]:sub(x+p.x+1,x+p.x+1))
      if lit then band=math.max(band,tonumber(map.lamp[y+p.y+1]:sub(x+p.x+1,x+p.x+1))) end
      local pixel=assert(ramps[p()],'undeclared day pixel')[band+1]
      local q=data.night.glyphs.question;local box=q.box
      if state=='curious' and p.x>=box.x and p.x<box.x+box.w and p.y>=box.y and p.y<box.y+box.h then
        if p()==pal.px.K then pixel=app.pixelColor.rgba(H.hex(q.colors.outline)) end
        if p()==pal.px.W then pixel=app.pixelColor.rgba(H.hex(q.colors.core)) end
      end
      out:drawPixel(p.x,p.y,pixel)
    end
  end
  return out
end
local plan=H.readJson(app.fs.joinPath(ART,'room-plan.json'))
local registryPath=app.fs.joinPath(ART,'qa/room-registry.json')
local registry=H.readJson(registryPath)
for _,layer in ipairs(plan.layers) do
  if layer.prop~='pane' and layer.prop~='skyfx' and layer.prop~='fly' and layer.prop~='clock' then
    local path=app.fs.joinPath(ART,'src',layer.sheet..'.aseprite')
    local s=assert(app.open(path));local tags={};local images={};local durations={}
    for _,t in ipairs(s.tags) do
      assert(t.name~='night-dark' and t.name~='night-lit','stale night range '..layer.sheet)
      tags[#tags+1]={name=t.name,from=t.fromFrame.frameNumber,to=t.toFrame.frameNumber}
    end
    for i=1,#s.frames do images[i]=H.flatten(s,i);durations[i]=H.ms(s.frames[i]) end
    -- Adding a frame grows a tag ending on the old last frame. Recreate all tags afterwards.
    for i=#s.tags,1,-1 do s:deleteTag(s.tags[i]) end
    H.layers(s,{'night'})
    local ranges={}
    for _,lit in ipairs({false,true}) do
      local base=(layer.prop=='backdrop' or layer.prop=='lamp') and (lit and 'lit' or 'dark') or 'idle'
      local t;for _,candidate in ipairs(tags) do if candidate.name==base then t=candidate end end
      assert(t,'missing day tag '..base)
      local first=#s.frames+1
      for f=t.from,t.to do H.addFrame(s,durations[f],{night=relight(images[f],layer.x,64-layer.y-layer.h,lit)}) end
      ranges[#ranges+1]={name=lit and 'night-lit' or 'night-dark',from=first,to=#s.frames}
    end
    for _,t in ipairs(tags) do H.tag(s,t.name,t.from,t.to) end
    for _,t in ipairs(ranges) do H.tag(s,t.name,t.from,t.to) end
    for _,t in ipairs(ranges) do
      local record={name=t.name,frames={}}
      for f=t.from,t.to do record.frames[#record.frames+1]={index=f-1,ms=H.ms(s.frames[f]),parts={}} end
      registry.sheets[layer.sheet].tags[#registry.sheets[layer.sheet].tags+1]=record
    end
    H.assertPalette(s,pal);H.applyUsedPalette(s);H.save(s,path);s:close()
  end
end
H.writeJson(registryPath,registry)
for _,state in ipairs({'awake','sleeping','digesting','happy','curious','hungry','reading','error'}) do
local day=assert(app.open(app.fs.joinPath(ART,'src/bookworm-'..state..'.aseprite')))
for _,lit in ipairs({false,true}) do
  local s=H.newSprite(day.width,day.height,pal,{'night'})
  local rec=H.recorder(s)
  for _,t in ipairs(day.tags) do
    rec:start(t.name)
    for f=t.fromFrame.frameNumber,t.toFrame.frameNumber do
      rec:frame(H.ms(day.frames[f]),{night=relight(H.flatten(day,f),plan.worm.x,64-plan.worm.y-plan.worm.h,lit,state)})
    end
    rec:stop()
  end
  rec:apply()
  for _,slice in ipairs(day.slices) do
    local b=slice.bounds;H.addSlice(s,slice.name,{x=b.x,y=b.y,w=b.width,h=b.height})
  end
  H.assertPalette(s,pal)
  H.applyUsedPalette(s)
  H.save(s,app.fs.joinPath(ART,'src/bookworm-'..state..'-night-'..(lit and 'lit' or 'dark')..'.aseprite'))
  s:close()
end
day:close()
end
print('night: six room tag pairs and sixteen complete worm sheets relit on one lattice')
