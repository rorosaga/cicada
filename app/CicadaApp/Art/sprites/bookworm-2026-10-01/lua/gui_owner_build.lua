-- Owner's final error/menu decisions: execute inside Aseprite under GUI lock.
assert(app.isUIAvailable,'GUI only')
local folder=app.fs.filePath(debug.getinfo(1,'S').source:sub(2));package.path=folder..'/?.lua;'..package.path
dofile(folder..'/gui_owner_error.lua')
dofile(folder..'/build_worm.lua')
dofile(folder..'/build_worm_small.lua')
app.command.OpenFile{ui=false,filename=app.fs.joinPath(app.fs.filePath(folder),'src/bookworm-error.aseprite')}
app.frame=1;app.editor.zoom=8;app.editor.scroll={x=25,y=20};app.refresh()
print('Owner X eyes saved and both worm generators rebuilt inside Aseprite')
