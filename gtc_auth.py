"""
gtc_auth.py — GetContact Authentication dengan Device Fingerprint Random
Flow: generate device random → register → send OTP → verify OTP → dapat token
Session disimpan di PostgreSQL (tahan restart Railway)
"""

import json
import uuid
import random
import string
import time
import aiohttp

# Lazy import db agar tidak circular
def _db():
    import db
    return db

# ─────────────────────────────────────────────
#  Konstanta GTC API
# ─────────────────────────────────────────────

GTC_BASE = "https://pbssrv-centralevents.com/v2.4"

GTC_HEADERS_BASE = {
    "Content-Type": "application/json; charset=UTF-8",
    "Accept-Language": "id",
    "X-Os": "android",
    "X-Lang": "id",
    "X-App-Version": "7.2.0",
    "User-Agent": "okhttp/4.9.0",
}

# ─────────────────────────────────────────────
#  Pool device Android populer
# ─────────────────────────────────────────────

ANDROID_DEVICES = [
    {"brand": "samsung", "model": "SM-A325F",   "product": "a32",      "device": "a32",      "android": "12"},
    {"brand": "samsung", "model": "SM-A515F",   "product": "a51",      "device": "a51",      "android": "11"},
    {"brand": "samsung", "model": "SM-G991B",   "product": "o1s",      "device": "o1s",      "android": "13"},
    {"brand": "samsung", "model": "SM-A035F",   "product": "a03s",     "device": "a03s",     "android": "11"},
    {"brand": "samsung", "model": "SM-A125F",   "product": "a12",      "device": "a12",      "android": "11"},
    {"brand": "xiaomi",  "model": "220233L2I",  "product": "sweet_in", "device": "sweet",    "android": "12"},
    {"brand": "xiaomi",  "model": "21091116I",  "product": "lemon",    "device": "lemon",    "android": "11"},
    {"brand": "xiaomi",  "model": "2201116SG",  "product": "lisa",     "device": "lisa",     "android": "12"},
    {"brand": "Redmi",   "model": "220333QNY",  "product": "topaz",    "device": "topaz",    "android": "12"},
    {"brand": "Redmi",   "model": "21121119SC", "product": "eos",      "device": "eos",      "android": "11"},
    {"brand": "realme",  "model": "RMX3231",    "product": "RMX3231",  "device": "RMX3231",  "android": "11"},
    {"brand": "realme",  "model": "RMX3085",    "product": "RMX3085",  "device": "RMX3085",  "android": "11"},
    {"brand": "OPPO",    "model": "CPH2269",    "product": "OP4F7F",   "device": "OP4F7F",   "android": "11"},
    {"brand": "OPPO",    "model": "CPH2135",    "product": "OP4BA9",   "device": "OP4BA9",   "android": "10"},
    {"brand": "vivo",    "model": "V2120",      "product": "V2120",    "device": "V2120",    "android": "12"},
    {"brand": "vivo",    "model": "V2044",      "product": "V2044",    "device": "V2044",    "android": "11"},
]

ANDROID_SDK = {
    "9": "28", "10": "29", "11": "30",
    "12": "31", "13": "33", "14": "34",
}

# ─────────────────────────────────────────────
#  Device Generator
# ─────────────────────────────────────────────

def _rand_hex(n):    return ''.join(random.choices('0123456789abcdef', k=n))
def _rand_digits(n): return ''.join(random.choices(string.digits, k=n))
def _rand_upper(n):  return ''.join(random.choices('0123456789ABCDEF', k=n))

def generate_device() -> dict:
    dev = random.choice(ANDROID_DEVICES)
    av  = dev["android"]
    sdk = ANDROID_SDK.get(av, "30")
    fcm_chars = string.ascii_letters + string.digits + "-_"
    fingerprint = (
        f"{dev['brand']}/{dev['product']}/{dev['device']}:"
        f"{av}/{_rand_upper(8)}.{_rand_digits(6)}/test-keys"
    )
    return {
        "device_id":       str(uuid.uuid4()),
        "android_id":      _rand_hex(16),
        "brand":           dev["brand"],
        "model":           dev["model"],
        "product":         dev["product"],
        "device_name":     dev["device"],
        "android_version": av,
        "sdk_version":     sdk,
        "serial":          _rand_upper(8),
        "imei":            _rand_digits(15),
        "fingerprint":     fingerprint,
        "fcm_token":       ''.join(random.choices(fcm_chars, k=152)),
    }

# ─────────────────────────────────────────────
#  GTCAuth class
# ─────────────────────────────────────────────

class GTCAuth:
    def __init__(self):
        self.device = None
        self.token  = None
        self.phone  = None

    def _headers(self):
        h = dict(GTC_HEADERS_BASE)
        if self.device:
            h["X-Device-Id"]  = self.device["device_id"]
            h["X-Android-Id"] = self.device["android_id"]
        if self.token:
            h["X-Token"]       = self.token
            h["Authorization"] = f"Bearer {self.token}"
        return h

    async def _post(self, path: str, payload: dict) -> dict:
        url = f"{GTC_BASE}{path}"
        async with aiohttp.ClientSession() as s:
            async with s.post(
                url, headers=self._headers(), json=payload,
                ssl=False, timeout=aiohttp.ClientTimeout(total=20)
            ) as r:
                try:
                    return await r.json(content_type=None)
                except Exception:
                    return {"error": True, "raw": await r.text(), "status": r.status}

    async def register_device(self) -> dict:
        self.device = generate_device()
        return await self._post("/user/register-device", {
            "countryCode":       "ID",
            "deviceId":          self.device["device_id"],
            "notificationToken": self.device["fcm_token"],
            "platform":          "android",
            "systemLanguage":    "id",
        })

    async def send_otp(self, phone: str) -> dict:
        self.phone = phone.lstrip("+")
        return await self._post("/user/send-otp", {
            "phoneNumber": f"+{self.phone}",
            "countryCode": "ID",
            "deviceId":    self.device["device_id"],
        })

    async def verify_otp(self, otp: str) -> dict:
        result = await self._post("/user/verify-otp", {
            "phoneNumber":       f"+{self.phone}",
            "otp":               otp.strip(),
            "deviceId":          self.device["device_id"],
            "notificationToken": self.device["fcm_token"],
        })
        token = (
            result.get("token")
            or result.get("data", {}).get("token")
            or result.get("result", {}).get("token")
            or result.get("access_token")
        )
        if token:
            self.token = token
            _db().save_session(token, self.device, self.phone)
        return result

    async def search(self, phone: str) -> dict:
        if not self.token:
            return {"error": True, "message": "Belum login"}
        p = phone if phone.startswith("+") else f"+{phone}"
        return await self._post("/search", {"phoneNumber": p})

    def restore_session(self) -> bool:
        sess = _db().load_session()
        if not sess:
            return False
        self.token  = sess["token"]
        self.device = sess["device"]
        self.phone  = sess["phone"]
        return True


# Singleton
gtc = GTCAuth()

def clear_session():
    _db().clear_session()
    gtc.token  = None
    gtc.device = None
    gtc.phone  = None
