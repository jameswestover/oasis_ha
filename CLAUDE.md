# Oasis lights (Home Assistant custom integration)

Mixtiles Oasis lights in Home Assistant, through Oasis's cloud. Installed from
Home Assistant's Marketplace (Settings › Marketplace, the built-in successor to
HACS) as a custom repository; `hacs.json` and `custom_components/oasis` at the
root are what it reads.

- Commit to `main` and push `main`. No other branches.
- This repo is public: no personal details, addresses, tokens or account names
  in code, tests, docs or commit messages.
- A change ships by bumping `version` in `custom_components/oasis/manifest.json`:
  `.github/workflows/release.yml` then publishes a GitHub release `v<version>`,
  which is what the Marketplace offers as an update.
- `custom_components/oasis/api.py` is the cloud (stock ESP RainMaker 2.3 behind
  Oasis's Cognito at `applogin.heyoasis.com`, client `20hc2tbnm5cqipo83tq7fr6lt1`,
  no client secret). Refresh tokens aren't rotated; access tokens last 24 h.
- Sign-in, like the Oasis app: Google and Apple (`const.PROVIDERS`) through the
  hosted page, pasting back the `com.mixtiles.oasis://` address; email and password
  by posting the hosted page's own form (`OasisApi.password_sign_in`): the app
  client refuses Cognito's `USER_PASSWORD_AUTH`, and SRP needs the pool id, which
  the page doesn't give. The password is kept so the coordinator can sign in again.
- `PUT /user/nodes/params` `[{"node_id", "payload": {"Light": {"Power", "Brightness", "CCT"}}}]`
  switches lights; rooms are `GET /user/node_group?node_list=true&sub_groups=true`.
- Every Oasis preset is just a `CCT` value (`const.TONES`).
- The lights report a change 5-15 s late, so the coordinator holds what was sent
  for up to 20 s (`SETTLE_SECONDS`) or until they agree.
- Tests: `pytest` with `pytest-homeassistant-custom-component` (fake cloud in
  `tests/conftest.py`). Run them before pushing.
