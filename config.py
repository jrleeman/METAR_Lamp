# config.py - User configuration for METAR taxi light on Pico W

# ===== WiFi Settings =====
WIFI_SSID = "NETWORK SSID"
WIFI_PASSWORD = "NETWORK PASSWD"

# ===== Airport / METAR Settings =====
AIRPORT_ICAO = "KSLG"          # e.g. "KJFK", "KDEN"
UPDATE_INTERVAL_SECONDS = 300  # How often to refresh METAR (seconds)

# ===== Location / Time Settings =====
# Used for sunrise/sunset-based brightness.
LATITUDE = 36.1859      # positive = north, negative = south
LONGITUDE = -94.5416    # positive = east, negative = west
USE_SUN_TIMES = True

# Local offset from UTC in hours (e.g. -6 for CST, -5 for CDT)
UTC_OFFSET_HOURS = -6

# How often to refresh sunrise/sunset times (seconds)
SUN_TIMES_REFRESH_SECONDS = 6 * 60 * 60  # every 6 hours

# ===== Brightness Settings (0.0 to 1.0) =====
DAY_BRIGHTNESS = 0.7
NIGHT_BRIGHTNESS = 0.2

# ===== Visual Effect Toggles =====
ENABLE_GUST_BREATHING = True      # pulse if gusts present
ENABLE_LIGHTNING_EFFECT = True    # flashes if thunderstorms/lightning present

# Gust breathing parameters
# Brightness scales between MIN and MAX when gusts present
GUST_BREATH_MIN = 0.6      # % of base brightness
GUST_BREATH_MAX = 1.0      # % of base brightness
GUST_BREATH_PERIOD_SEC = 5.0  # one full in/out cycle every X seconds

# Lightning parameters
LIGHTNING_FREQUENCY = 0.02
LIGHTNING_BRIGHTNESS = 0.6

# If sustained wind >= this (in knots), treat as "high wind"
# (no longer changes color – you can remove this later if you want)
HIGH_WIND_THRESHOLD_KT = 25

# ===== LED Ring / Hardware Settings =====
LED_PIN = 2            # Pico GPIO number used for NeoPixel data
LED_COUNT = 24         # number of LEDs in the ring
LED_ORDER = "GRB"      # most WS2812 are GRB

# ===== Color Mapping for Flight Categories =====
# RGB tuples, 0-255 each
COLOR_VFR = (0, 255, 0)        # green
COLOR_MVFR = (0, 0, 255)       # blue
COLOR_IFR = (255, 0, 0)        # red
COLOR_LIFR = (255, 0, 255)     # magenta
COLOR_UNKNOWN = (255, 255, 255)  # white

