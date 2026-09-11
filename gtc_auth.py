"""
Safe GetContact session client.

- Generates a local device profile for app state/testing only.
- DOES NOT call register-device or attempt to bypass GetContact authentication.
- Admin can save a valid session token obtained through an official login flow.
- Audience reuses that stored admin session.
"""
import uuid
import random
import string
import aiohttp


def _db():
    import db
    return db


GTC_BASE = "https://pbssrv-centralevents.com/v2.4"

GTC_HEADERS_BASE = {
    "Content-Type": "application/json; charset=UTF-8",
    "Accept-Language": "id",
    "X-Os": "android",
    "X-Lang": "id",
    "X-App-Version": "7.2.0",
    "User-Agent": "okhttp/4.9.0",
}

ANDROID_DEVICES = [
    {"brand": "samsung", "model": "SM-A325F", "android": "12", "sdk": "31"},
    {"brand": "samsung", "model": "SM-A515F", "android": "11", "sdk": "30"},
    {"brand": "xiaomi", "model": "2201116SG", "android": "12", "sdk": "31"},
    {"brand": "OPPO", "model": "CPH2269", "android": "11", "sdk": "30"},
    {"brand": "vivo", "model": "V2120", "android": "12", "sdk": "31"},
]


def _rand_hex(n):
    return "".join(random.choices("0123456789abcdef", k=n))


def generate_device():
    d = random.choice(ANDROID_DEVICES)
    return {
        "device_id": str(uuid.uuid4()),
        "android_id": _rand_hex(16),
        "brand": d["brand"],
        "model": d["model"],
        "android_version": d["android"],
        "sdk_version": d["sdk"],
    }


class GTCSession:
    def __init__(self):
        self.device = None
        self.token = None
        self.phone = None

    def _headers(self):
        h = dict(GTC_HEADERS_BASE)
        if self.device:
            h["X-Device-Id"] = self.device["device_id"]
            h["X-Android-Id"] = self.device["android_id"]
        if self.token:
            h["X-Token"] = self.token
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def ensure_device(self):
        if not self.device:
            self.device = generate_device()
        return self.device

    def set_session(self, token, phone=""):
        token = (token or "").strip()
        if not token:
            raise ValueError("Token/session kosong.")
        self.ensure_device()
        self.token = token
        self.phone = (phone or "").strip().lstrip("+")
        _db().save_session(self.token, self.device, self.phone)
        return True

    def restore_session(self):
        sess = _db().load_session()
        if not sess:
            self.ensure_device()
            return False
        self.token = sess["token"]
        self.device = sess["device"] or generate_device()
        self.phone = sess.get("phone") or ""
        return True

    def clear(self):
        _db().clear_session()
        self.token = None
        self.phone = None
        self.device = generate_device()

    async def _post(self, path, payload):
        if not self.token:
            return {"error": True, "message": "Session GetContact belum di-set admin."}

        url = f"{GTC_BASE}{path}"
        async with aiohttp.ClientSession() as s:
            async with s.post(
                url,
                headers=self._headers(),
                json=payload,
                ssl=False,
                timeout=aiohttp.ClientTimeout(total=25),
            ) as r:
                try:
                    body = await r.json(content_type=None)
                except Exception:
                    body = {"raw": await r.text()}

                if not isinstance(body, dict):
                    body = {"data": body}

                body.setdefault("http_status", r.status)
                if r.status >= 400:
                    body["error"] = True
                return body

    async def search(self, phone):
        p = phone if phone.startswith("+") else f"+{phone}"
        return await self._post("/search", {"phoneNumber": p})


gtc = GTCSession()


def clear_session():
    gtc.clear()
