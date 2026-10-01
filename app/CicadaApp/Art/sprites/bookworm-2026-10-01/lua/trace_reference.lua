local H = require('ase_helpers')
local ART = app.params.art or app.fs.joinPath(H.scriptDir(), '..')
local pal = H.paletteFromJson(app.fs.joinPath(ART, 'palette.json'))
local entries = {}
for _, k in ipairs({'K','G','g','D','L','B','b','H','W','C','P','S'}) do
  entries[#entries+1] = {k, pal.hex[k], pal.role[k]}
end
local refPal = H.palette(entries)
local path = app.fs.joinPath(ART, 'reference/bookworm.png')
local raw = H.quantize(Image{fromFile=path}, refPal)
local b = H.inkBounds(raw)
local crop = H.image(b.w,b.h)
H.paste(crop,raw,-b.x,-b.y)
H.exportPng(crop,app.fs.joinPath(ART,'qa/reference-crop.png'))
for _, size in ipairs({{70,47},{56,38}}) do
  local w,h = size[1],size[2]
  local im = H.loadReference(app.fs.joinPath(ART,'qa/reference-crop.png'),w,h,refPal)
  local spr,layers = H.newSprite(w,h,pal,{'ref','fitted'})
  H.addFrame(spr,1000,{ref=H.loadReference(path,w,h,refPal),fitted=im})
  layers.ref.isVisible=false; layers.fitted.isVisible=false
  H.save(spr,app.fs.joinPath(ART,string.format('tracing/ref_%dx%d.aseprite',w,h)))
  H.exportPng(im,app.fs.joinPath(ART,string.format('qa/ref_%dx%d@8x.png',w,h)),8)
  local keys={}; for _,k in ipairs(refPal.keys) do keys[refPal.px[k]]=k end
  local rows={}
  for y=0,h-1 do local r=''; for x=0,w-1 do r=r..(keys[im:getPixel(x,y)] or '.') end; rows[#rows+1]=r end
  local f=assert(io.open(app.fs.joinPath(ART,string.format('tracing/ref_%dx%d.txt',w,h)),'w'))
  f:write(table.concat(rows,'\n')..'\n'); f:close(); spr:close()
end
print('reference: independently cropped, palette fitted, traced at 70x47 and 56x38')
