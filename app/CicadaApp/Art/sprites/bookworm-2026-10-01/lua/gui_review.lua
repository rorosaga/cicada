-- Computer-use review only. Native timeline playback, no edits and no preferences.
assert(app.isUIAvailable,'GUI only')
local thisFile=debug.getinfo(1,'S').source:sub(2)
local ART=app.fs.filePath(app.fs.filePath(thisFile))
local plan={
{sheet="bookworm-awake",tag="idle",first=1,ms=13200,scale=6},
{sheet="bookworm-awake",tag="attentive.left",first=35,ms=5910,scale=6},
{sheet="bookworm-awake",tag="attentive.center",first=46,ms=5910,scale=6},
{sheet="bookworm-awake",tag="attentive.right",first=57,ms=5910,scale=6},
{sheet="bookworm-awake",tag="expectant.left",first=68,ms=720,scale=6},
{sheet="bookworm-awake",tag="expectant.center",first=72,ms=720,scale=6},
{sheet="bookworm-awake",tag="expectant.right",first=76,ms=720,scale=6},
{sheet="bookworm-awake",tag="eager",first=80,ms=460,scale=6},
{sheet="bookworm-awake",tag="perk.left",first=84,ms=360,scale=6},
{sheet="bookworm-awake",tag="perk.center",first=88,ms=360,scale=6},
{sheet="bookworm-awake",tag="perk.right",first=92,ms=360,scale=6},
{sheet="bookworm-awake",tag="talk.left",first=96,ms=500,scale=6},
{sheet="bookworm-awake",tag="talk.center",first=102,ms=500,scale=6},
{sheet="bookworm-awake",tag="talk.right",first=108,ms=500,scale=6},
{sheet="bookworm-awake",tag="gulp.center",first=114,ms=650,scale=6},
{sheet="bookworm-awake",tag="shake.left",first=121,ms=430,scale=6},
{sheet="bookworm-awake",tag="shake.center",first=126,ms=430,scale=6},
{sheet="bookworm-awake",tag="shake.right",first=131,ms=430,scale=6},
{sheet="bookworm-reading",tag="idle",first=1,ms=21840,scale=6},
{sheet="bookworm-reading",tag="attentive.left",first=86,ms=5910,scale=6},
{sheet="bookworm-reading",tag="attentive.center",first=97,ms=5910,scale=6},
{sheet="bookworm-reading",tag="attentive.right",first=108,ms=5910,scale=6},
{sheet="bookworm-reading",tag="expectant.left",first=119,ms=720,scale=6},
{sheet="bookworm-reading",tag="expectant.center",first=123,ms=720,scale=6},
{sheet="bookworm-reading",tag="expectant.right",first=127,ms=720,scale=6},
{sheet="bookworm-reading",tag="eager",first=131,ms=460,scale=6},
{sheet="bookworm-reading",tag="perk.left",first=135,ms=360,scale=6},
{sheet="bookworm-reading",tag="perk.center",first=139,ms=360,scale=6},
{sheet="bookworm-reading",tag="perk.right",first=143,ms=360,scale=6},
{sheet="bookworm-reading",tag="talk.left",first=147,ms=500,scale=6},
{sheet="bookworm-reading",tag="talk.center",first=153,ms=500,scale=6},
{sheet="bookworm-reading",tag="talk.right",first=159,ms=500,scale=6},
{sheet="bookworm-reading",tag="gulp.center",first=165,ms=650,scale=6},
{sheet="bookworm-reading",tag="shake.left",first=172,ms=430,scale=6},
{sheet="bookworm-reading",tag="shake.center",first=177,ms=430,scale=6},
{sheet="bookworm-reading",tag="shake.right",first=182,ms=430,scale=6},
{sheet="bookworm-reading",tag="idle@2",first=187,ms=21840,scale=6},
{sheet="bookworm-reading",tag="attentive.left@2",first=272,ms=5910,scale=6},
{sheet="bookworm-reading",tag="attentive.center@2",first=283,ms=5910,scale=6},
{sheet="bookworm-reading",tag="attentive.right@2",first=294,ms=5910,scale=6},
{sheet="bookworm-reading",tag="expectant.left@2",first=305,ms=720,scale=6},
{sheet="bookworm-reading",tag="expectant.center@2",first=309,ms=720,scale=6},
{sheet="bookworm-reading",tag="expectant.right@2",first=313,ms=720,scale=6},
{sheet="bookworm-reading",tag="eager@2",first=317,ms=460,scale=6},
{sheet="bookworm-reading",tag="perk.left@2",first=321,ms=360,scale=6},
{sheet="bookworm-reading",tag="perk.center@2",first=325,ms=360,scale=6},
{sheet="bookworm-reading",tag="perk.right@2",first=329,ms=360,scale=6},
{sheet="bookworm-reading",tag="talk.left@2",first=333,ms=500,scale=6},
{sheet="bookworm-reading",tag="talk.center@2",first=339,ms=500,scale=6},
{sheet="bookworm-reading",tag="talk.right@2",first=345,ms=500,scale=6},
{sheet="bookworm-reading",tag="gulp.center@2",first=351,ms=650,scale=6},
{sheet="bookworm-reading",tag="shake.left@2",first=358,ms=430,scale=6},
{sheet="bookworm-reading",tag="shake.center@2",first=363,ms=430,scale=6},
{sheet="bookworm-reading",tag="shake.right@2",first=368,ms=430,scale=6},
{sheet="bookworm-reading",tag="idle@3",first=373,ms=21840,scale=6},
{sheet="bookworm-reading",tag="attentive.left@3",first=458,ms=5910,scale=6},
{sheet="bookworm-reading",tag="attentive.center@3",first=469,ms=5910,scale=6},
{sheet="bookworm-reading",tag="attentive.right@3",first=480,ms=5910,scale=6},
{sheet="bookworm-reading",tag="expectant.left@3",first=491,ms=720,scale=6},
{sheet="bookworm-reading",tag="expectant.center@3",first=495,ms=720,scale=6},
{sheet="bookworm-reading",tag="expectant.right@3",first=499,ms=720,scale=6},
{sheet="bookworm-reading",tag="eager@3",first=503,ms=460,scale=6},
{sheet="bookworm-reading",tag="perk.left@3",first=507,ms=360,scale=6},
{sheet="bookworm-reading",tag="perk.center@3",first=511,ms=360,scale=6},
{sheet="bookworm-reading",tag="perk.right@3",first=515,ms=360,scale=6},
{sheet="bookworm-reading",tag="talk.left@3",first=519,ms=500,scale=6},
{sheet="bookworm-reading",tag="talk.center@3",first=525,ms=500,scale=6},
{sheet="bookworm-reading",tag="talk.right@3",first=531,ms=500,scale=6},
{sheet="bookworm-reading",tag="gulp.center@3",first=537,ms=650,scale=6},
{sheet="bookworm-reading",tag="shake.left@3",first=544,ms=430,scale=6},
{sheet="bookworm-reading",tag="shake.center@3",first=549,ms=430,scale=6},
{sheet="bookworm-reading",tag="shake.right@3",first=554,ms=430,scale=6},
{sheet="bookworm-sleeping",tag="idle",first=1,ms=8000,scale=6},
{sheet="bookworm-sleeping",tag="talk.center",first=33,ms=540,scale=6},
{sheet="bookworm-sleeping",tag="intro",first=39,ms=1420,scale=6},
{sheet="bookworm-sleeping",tag="outro",first=49,ms=1240,scale=6},
{sheet="bookworm-digesting",tag="idle",first=1,ms=1060,scale=6},
{sheet="bookworm-digesting",tag="expectant.center",first=7,ms=720,scale=6},
{sheet="bookworm-digesting",tag="eager",first=11,ms=460,scale=6},
{sheet="bookworm-digesting",tag="talk.center",first=15,ms=500,scale=6},
{sheet="bookworm-digesting",tag="gulp.center",first=21,ms=650,scale=6},
{sheet="bookworm-digesting",tag="shake.center",first=28,ms=430,scale=6},
{sheet="bookworm-digesting",tag="cheer.center",first=33,ms=720,scale=6},
{sheet="bookworm-happy",tag="idle",first=1,ms=7170,scale=6},
{sheet="bookworm-happy",tag="attentive.left",first=28,ms=5910,scale=6},
{sheet="bookworm-happy",tag="attentive.center",first=39,ms=5910,scale=6},
{sheet="bookworm-happy",tag="attentive.right",first=50,ms=5910,scale=6},
{sheet="bookworm-happy",tag="expectant.left",first=61,ms=720,scale=6},
{sheet="bookworm-happy",tag="expectant.center",first=65,ms=720,scale=6},
{sheet="bookworm-happy",tag="expectant.right",first=69,ms=720,scale=6},
{sheet="bookworm-happy",tag="eager",first=73,ms=460,scale=6},
{sheet="bookworm-happy",tag="perk.left",first=77,ms=360,scale=6},
{sheet="bookworm-happy",tag="perk.center",first=81,ms=360,scale=6},
{sheet="bookworm-happy",tag="perk.right",first=85,ms=360,scale=6},
{sheet="bookworm-happy",tag="talk.left",first=89,ms=500,scale=6},
{sheet="bookworm-happy",tag="talk.center",first=95,ms=500,scale=6},
{sheet="bookworm-happy",tag="talk.right",first=101,ms=500,scale=6},
{sheet="bookworm-happy",tag="gulp.center",first=107,ms=650,scale=6},
{sheet="bookworm-happy",tag="shake.left",first=114,ms=430,scale=6},
{sheet="bookworm-happy",tag="shake.center",first=119,ms=430,scale=6},
{sheet="bookworm-happy",tag="shake.right",first=124,ms=430,scale=6},
{sheet="bookworm-happy",tag="cheer.center",first=129,ms=720,scale=6},
{sheet="bookworm-hungry",tag="idle",first=1,ms=8800,scale=6},
{sheet="bookworm-hungry",tag="attentive.left",first=18,ms=6070,scale=6},
{sheet="bookworm-hungry",tag="attentive.center",first=29,ms=6070,scale=6},
{sheet="bookworm-hungry",tag="attentive.right",first=40,ms=6070,scale=6},
{sheet="bookworm-hungry",tag="expectant.left",first=51,ms=720,scale=6},
{sheet="bookworm-hungry",tag="expectant.center",first=55,ms=720,scale=6},
{sheet="bookworm-hungry",tag="expectant.right",first=59,ms=720,scale=6},
{sheet="bookworm-hungry",tag="eager",first=63,ms=460,scale=6},
{sheet="bookworm-hungry",tag="perk.left",first=67,ms=360,scale=6},
{sheet="bookworm-hungry",tag="perk.center",first=71,ms=360,scale=6},
{sheet="bookworm-hungry",tag="perk.right",first=75,ms=360,scale=6},
{sheet="bookworm-hungry",tag="talk.left",first=79,ms=500,scale=6},
{sheet="bookworm-hungry",tag="talk.center",first=85,ms=500,scale=6},
{sheet="bookworm-hungry",tag="talk.right",first=91,ms=500,scale=6},
{sheet="bookworm-hungry",tag="gulp.center",first=97,ms=650,scale=6},
{sheet="bookworm-hungry",tag="shake.left",first=104,ms=430,scale=6},
{sheet="bookworm-hungry",tag="shake.center",first=109,ms=430,scale=6},
{sheet="bookworm-hungry",tag="shake.right",first=114,ms=430,scale=6},
{sheet="bookworm-error",tag="idle",first=1,ms=2400,scale=6},
{sheet="bookworm-curious",tag="idle",first=1,ms=3600,scale=6},
{sheet="bookworm-small",tag="awake",first=1,ms=4200,scale=8},
{sheet="bookworm-small",tag="sleeping",first=6,ms=2800,scale=8},
{sheet="bookworm-small",tag="digesting",first=10,ms=500,scale=8},
{sheet="bookworm-small",tag="happy",first=12,ms=3520,scale=8},
{sheet="bookworm-small",tag="curious",first=17,ms=2800,scale=8},
{sheet="bookworm-small",tag="hungry",first=21,ms=4800,scale=8},
{sheet="bookworm-small",tag="reading",first=25,ms=1950,scale=8},
{sheet="bookworm-small",tag="error",first=29,ms=1500,scale=8}
}
local mode=CicadaReviewMode or 'source';local index=(CicadaReviewStart or 1)-1;local current;local playing=false
local lastIndex=CicadaReviewEnd or #plan
local dialog=Dialog{title='Worm fix '..mode..' review'}
local completed={}
local timer
local stepLast
local function stop()
 if playing then app.command.PlayAnimation();playing=false end
