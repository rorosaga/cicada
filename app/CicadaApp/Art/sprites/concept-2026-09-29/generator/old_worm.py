S=24;T='.'
def blank(): return [T*S for _ in range(S)]
def pad(g,r):
    if r>=len(g): return T*S
    x=g[r]; return (x+T*S)[:S]
def merge(b,o):
    out=[]
    for r in range(S):
        row=list(pad(b,r)); ov=pad(o,r)
        for c in range(S):
            if ov[c]!=T: row[c]=ov[c]
        out.append(''.join(row))
    return out
def glyph(shape,top,left):
    out=[list(x) for x in blank()]
    for i,row in enumerate(shape):
        r=top+i
        if 0<=r<S:
            for j,ch in enumerate(row):
                c=left+j
                if ch!=T and 0<=c<S: out[r][c]=ch
    return [''.join(x) for x in out]
headTop=["........oooooooo........","......oobbbbbbbboo......",".....obbbbbbbbbbbbo....."]
def eyes(p='o',lid='open',gaze='c'):
    lens=lambda i:"a"+i+"a"
    row=lambda l,r:"....ob"+l+"b"+r+"bo..."
    w=lens("wwww"); sh=lens("oooo")
    look={'l':lens(p+p+"ww"),'c':lens("w"+p+p+"w"),'r':lens("ww"+p+p)}[gaze]
    top="....ob"+"aaaaaa"+"a"+"aaaaaa"+"bo..."; bot="....ob"+"aaaaaa"+"b"+"aaaaaa"+"bo..."
    mid={'open':[row(w,w),row(look,look),row(look,look)],'closed':[row(w,w),row(w,w),row(sh,sh)],'half':[row(sh,sh),row(look,look),row(w,w)]}[lid]
    return [top]+mid+[bot]
smile=["....obbrrbbbbbbbbrrbo...",".....obbbobbbbbbobbo....","......obbboooooobbo....."]
neutral=["....obbbbbbbbbbbbbbbo...",".....obbbbbbbbbbbbbo....","......obbbooooobbbo....."]
body=[".......obbbbbbbbbbo.....","........obbllbbbbo......","........obbllbbbbo......",".......obbbllbbbbo......","......obbbllbbbbo.......",".....obbbllbbbbo........","....obbbllbbbbo.........","...obbbbbbbbbo..........","..obbbbbbbboo...........","...ooooooo.............."]
def rep(g,s,rows):
    g=list(g)
    for i,r in enumerate(rows): g[s+i]=r
    return g
def compose(e,m,b=body):
    g=blank(); g=rep(g,2,headTop); g=rep(g,5,e); g=rep(g,10,m); g=rep(g,13,b); return g
cap=glyph([".......oozzzzoo.........",".....oozzzzzzzzzzoo.....","...oowwwwwwwwwwwwoo.....","..owwo.................."],0,0)
bookOpen=["aaaaaaaaa","awwwawwwa","awwwawwwa","aaaaaaaaa"]
zBig=["zzzzz","...z.","..z..",".z...","zzzzz"]
def dots(n):
    row=list(T*S)
    for i,c in enumerate([3,7,11,15,19]): row[c]='a' if i<n else 'o'
    g=blank(); g[23]=''.join(row); return g
def show(name,g):
    print("### "+name); print("```"); 
    for i,r in enumerate(g): print(f"{i:02d} {r}")
    print("```")
show("awake (canonical, awakeBase)",compose(eyes(),smile))
show("reading frame 1 (cap + open book)",merge(merge(compose(eyes(),smile),glyph(bookOpen,15,8)),cap))
show("sleeping(stage 3) frame 2",merge(merge(merge(compose(eyes(lid='closed'),neutral),glyph(zBig,0,19)),dots(3)),cap))
