-- GUI-only final z correction: short opposing ends make the 3x3 diagonal read.
assert(app.isUIAvailable,'GUI only')
local s=app.activeSprite
assert(s.filename:match('worm%-parts.aseprite$'),'open the saved room parts')
local function frame(n)
 for _,tag in ipairs(s.tags) do if tag.name==n then return tag.fromFrame end end
 error('missing '..n)
end
app.transaction('Clarify the smallest sleeping z',function()
 app.layer=s.layers[1]
 for _,colour in ipairs({'Z','Y','X'}) do
  app.frame=frame('fx.z.s.'..colour)
  for _,point in ipairs({Point(0,0),Point(2,2)}) do
   app.useTool{tool='eraser',brush=Brush(1),points={point}}
  end
 end
end)
app.command.SaveFile()
app.frame=frame('fx.z.s.Z');app.editor.zoom=8;app.editor.scroll={x=1,y=1};app.refresh()
