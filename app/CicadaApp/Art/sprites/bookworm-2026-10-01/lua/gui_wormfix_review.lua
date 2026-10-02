-- Native playback entrypoint, invoked from Aseprite's Lua Console.
local folder=app.fs.filePath(debug.getinfo(1,'S').source:sub(2))
CicadaReviewMode='source'
CicadaReviewStart=1
CicadaReviewEnd=nil
dofile(app.fs.joinPath(folder,'gui_review.lua'))
