local H=require('ase_helpers')
local ART=app.params.art or app.fs.joinPath(H.scriptDir(),'..')
local s=app.open(app.fs.joinPath(ART,'parts/worm-parts.aseprite'))
local p=H.paletteFromJson(app.fs.joinPath(ART,'palette.json'))
for _,tag in ipairs(s.tags) do
  if tag.name=='body.sit/head' or tag.name=='eyes.center' then
    local im=H.flatten(s,tag.fromFrame.frameNumber)
    for it in im:pixels() do if it()~=0 and app.pixelColor.rgbaR(it())>250 then print(tag.name..' white '..it.x..','..it.y) end end
  end
end
s:close()
local a=H.loadPart(app.fs.joinPath(ART,'parts/worm-parts.aseprite'),'book.open')
local b=H.loadPart(app.fs.joinPath(ART,'parts/worm-parts.aseprite'),'book.open2')
local n=0
for y=0,47 do for x=0,63 do if a:getPixel(x,y)~=b:getPixel(x,y) then
 n=n+1;if n<8 then print('open seam '..x..','..y..': '..a:getPixel(x,y)..'/'..b:getPixel(x,y)) end
end end end
print('open seam differences '..n)
