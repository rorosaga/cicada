-- Owner 2026-10-01: diagonal black X eyes, no red. Integer palette strokes.
local E={}
E.roomLeft={x=11,y=18,rows={'K.K','.K.','.K.','K.K'}}
E.roomRight={x=24,y=19,rows={'K....K','.K..K.','..KK..','.K..K.','K....K'}}
E.smallLeft={x=3,y=6,rows={'K.K','.K.','K.K'}}
E.smallRight={x=11,y=6,rows={'K.K','.K.','K.K'}}
local function rect(dot,x,y,w,h,key)
 for yy=y,y+h-1 do for xx=x,x+w-1 do dot(xx,yy,key) end end
end
local function stamp(dot,p)
 for y,row in ipairs(p.rows) do for x=1,#row do if row:sub(x,x)=='K' then dot(p.x+x-1,p.y+y-1,'K') end end end
end
function E.room(dot)
 -- Move only the error's inner left rim one pixel outward. The external
 -- silhouette stays put; a 5x6 green interior leaves air around the small X.
 rect(dot,9,17,1,6,'K');rect(dot,10,17,5,6,'G');rect(dot,23,18,8,7,'G')
 stamp(dot,E.roomLeft);stamp(dot,E.roomRight)
end
function E.small(dot)
 -- Clear all former pupils/highlights; leave the owner's dark rims untouched.
 rect(dot,1,5,6,4,'m');rect(dot,9,5,7,4,'m')
 stamp(dot,E.smallLeft);stamp(dot,E.smallRight)
end
return E
