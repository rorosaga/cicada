import sys, subprocess, json, os, re
P=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'boards') + os.sep
L=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..', 'Sources', 'CicadaApp', 'Resources', 'logos') + os.sep
from ui import ASSET
FILES={'claude':'claude.png','chatgptDark':'chatgpt-dark.png','codexDark':'codex-dark.png','chrome':'chrome.png','youtube':'youtube.png','linkedin':'linkedin.png','xDark':'x-dark.png','reddit':'reddit.png','brave':'brave.png'}
os.makedirs('shots',exist_ok=True)
for name in sys.argv[1:]:
    boards=[]
    for j in ('boards_worm.json','boards_queue.json','boards_view.json'):
        if os.path.exists(j): boards+=json.load(open(j))
    b=[x for x in boards if x['file'].startswith(name)][0]
    s=open(P+b['file']).read()
    for k,v in ASSET.items(): s=s.replace(v,'file://'+L+FILES[k])
    tmp=os.path.abspath('shots/_'+b['file'])
    open(tmp,'w').write(s)
    out=os.path.abspath('shots/'+name+'.png')
    subprocess.run(['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome','--headless=new','--disable-gpu','--hide-scrollbars','--allow-file-access-from-files',f'--window-size={b["w"]},{b["h"]}',f'--screenshot={out}','file://'+tmp],capture_output=True)
    print(out)
