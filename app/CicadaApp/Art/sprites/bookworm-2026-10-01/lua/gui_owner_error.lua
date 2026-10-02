-- Reproducible native 1px Pencil hand correction. Run from Aseprite's console
-- under the GUI lock, or with -b --script for the same saved authoring parts.
local folder=app.fs.filePath(debug.getinfo(1,'S').source:sub(2));package.path=folder..'/?.lua;'..package.path
local H=require('ase_helpers');local E=require('error_eyes')
local ART=(app.params or {}).art or app.fs.joinPath(folder,'..')
local pal=H.paletteFromJson(app.fs.joinPath(ART,'palette.json'))
for _,kind in ipairs({'room','small'}) do
 local s=app.open(app.fs.joinPath(ART,kind=='room' and 'parts/worm-parts.aseprite' or 'parts/worm-small-parts.aseprite'))
 app.sprite=s;app.layer=s.layers[1]
 app.transaction('Owner black X eyes: native palette Pencil',function()
  for _,tag in ipairs(s.tags) do if tag.name:match('^eyes%.error') then
   app.frame=tag.fromFrame
   H.setCel(s,s.layers[1],tag.fromFrame.frameNumber,H.image(s.width,s.height))
   E[kind](function(x,y,key) app.useTool{tool='pencil',brush=Brush(1),color=pal.color[key],points={Point(x,y)}} end)
  end end
  H.applyPalette(s,pal)
 end)
 H.assertPalette(s,pal);H.save(s,s.filename)
 if app.isUIAvailable then app.editor.zoom=8;app.refresh() end
 s:close()
end
print('Owner black X room/menu parts saved; red and dark-rim palette keys removed')
