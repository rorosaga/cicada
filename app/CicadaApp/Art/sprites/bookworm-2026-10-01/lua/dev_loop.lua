-- dev_loop.lua — rebuild one sprite from its Lua source and report it, for the GUI review loop.
-- CLI:  aseprite -b --script-param build=<build.lua> --script-param result=<file.aseprite> \
--                  --script-param tag=idle --script dev_loop.lua
-- Then: open -a Aseprite <file.aseprite>     (never --script without -b)
local build = app.params.build or DEV_LOOP_BUILD
local result = app.params.result or DEV_LOOP_RESULT
local tagName = app.params.tag or DEV_LOOP_TAG
assert(build and result, 'dev_loop: need build= and result= (params or DEV_LOOP_* globals)')
for _, s in ipairs(app.sprites) do if s.filename == result then s:close() end end
dofile(build)
local spr = app.open(result)
assert(spr, 'dev_loop: could not open ' .. result)
local frameNumber = 1
if tagName then
  for _, t in ipairs(spr.tags) do if t.name == tagName then frameNumber = t.fromFrame.frameNumber end end
end
app.frame = spr.frames[frameNumber]
print(string.format('dev_loop: %s  frames=%d tags=%d  tag %s starts at frame %d', result, #spr.frames, #spr.tags,
  tostring(tagName), frameNumber))
