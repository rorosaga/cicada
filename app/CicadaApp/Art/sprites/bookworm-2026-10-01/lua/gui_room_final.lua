-- Native final correction: keep the extreme tree lean inside glass cols 1-12.
assert(app.isUIAvailable,'GUI only')
local ART=app.fs.filePath(app.fs.filePath(debug.getinfo(1,'S').source:sub(2)))
local filename=app.fs.joinPath(ART,'parts/room-parts.aseprite')
app.command.OpenFile{ui=false,filename=filename}
local sprite=app.activeSprite;assert(sprite and sprite.filename==filename)
local file=assert(io.open(app.fs.joinPath(ART,'palette.json'),'r'))
local palette=json.decode(file:read('a'));file:close()
local outline
for _,entry in ipairs(palette.colors) do if entry.role=='room.leaf.0' then
 outline=Color{r=tonumber(entry.hex:sub(2,3),16),g=tonumber(entry.hex:sub(4,5),16),b=tonumber(entry.hex:sub(6,7),16)}
end end
assert(outline)
for _,tag in ipairs(sprite.tags) do if tag.name=='tree.2' then app.frame=tag.fromFrame;break end end
app.layer=sprite.layers[1];app.command.DeselectMask()
app.transaction('Keep the leaning tree inside its pane',function()
 for y=2,5 do
  app.useTool{tool='eraser',brush=Brush(1),points={Point(13,y)}}
  app.useTool{tool='pencil',brush=Brush(1),color=outline,points={Point(12,y)}}
 end
end)
app.command.SaveFile();app.editor.zoom=8;app.refresh()
print('GUI final tree correction saved')
