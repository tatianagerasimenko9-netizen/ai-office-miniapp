import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office_br.telegram_edit import edit_original

class Response:
    def __init__(self, code, body):
        self.status, self.body = code, body
    async def __aenter__(self): return self
    async def __aexit__(self, *args): return None
    async def json(self): return self.body
class Session:
    def __init__(self, code, body):
        self.code, self.body, self.calls = code, body, []
    def post(self, url, json):
        self.calls.append((url,json))
        return Response(self.code,self.body)
class Tests(unittest.IsolatedAsyncioTestCase):
    async def test_success(self):
        s=Session(200, {"ok":True})
        self.assertEqual(await edit_original(s,"x",100,200,"changed"),"EDITED")
        self.assertEqual(s.calls[0][1]["message_id"],200)
    async def test_unchanged(self):
        s=Session(400,{"description":"Bad Request: message is not modified"})
        self.assertEqual(await edit_original(s,"x",100,200,"same"),"UNCHANGED")
    async def test_deleted(self):
        s=Session(400,{"description":"Bad Request: message to edit not found"})
        self.assertEqual(await edit_original(s,"x",100,200,"new"),"UNSUPPORTED")
    async def test_rate_limited(self):
        s=Session(429,{"description":"Too Many Requests"})
        self.assertEqual(await edit_original(s,"x",100,200,"new"),"RETRY")
    async def test_missing_context(self):
        s=Session(200,{"ok":True})
        self.assertEqual(await edit_original(s,"",100,200,"new"),"UNSUPPORTED")
        self.assertFalse(s.calls)
if __name__=="__main__": unittest.main()