end
local function nextClip()
 stop()
 if current then completed[#completed+1]=current.sheet..'/'..current.tag end
 index=index+1;current=index<=lastIndex and plan[index] or nil
 if not current then
  timer:stop();CicadaReview.completed=completed
  local folder=app.fs.filePath(thisFile);package.path=folder..'/?.lua;'..package.path
  require('ase_helpers').writeJson(app.fs.joinPath(ART,'qa/wormfix-native-'..mode..'.json'),{completed=completed,count=#completed,mode=mode})
  dialog:modify{id='status',text='COMPLETE: '..#completed..' clips'};return
 end
 local filename=app.fs.joinPath(ART,mode=='gif' and ('qa/'..current.sheet..'/'..current.tag..'@'..current.scale..'x.gif') or ('src/'..current.sheet..'.aseprite'))
 if not app.activeSprite or app.activeSprite.filename~=filename then
  if app.activeSprite and app.activeSprite.filename:sub(1,#ART)==ART then app.command.CloseFile() end
  app.command.OpenFile{ui=false,filename=filename}
 end
 assert(app.activeSprite and app.activeSprite.filename==filename,'did not open review document')
 app.frame=mode=='gif' and 1 or current.first
 app.editor.zoom=mode=='gif' and 1 or current.scale
 app.editor.scroll={x=app.activeSprite.width/2,y=app.activeSprite.height/2}
 dialog:modify{id='status',text=index..'/'..#plan..' '..current.sheet..'/'..current.tag}
 if mode=='step' then
  for _,tag in ipairs(app.activeSprite.tags) do
   if tag.name==current.tag then stepLast=tag.toFrame.frameNumber;break end
  end
  assert(stepLast,'missing step tag')
  timer.interval=0.2
 else
  app.command.PlayAnimation();playing=true
  timer.interval=current.ms/1000+0.15
 end
 timer:start();app.refresh()
end
CicadaReview={stop=function() stop();timer:stop();dialog:close() end}
dialog:label{id='status',text='Starting'}:button{text='Stop / close',onclick=function() CicadaReview.stop() end}
dialog:show{wait=false,bounds=Rectangle(90,53,650,90)}
timer=Timer{interval=1,ontick=function()
 timer:stop()
 if mode=='step' and app.frame.frameNumber<stepLast then
  app.command.GotoNextFrame();app.refresh();timer:start()
 else nextClip() end
end}
nextClip()
