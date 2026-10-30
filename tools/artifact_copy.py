"""Make base64 .txt copies of web/3d packs for hosts that only serve text (the claude.ai artifact)."""
import base64, json, os, sys
import os
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = os.path.join(PROJECT, 'web', '3d')
dst = sys.argv[1]
os.makedirs(dst, exist_ok=True)
for n in os.listdir(src):
    if n.endswith('.bin'):
        open(f'{dst}/{n[:-4]}.txt', 'w').write(base64.b64encode(open(f'{src}/{n}', 'rb').read()).decode())
i = json.load(open(f'{src}/index.json')); i['ext'] = '.txt'
json.dump(i, open(f'{dst}/index.json', 'w'), separators=(',', ':'))
