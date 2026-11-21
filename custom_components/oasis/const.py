"""Constants for Oasis lights."""

from urllib.parse import urlencode

DOMAIN = "oasis"

API = "https://0sb7eb48mj.execute-api.us-east-1.amazonaws.com/dev/v1"
LOGIN = "https://applogin.heyoasis.com/oauth2/token"
CLIENT_ID = "20hc2tbnm5cqipo83tq7fr6lt1"
# Oasis's hosted sign-in. It only returns to the Oasis app's own scheme.
SIGN_IN = "https://applogin.heyoasis.com"
REDIRECT = "com.mixtiles.oasis://success"
LOGIN_QUERY = urlencode({"response_type": "code", "client_id": CLIENT_ID, "redirect_uri": REDIRECT})
LOGIN_PAGE = f"{SIGN_IN}/login?{LOGIN_QUERY}"
# The sign-in buttons the Oasis app offers, besides email and password.
PROVIDERS = {"google": "Google", "apple": "SignInWithApple"}


def authorize(provider: str) -> str:
    """The sign-in page for one of PROVIDERS."""
    return f"{SIGN_IN}/oauth2/authorize?" + urlencode(
        {"response_type": "CODE", "client_id": CLIENT_ID, "redirect_uri": REDIRECT, "identity_provider": PROVIDERS[provider]}
    )


CONF_REFRESH_TOKEN = "refresh_token"
CONF_EMAIL = "email"
CONF_PASSWORD = "password"

# The Oasis app's presets, coolest first. Even "Pure Red" is a white temperature (CCT).
TONES = {
    "Bright": 4000,
    "Neutral": 3300,
    "Soft": 2800,
    "Amber": 2200,
    "Candle": 1800,
    "Dusk": 1500,
    "Maui": 1100,
    "Pure Red": 1000,
}
MIN_KELVIN = min(TONES.values())
MAX_KELVIN = max(TONES.values())

POLL_SECONDS = 30
# Which lights are in which room hardly ever changes; asked again after this long,
# or when a light turns up that's in no known room.
ROOMS_SECONDS = 600
# The lights report a change 5-15 s after it's made. Until they do, a light shows
# what was sent, or a poll in between flips it back.
SETTLE_SECONDS = 20
