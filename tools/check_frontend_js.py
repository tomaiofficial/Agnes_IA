from pathlib import Path
import re

html = Path('/home/ubuntu/Agnes_IA/static/index.html').read_text(encoding='utf-8')
blocks = re.findall(r'<script(?:\s[^>]*)?>(.*?)</script>', html, flags=re.S | re.I)
out = Path('/home/ubuntu/Agnes_IA/tools/frontend_inline.js')
out.write_text('\n\n'.join(blocks), encoding='utf-8')
print(f'extracted {len(blocks)} inline script blocks to {out}')
print('function fetchWithAuth present:', 'function fetchWithAuth' in out.read_text(encoding='utf-8'))
print('function openImageMode present:', 'function openImageMode' in out.read_text(encoding='utf-8'))
print('init source check present:', "d.source && d.source !== 'none'" in out.read_text(encoding='utf-8'))
ପ = None
if 'fetchWithAuth' not in out.read_text(encoding='utf-8'):
    raise SystemExit('frontend extraction check failed')
