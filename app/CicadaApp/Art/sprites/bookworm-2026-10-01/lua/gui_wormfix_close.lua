-- Close only this run's documents before handing back the shared GUI lock.
local folder=app.fs.filePath(debug.getinfo(1,'S').source:sub(2))
local art=app.fs.filePath(folder)
if CicadaReview then CicadaReview.stop() end
local owned={}
for _,sprite in ipairs(app.sprites) do
  if sprite.filename:sub(1,#art)==art then owned[#owned+1]=sprite end
end
for _,sprite in ipairs(owned) do app.activeSprite=sprite;app.command.CloseFile() end
