"""Constants for the Min Fotboll integration."""

from datetime import timedelta

DOMAIN = "min_fotboll"
NAME = "Min Fotboll"
VERSION = "0.1.5"

API_BASE_URL = "https://minfotboll-api.azurewebsites.net"
PLATFORM_ID = "2"
UPDATE_INTERVAL = timedelta(seconds=90)

CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_EXPIRES = "expires"
CONF_SERVER_TIME = "server_time"
CONF_TOKEN_JSON = "token_json"
CONF_SELECTED_TEAMS = "selected_teams"

STATUS_UPCOMING = "KOMMANDE"
STATUS_LIVE = "LIVE"
STATUS_FINISHED = "SLUT"
STATUS_CANCELLED = "INSTÄLLD"
STATUS_POSTPONED = "UPPSKJUTEN"
STATUS_INTERRUPTED = "AVBRUTEN"
STATUS_UNKNOWN = "OKÄND"
