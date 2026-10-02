-- Aseprite's batch process can exit zero after a Lua error. Only a completed
-- script writes this marker; the shell checks it before exporting any source.
local params=app.params or {}
local art=assert(params.art,'art parameter required')
local script=assert(params.run,'run parameter required')
local status=assert(params.status,'status parameter required')
assert(script:match('^[%w_%-]+$'),'invalid script name')
dofile(app.fs.joinPath(art,'lua',script..'.lua'))
local file=assert(io.open(status,'w'))
file:write('completed\n')
assert(file:close())
