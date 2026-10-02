-- Run from Aseprite's native Developer Console or File > Scripts.
-- The builders always read the saved, GUI-tuned room-parts document.
assert(app.isUIAvailable,'GUI only')
local thisFile=debug.getinfo(1,'S').source:sub(2)
local ART=app.fs.filePath(app.fs.filePath(thisFile))
package.path=app.fs.joinPath(ART,'lua/?.lua')..';'..package.path
for _,name in ipairs({'build_room','build_weather','build_spines'}) do
 dofile(app.fs.joinPath(ART,'lua/'..name..'.lua'))
end
print('Run B: all three builders executed in the Aseprite GUI')
