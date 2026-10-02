-- Open the saved page-turn pose for 800% onion-skin review; no pixels change.
assert(app.isUIAvailable,'GUI only')
local folder=app.fs.filePath(debug.getinfo(1,'S').source:sub(2))
local ART=app.fs.filePath(folder)
app.command.OpenFile{ui=false,filename=app.fs.joinPath(ART,'src/bookworm-reading.aseprite')}
app.frame=18;app.editor.zoom=8;app.editor.scroll={x=28,y=34};app.refresh()
