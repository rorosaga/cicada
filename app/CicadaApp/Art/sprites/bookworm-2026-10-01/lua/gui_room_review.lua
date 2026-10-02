-- Native source/GIF playback. Each weather gets three complete loops.
assert(app.isUIAvailable,'GUI only')
local thisFile=debug.getinfo(1,'S').source:sub(2)
local ART=app.fs.filePath(app.fs.filePath(thisFile))
local plan={
 {sheet='room-weather',tag='night',first=1,ms=4800},
 {sheet='room-weather',tag='dawn',first=25,ms=10800},
 {sheet='room-weather',tag='clear',first=61,ms=18000},
 {sheet='room-weather',tag='fair',first=97,ms=14400},
 {sheet='room-weather',tag='overcast',first=169,ms=4320},
 {sheet='room-weather',tag='storm',first=205,ms=3840},
 {sheet='room-weather',tag='curtains',first=253,ms=3600},
 {sheet='room-fly',tag='buzz',first=1,ms=4590},
 {sheet='room-lamp',tag='dark',first=1,ms=1000},
 {sheet='room-lamp',tag='lit',first=2,ms=1000},
 {sheet='room-window',tag='idle',first=1,ms=1000},
 {sheet='room-backdrop',tag='dark',first=1,ms=1000},
 {sheet='room-backdrop',tag='lit',first=2,ms=1000},
 {sheet='room-beanbag',tag='idle',first=1,ms=1000},
 {sheet='room-plant',tag='idle',first=1,ms=1000},
 {sheet='room-mug',tag='idle',first=1,ms=1000},
 {sheet='room-spines',tag='chat',first=1,ms=3000},
 {sheet='room-spines',tag='page',first=4,ms=3000},
 {sheet='room-spines',tag='note',first=7,ms=3000},
 {sheet='room-spines',tag='video',first=10,ms=3000},
 {sheet='room-spines',tag='other',first=13,ms=3000}}
local mode=CicadaRoomReviewMode or 'source'
local index=(CicadaRoomReviewStart or 1)-1
local lastIndex=CicadaRoomReviewEnd or #plan
local current,playing,stepLast=false,false,nil
local completed={};local timer
local dialog=Dialog{title='Run B '..mode..' review'}
local function stop() if playing then app.command.PlayAnimation();playing=false end end
local function nextClip()
 stop()
 if current then completed[#completed+1]=current.sheet..'/'..current.tag end
 index=index+1;current=index<=lastIndex and plan[index] or nil
 if not current then
  timer:stop();CicadaRoomReview.completed=completed
  dialog:modify{id='status',text='COMPLETE: '..#completed..' clips'};return
 end
 local filename=app.fs.joinPath(ART,mode=='gif' and ('qa/'..current.sheet..'/'..current.tag..'@6x.gif') or ('src/'..current.sheet..'.aseprite'))
 if not app.activeSprite or app.activeSprite.filename~=filename then
  if app.activeSprite and app.activeSprite.filename:sub(1,#ART)==ART then app.command.CloseFile() end
  app.command.OpenFile{ui=false,filename=filename}
 end
 assert(app.activeSprite and app.activeSprite.filename==filename,'review document missing')
 app.frame=mode=='gif' and 1 or current.first
 app.editor.zoom=mode=='gif' and 1 or 8
 app.editor.scroll={x=app.activeSprite.width/2,y=app.activeSprite.height/2}
 dialog:modify{id='status',text=index..'/'..#plan..' '..current.sheet..'/'..current.tag}
 if mode=='step' then
  stepLast=current.sheet=='room-fly' and 40 or current.first
  timer.interval=0.25
 else
  app.command.PlayAnimation();playing=true
  timer.interval=current.ms/1000*(current.sheet=='room-weather' and 3 or 1)+0.15
 end
 timer:start();app.refresh()
end
CicadaRoomReview={stop=function()stop();timer:stop();dialog:close()end}
dialog:label{id='status',text='Starting'}:button{text='Stop / close',onclick=function()CicadaRoomReview.stop()end}
dialog:show{wait=false,bounds=Rectangle(90,53,650,90)}
timer=Timer{interval=1,ontick=function()
 timer:stop()
 if mode=='step' and app.frame.frameNumber<stepLast then app.command.GotoNextFrame();app.refresh();timer:start() else nextClip() end
end}
nextClip()
