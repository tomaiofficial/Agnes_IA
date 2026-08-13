from pathlib import Path
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server

client = TestClient(server.app)

status = client.get('/api/pollo/status', headers={'X-User-Id': 'local-test'})
assert status.status_code == 200
body = status.json()
assert body['provider'] == 'Pollo AI'
assert 'credits' in body

estimate = client.post('/api/pollo/estimate', json={
    'model': 'veo3-1',
    'resolution': '1080p',
    'duration': 8,
    'audio': True,
})
assert estimate.status_code == 200
assert estimate.json()['credits'] > 0
print('pollo integration smoke test: ok')
