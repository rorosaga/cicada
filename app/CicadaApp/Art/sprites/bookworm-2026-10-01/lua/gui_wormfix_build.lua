-- Short GUI-console entry point; Aseprite's console limits a pasted line.
assert(app.isUIAvailable,'GUI only')
local folder=app.fs.filePath(debug.getinfo(1,'S').source:sub(2))
package.path=folder..'/?.lua;'..package.path
dofile(folder..'/gui_wormfix_face.lua')
-- Close only our saved authoring documents before the generators read them.
local ART=app.fs.filePath(folder)
for i=#app.sprites,1,-1 do
 local s=app.sprites[i]
 if s.filename:sub(1,#ART)==ART then s:close() end
end
dofile(folder..'/build_worm.lua')
dofile(folder..'/build_worm_small.lua')
print('GUI worm fix builders complete')
