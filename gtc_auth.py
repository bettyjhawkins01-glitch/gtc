"""
GetContact authentication/session client.

Important:
- Audience never logs in.
- A single admin-owned GetContact session is shared by the bot.
- OTP delivery channel is ultimately controlled by GetContact's server.
  We send a WhatsApp preference hint; if the upstream API ignores it,
  delivery may still fall back to SMS/app.
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
    {"brand": "samsung", "model": "SM-A325F", "product": "a32", "device": "a32", "android": "12"},
    {"brand": "samsung", "model": "SM-A515F", "product": "a51", "device": "a51", "android": "11"},
    {"brand": "xiaomi", "model": "2201116SG", "product": "lisa", "device": "lisa", "android": "12"},
    {"brand": "OPPO", "model": "CPH2269", "product": "OP4F7F", "device": "OP4F7F", "android": "11"},
    {"brand": "vivo", "model": "V2120", "product": "V2120", "device": "V2120", "android": "12"},
]
ANDROID_SDK = {"10": "29", "11": "30", "12": "31", "13": "33", "14": "34"}


def _rand_hex(n):
    return "".join(random.choices("0123456789abcdef", k=n))


def _rand_digits(n):
    return "".join(random.choices(string.digits, k=n))


def _rand_upper(n):
    return "".join(random.choices("0123456789ABCDEF", k=n))


def generate_device():
    dev = random.choice(ANDROID_DEVICES)
    av = dev["android"]
    fcm_chars = string.ascii_letters + string.digits + "-_"
    return {
        "device_id": str(uuid.uuid4()),
        "android_id": _rand_hex(16),
        "brand": dev["brand"],
        "model": dev["model"],
        "product": dev["product"],
        "device_name": dev["device"],
        "android_version": av,
        "sdk_version": ANDROID_SDK.get(av, "30"),
        "serial": _rand_upper(8),
        "imei": _rand_digits(15),
        "fingerprint": (
            f"{dev['brand']}/{dev['product']}/{dev['device']}:"
            f"{av}/{_rand_upper(8)}.{_rand_digits(6)}/test-keys"
        ),
        "fcm_token": "".join(random.choices(fcm_chars, k=152)),
    }


class GTCAuth:
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

    async def _post(self, path, payload):
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

    async def register_device(self):
        self.device = generate_device()
        return await self._post(
            "/user/register-device",
            {
                "countryCode": "ID",
                "deviceId": self.device["device_id"],
                "notificationToken": self.device["fcm_token"],
                "platform": "android",
                "systemLanguage": "id",
            },
        )

    async def send_otp(self, phone, prefer_whatsapp=True):
        self.phone = phone.lstrip("+")
        payload = {
            "phoneNumber": f"+{self.phone}",
            "countryCode": "ID",
            "deviceId": self.device["device_id"],
        }

        # Best-effort preference only. If unsupported, GetContact may ignore it.
        if prefer_whatsapp:
            payload["channel"] = "whatsapp"
            payload["deliveryMethod"] = "whatsapp"

        return await self._post("/user/send-otp", payload)

    async def verify_otp(self, otp):
        result = await self._post(
            "/user/verify-otp",
            {
                "phoneNumber": f"+{self.phone}",
                "otp": otp.strip(),
                "deviceId": self.device["device_id"],
                "notificationToken": self.device["fcm_token"],
            },
        )
        token = (
            result.get("token")
            or (result.get("data") or {}).get("token")
            or (result.get("result") or {}).get("token")
            or result.get("access_token")
        )
        if token:
            self.token = token
            _db().save_session(token, self.device, self.phone)
        return result

    async def search(self, phone):
        if not self.token:
            return {"error": True, "message": "Session GetContact belum aktif"}
        p = phone if phone.startswith("+") else f"+{phone}"
        return await self._post("/search", {"phoneNumber": p})

    def restore_session(self):
        sess = _db().load_session()
        if not sess:
            return False
        self.token = sess["token"]
        self.device = sess["device"]
        self.phone = sess["phone"]
        return True


gtc = GTCAuth()


def clear_session():
    _db().clear_session()
    gtc.token = None
    gtc.device = None
    gtc.phone = None
