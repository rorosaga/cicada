-- Native playback of every actual 6x/8x exported tag GIF.
local folder=app.fs.filePath(debug.getinfo(1,'S').source:sub(2))
CicadaReviewMode='gif'
CicadaReviewStart=1
CicadaReviewEnd=nil
dofile(app.fs.joinPath(folder,'gui_review.lua'))
