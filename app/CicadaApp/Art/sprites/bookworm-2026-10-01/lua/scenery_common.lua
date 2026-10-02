local H=require('ase_helpers')
local C={}
function C.context(art)
  local palette=H.readJson(app.fs.joinPath(art,'palette.json'))
  C.tints={dusk={},night={}};C.colors={}
  for _,color in ipairs(palette.colors) do
    local pixel=app.pixelColor.rgba(H.hex(color.hex))
    for phase,ramp in pairs(palette.scenery.ramps) do C.tints[phase][pixel]=app.pixelColor.rgba(H.hex(ramp[color.key])) end
  end
  for _,color in ipairs(palette.scenery.colors) do C.colors[color.id]=app.pixelColor.rgba(H.hex(color.hex)) end
  return C
end
function C.tint(im,time)
  if time=='day' then return im end
  local out=H.image(im.width,im.height)
  for p in im:pixels() do if app.pixelColor.rgbaA(p())>0 then out:drawPixel(p.x,p.y,assert(C.tints[time][p()],'missing scenery tint')) end end
  return out
end
function C.pos(name,n,fn,wx,wy)
  local e={name=name,positions={},steps={},wrap={x=wx or 0,y=wy or 0}}
  for i=0,n-1 do local x,y=fn(i);e.positions[i+1]={x=x,y=y} end
  for i=1,n do
    local a,b=e.positions[i],e.positions[i%n+1];local dx,dy=b.x-a.x,b.y-a.y
    if wx and wx>0 then dx=dx%wx;if dx>wx/2 then dx=dx-wx end end
    if wy and wy>0 then dy=dy%wy;if dy>wy/2 then dy=dy-wy end end
    e.steps[i]={x=dx,y=dy}
  end
  return e
end
return C
