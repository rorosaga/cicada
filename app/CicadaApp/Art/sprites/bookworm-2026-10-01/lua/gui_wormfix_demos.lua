-- Native playback of the continuous cover cycle and unbundled mad preview.
assert(app.isUIAvailable,'GUI only')
local folder=app.fs.filePath(debug.getinfo(1,'S').source:sub(2))
local art=app.fs.filePath(folder)
package.path=folder..'/?.lua;'..package.path
local H=require('ase_helpers')
local clips={{'bookworm-reading-cycle@6x.gif',65520},{'bookworm-mad-demo@6x.gif',13200}}
local index=0;local playing=false;local timer
local dialog=Dialog{title='Worm fix continuous demos'}
local function stop()
  if playing then app.command.PlayAnimation();playing=false end
end
local function nextClip()
  stop();index=index+1
  if index>#clips then
    timer:stop()
    H.writeJson(app.fs.joinPath(art,'qa/wormfix-native-demos.json'),{count=2,readingMs=65520,madMs=13200})
    dialog:modify{id='status',text='COMPLETE: continuous reading + mad'}
    return
  end
  if app.activeSprite and app.activeSprite.filename:sub(1,#art)==art then app.command.CloseFile() end
  app.command.OpenFile{ui=false,filename=app.fs.joinPath(art,'demo/'..clips[index][1])}
  app.frame=1;app.editor.zoom=1
  app.editor.scroll={x=app.activeSprite.width/2,y=app.activeSprite.height/2}
  dialog:modify{id='status',text=index..'/2 '..clips[index][1]}
  app.command.PlayAnimation();playing=true
  timer.interval=clips[index][2]/1000+0.15;timer:start();app.refresh()
end
CicadaReview={stop=function() stop();timer:stop();dialog:close() end}
dialog:label{id='status',text='Starting'}:button{text='Stop / close',onclick=function() CicadaReview.stop() end}
dialog:show{wait=false,bounds=Rectangle(90,53,650,90)}
timer=Timer{interval=1,ontick=function() timer:stop();nextClip() end}
nextClip()
