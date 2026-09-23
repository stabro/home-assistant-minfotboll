# Min Fotboll for Home Assistant

Experimental Home Assistant custom integration for the Swedish **Min Fotboll** service.

> **Status: v0.1.1 developer preview**
>
> The API used by Min Fotboll is undocumented and may change. This integration is not affiliated with Svenska Fotbollförbundet, Min Fotboll or Sportswik.

## What v0.1.1 does

- Reads the teams followed by the signed-in Min Fotboll account.
- Creates one Home Assistant match sensor per followed team.
- Uses the verified `initmain` payload plus the live-timeline endpoint.
- Updates every **90 seconds**.
- Shows the current/live score when a game is live.
- Otherwise shows the most recent finished game's score when available.
- Exposes match status and the latest timeline event as entity attributes.
- Automatically refreshes the Min Fotboll JWT pair when the access token expires.
- Avoids the unverified `teamapi/getlivegames` call that caused HTTP 400 in v0.1.0.

Example attributes:

```yaml
team_id: 406252
club_name: Wargöns IK
team_name: P2012
game_id: 2036482
home_team: Wargöns IK
away_team: Edet FK Blå
score: 1-3
status: SLUT
latest_event: "75' Matchen slut Edet FK"
minute: "75'"
```

## Installation for testing

### HACS custom repository

1. Add this repository to HACS as a custom **Integration** repository.
2. Install **Min Fotboll**.
3. Restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration → Min Fotboll**.

### Manual installation

Copy `custom_components/min_fotboll` to your Home Assistant `config/custom_components/` directory and restart Home Assistant.

## Authentication in v0.1.1

The Min Fotboll web login requests an SMS code through a Google reCAPTCHA-protected web form. A Home Assistant server cannot complete that browser reCAPTCHA flow directly, so the developer preview imports the JWT pair from an existing browser login.

1. Sign in at `minfotboll.svenskfotboll.se` normally with phone number and SMS code.
2. Open your browser developer tools.
3. Open **Application** (Chrome/Edge) → **Cookies** → `https://minfotboll.svenskfotboll.se`.
4. Copy the value of the cookie named `JWT_token`.
5. Paste the complete JSON value into the Min Fotboll config flow in Home Assistant.

The integration stores the token in the Home Assistant config entry and refreshes it through Min Fotboll's refresh-token endpoint. Never post your token in an issue, screenshot or public repository.

Direct phone-number/SMS setup is planned once a safe login flow that does not require automating reCAPTCHA has been identified.

## Entity model

Each followed team gets one sensor. The team ID is used as the entity unique ID, so renaming a team will not create a duplicate entity.

The sensor state is the score (for example `1-3`). Attributes include:

- `status`: `LIVE`, `SLUT`, `INSTÄLLD`, `UPPSKJUTEN`, `AVBRUTEN` or `OKÄND`
- `latest_event`
- `minute`
- `home_team` / `away_team`
- `game_id`
- `game_time`
- `arena`

## Known limitations

- Min Fotboll has no documented public API for this use case.
- v0.1.1 requires importing `JWT_token` from a browser login.
- The exact response shape can vary; this version still needs real-world testing across more accounts and competitions.
- New followed teams are discovered by the coordinator, but Home Assistant currently creates team entities when the integration is loaded. Restart/reload the integration after following a new team in Min Fotboll. Dynamic entity discovery is planned.

## Privacy

The integration sends requests directly from Home Assistant to Min Fotboll's servers. Credentials stay in your Home Assistant config entry. No credentials are included in this repository.

## Development

Repository: `stabro/home-assistant-minfotboll`

Initial reverse engineering was based on requests made by the official Min Fotboll web client, including:

- `/api/mainviewapi/initmain?IsFromWeb=true`
- `/api/followgameapi/initlivetimelineblurbs`
- `/api/jwtapi/refreshtoken`
