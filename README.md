# Oasis lights for Home Assistant

Mixtiles Oasis lights in Home Assistant, through Oasis's cloud (the lights have
no local API). Each Oasis room becomes one light, put in the Home Assistant area
of the same name; a light that's in no room is a light of its own.

- On/off, brightness, and white temperature (1000-4000 K).
- The Oasis app's presets are the light's effects: Bright, Neutral, Soft, Amber,
  Candle, Dusk, Maui, Pure Red.
- Polled every 30 s. The lights report a change 5-15 s after it's made, so a
  light shows what was sent until they catch up (up to 20 s).

## Install

[![Open in your Home Assistant](https://img.shields.io/badge/Open%20in-Home%20Assistant-41BDF5?style=for-the-badge&logo=homeassistant&logoColor=white)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=jameswestover&repository=oasis_ha&category=integration)

Click the button, pick your Home Assistant if it asks, click **Download**, then
restart Home Assistant.

Or by hand: Settings › Marketplace › ⋮ › Custom repositories, add
`https://github.com/jameswestover/oasis_ha` as an Integration, and download
**Oasis lights**.

Then Settings › Devices & services › Add integration › **Oasis lights**.

## Signing in

The Oasis app offers more than one way to sign in. **Only Google sign-in works
here so far.** If your Oasis account uses another way, this integration can't
sign in to it yet (contributions welcome).

Oasis's Google sign-in returns to the Oasis app's own address
(`com.mixtiles.oasis://success?code=…`), which a browser can't open. So:

1. On a computer, in Chrome, open DevTools (Network tab) and tick **Preserve log**.
2. In that tab, open the sign-in link the setup form shows and sign in with Google.
3. The page stops. Filter the Network list for `code=` and copy the
   `com.mixtiles.oasis://success?code=…` address (or the request's Location header).
4. Paste it into the form within a few minutes (a code works once).

The form also takes a refresh token from an earlier sign-in. When the sign-in
lapses, Home Assistant asks for it again (Settings › Repairs / the integration's
card), with the same form.

## Development

```bash
python -m venv .venv && .venv/bin/pip install pytest-homeassistant-custom-component
.venv/bin/pytest
```

The tests run against a fake Oasis cloud (`tests/conftest.py`).
