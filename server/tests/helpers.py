import json
import urllib.error
import urllib.request


class Client:
    def __init__(self, base):
        self.base, self.token = base, None

    def call(self, method, path, body=None, raw=None, headers=None, expect=None):
        h = dict(headers or {})
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req) as r:
                code, payload, ctype = r.status, r.read(), r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            code, payload, ctype = e.code, e.read(), e.headers.get("Content-Type", "")
        out = json.loads(payload) if "json" in ctype and payload else payload
        if expect is not None:
            assert code == expect, (code, out)
        return code, out

    def login(self, user, password="correct horse battery"):
        code, out = self.call("POST", "/api/login", {"username": user, "password": password})
        if code == 200:
            self.token = out["token"]
        return code, out
