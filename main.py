# main.py - METAR taxi light for Raspberry Pi Pico W + NeoPixel ring
#
# Notes:
# - Requires MicroPython firmware for Pico W.
# - You will likely need the "urequests.py" module copied onto the Pico.
# - Also ensure "neopixel" module is available (it is included in most Pico builds).

import time
import math
import random

import network
import ntptime

try:
    import urequests as requests
except ImportError:
    # Fallback name on some builds
    import requests

from machine import Pin
import neopixel

import config

# ===== Global state =====

np = neopixel.NeoPixel(Pin(config.LED_PIN, Pin.OUT), config.LED_COUNT)

last_metar_update = 0
last_sun_update = 0

flight_category = "UNKNOWN"
has_gusts = False
has_lightning = False
sustained_wind_kt = 0

sunrise_sec_local = 6 * 3600   # fallback 06:00 local
sunset_sec_local = 18 * 3600   # fallback 18:00 local


# ===== Utility functions =====

def log(msg):
    # Simple logger; replace with LED codes if you want silent operation
    print("[LOG]", msg)


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        log("Connecting to WiFi...")
        wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
        timeout = 20
        while timeout > 0 and not wlan.isconnected():
            time.sleep(1)
            timeout -= 1
            print(".", end="")
        print()
    if wlan.isconnected():
        log("WiFi connected, IP: {}".format(wlan.ifconfig()[0]))
    else:
        log("Failed to connect to WiFi")
    return wlan


def sync_time():
    # Set RTC from NTP; will be in UTC
    try:
        log("Syncing time via NTP...")
        ntptime.settime()
        log("Time sync OK")
    except Exception as e:
        log("NTP sync failed: {}".format(e))


def http_get_json(url, timeout=10):
    log("GET {}".format(url))
    resp = None
    try:
        resp = requests.get(url, timeout=timeout)
        data = resp.json()
        resp.close()
        return data
    except Exception as e:
        log("HTTP JSON error: {}".format(e))
        try:
            if resp:
                resp.close()
        except Exception:
            pass
        return None


def http_get_text(url, timeout=10):
    log("GET {}".format(url))
    resp = None
    try:
        resp = requests.get(url, timeout=timeout)
        text = resp.text
        resp.close()
        return text
    except Exception as e:
        log("HTTP text error: {}".format(e))
        try:
            if resp:
                resp.close()
        except Exception:
            pass
        return None


def iso_time_to_seconds_since_midnight(iso_str):
    """
    Convert an ISO 8601 timestamp string to seconds since midnight (UTC) for that day.
    Example: "2025-11-29T13:05:23+00:00"
    """
    try:
        # Split off timezone offset
        if "T" not in iso_str:
            return 0
        date_part, time_part = iso_str.split("T", 1)
        # Remove offset (+HH:MM or -HH:MM)
        if "+" in time_part:
            time_part = time_part.split("+", 1)[0]
        elif "-" in time_part:
            # careful: the time part may contain '-' for offset, but not for time itself
            # split on last '-' to avoid truncating the date already removed
            parts = time_part.rsplit("-", 1)
            time_part = parts[0]
        # Strip possible 'Z'
        time_part = time_part.replace("Z", "")
        # Drop fractional seconds if present
        if "." in time_part:
            time_part = time_part.split(".", 1)[0]
        hh, mm, ss = time_part.split(":")
        h = int(hh)
        m = int(mm)
        s = int(ss)
        return h * 3600 + m * 60 + s
    except Exception as e:
        log("Failed to parse ISO time '{}': {}".format(iso_str, e))
        return 0


def update_sun_times():
    global sunrise_sec_local, sunset_sec_local, last_sun_update

    if not config.USE_SUN_TIMES:
        return

    url = "https://api.sunrise-sunset.org/json?lat={}&lng={}&formatted=0".format(
        config.LATITUDE, config.LONGITUDE
    )
    data = http_get_json(url)
    if not data or "results" not in data:
        log("Sun API failed; keeping old sun times")
        return

    results = data["results"]
    sr_iso = results.get("sunrise")
    ss_iso = results.get("sunset")
    if not sr_iso or not ss_iso:
        log("Sun API missing sunrise/sunset")
        return

    sr_utc = iso_time_to_seconds_since_midnight(sr_iso)
    ss_utc = iso_time_to_seconds_since_midnight(ss_iso)

    offset = int(config.UTC_OFFSET_HOURS)
    sunrise_sec_local = (sr_utc + offset * 3600) % 86400
    sunset_sec_local = (ss_utc + offset * 3600) % 86400
    last_sun_update = time.time()

    log("Sunrise local sec: {}, sunset local sec: {}".format(
        sunrise_sec_local, sunset_sec_local
    ))


def get_local_seconds_of_day():
    # MicroPython time.localtime() is UTC by default; apply offset
    t = time.localtime()
    utc_sec = t[3] * 3600 + t[4] * 60 + t[5]
    offset = int(config.UTC_OFFSET_HOURS)
    local_sec = (utc_sec + offset * 3600) % 86400
    return local_sec


def current_brightness():
    if not config.USE_SUN_TIMES:
        # fallback fixed-day assumption
        hour = time.localtime()[3] + int(config.UTC_OFFSET_HOURS)
        if hour < 0:
            hour += 24
        elif hour >= 24:
            hour -= 24
        if 7 <= hour < 20:
            return config.DAY_BRIGHTNESS
        else:
            return config.NIGHT_BRIGHTNESS

    sec = get_local_seconds_of_day()
    # Handle possible midnight wrap
    if sunrise_sec_local < sunset_sec_local:
        # Normal case
        if sunrise_sec_local <= sec < sunset_sec_local:
            return config.DAY_BRIGHTNESS
        else:
            return config.NIGHT_BRIGHTNESS
    else:
        # Polar / weird case where sunrise after sunset
        if sec >= sunrise_sec_local or sec < sunset_sec_local:
            return config.DAY_BRIGHTNESS
        else:
            return config.NIGHT_BRIGHTNESS


# ===== METAR handling =====

def fetch_metar(icao):
    url = "https://tgftp.nws.noaa.gov/data/observations/metar/stations/{}.TXT".format(
        icao.upper()
    )
    text = http_get_text(url)
    if not text:
        return None
    lines = text.strip().splitlines()
    if not lines:
        return None
    # Last line is the raw METAR
    return lines[-1].strip()


def parse_visibility_sm(tokens):
    """
    Parse visibility in statute miles from METAR tokens.
    Looks for tokens with 'SM'. Handles simple patterns like:
    '10SM', '5SM', '3/4SM', '1 1/2SM', 'P6SM', 'M1/4SM'
    Returns float (SM) or None.
    """
    vis = None
    for i, tok in enumerate(tokens):
        if "SM" not in tok:
            continue
        raw = tok.replace("SM", "")

        whole = 0.0
        frac = 0.0

        # Handle patterns like 'P6' (greater than 6) or 'M1/4'
        greater = raw.startswith("P")
        less_than = raw.startswith("M")
        if greater or less_than:
            raw = raw[1:]

        # Sometimes whole number and fraction are split: '1' '1/2SM'
        prev = tokens[i - 1] if i > 0 else ""
        if "/" in raw and prev.isdigit():
            whole = float(prev)
            frac_num, frac_den = raw.split("/", 1)
            try:
                frac = float(frac_num) / float(frac_den)
            except Exception:
                frac = 0.0
        elif "/" in raw:
            # fraction only, like '1/2'
            try:
                num, den = raw.split("/", 1)
                frac = float(num) / float(den)
            except Exception:
                frac = 0.0
        elif raw.strip() != "":
            # whole number only
            try:
                whole = float(raw)
            except Exception:
                whole = 0.0

        value = whole + frac

        if greater:
            # 'P6SM' etc → treat as 10SM
            if value <= 0:
                value = 10.0
        if less_than:
            # 'M1/4SM' → treat as 0.25SM
            if value <= 0:
                value = 0.25

        vis = value
        break

    return vis


def parse_ceiling_ft(tokens):
    """
    Find lowest ceiling (BKN/OVC/VV) in feet.
    Returns int feet or None.
    """
    ceiling_ft = None
    for tok in tokens:
        if tok.startswith("BKN") or tok.startswith("OVC") or tok.startswith("VV"):
            if len(tok) >= 6:
                height_part = tok[3:6]
                if height_part.isdigit():
                    h = int(height_part) * 100
                    if ceiling_ft is None or h < ceiling_ft:
                        ceiling_ft = h
    return ceiling_ft


def parse_wind(tokens):
    """
    Parse sustained wind speed and gust presence from METAR tokens.
    Returns (sustained_knots, has_gusts)
    """
    sustained = 0
    gust = False
    for tok in tokens:
        if tok.endswith("KT") and ("G" in tok or tok[0:3].isdigit() or tok.startswith("VRB")):
            # Example: 18012G20KT, 09005KT, VRB03KT
            body = tok[:-2]  # drop 'KT'
            # Remove optional unit 'KT' already removed, handle VRB
            if body.startswith("VRB"):
                body = body[3:]
            else:
                body = body[3:]  # strip dir
            if "G" in body:
                parts = body.split("G", 1)
                spd = parts[0]
                gspd = parts[1]
                gust = True
            else:
                spd = body
            try:
                sustained = int(spd)
            except Exception:
                sustained = 0
            break
    return sustained, gust


def has_lightning_from_metar(metar):
    """
    Very simple detection: look for TS, VCTS, or LTG in the METAR.
    """
    if "TS" in metar or "VCTS" in metar or "LTG" in metar:
        return True
    return False


def classify_flight_category(ceiling_ft, visibility_sm):
    """
    FAA-style categories: LIFR, IFR, MVFR, VFR
    """
    if visibility_sm is None:
        visibility_sm = 10.0
    if ceiling_ft is None:
        ceiling_ft = 99999

    if ceiling_ft < 500 or visibility_sm < 1.0:
        return "LIFR"
    elif ceiling_ft < 1000 or visibility_sm < 3.0:
        return "IFR"
    elif ceiling_ft <= 3000 or visibility_sm <= 5.0:
        return "MVFR"
    else:
        return "VFR"


def update_metar_state():
    global last_metar_update, flight_category, has_gusts, has_lightning, sustained_wind_kt

    metar = fetch_metar(config.AIRPORT_ICAO)
    if not metar:
        log("Failed to fetch METAR")
        return

    log("METAR: {}".format(metar))

    tokens = metar.split()

    vis_sm = parse_visibility_sm(tokens)
    ceil_ft = parse_ceiling_ft(tokens)
    sustained_wind_kt, gust_flag = parse_wind(tokens)
    lightning_flag = has_lightning_from_metar(metar)

    cat = classify_flight_category(ceil_ft, vis_sm)

    flight_category = cat
    has_gusts = gust_flag
    has_lightning = lightning_flag

    last_metar_update = time.time()

    log("Category: {}, vis: {} SM, ceil: {} ft, wind: {} kt, gusts: {}, lightning: {}".format(
        flight_category, vis_sm, ceil_ft, sustained_wind_kt, has_gusts, has_lightning
    ))


# ===== LED / animation =====

def get_base_color_for_category(cat):
    if cat == "VFR":
        return config.COLOR_VFR
    elif cat == "MVFR":
        return config.COLOR_MVFR
    elif cat == "IFR":
        return config.COLOR_IFR
    elif cat == "LIFR":
        return config.COLOR_LIFR
    else:
        return config.COLOR_UNKNOWN


def apply_brightness_to_color(color, brightness):
    r, g, b = color
    return (
        int(r * brightness),
        int(g * brightness),
        int(b * brightness),
    )


def show_static_color(color):
    for i in range(config.LED_COUNT):
        np[i] = color
    np.write()


def animate_frame():
    """
    Called frequently in the main loop to update the ring based on
    current METAR state and time of day.
    """
    base_color = get_base_color_for_category(flight_category)
    base_brightness = current_brightness()

    # Start from base brightness
    brightness = base_brightness

    # Gust breathing: modulate brightness slowly if gusts present
    if config.ENABLE_GUST_BREATHING and has_gusts:
        now = time.ticks_ms() / 1000.0

        # Base sine phase 0..1
        raw = (math.sin(
            2 * math.pi * now / config.GUST_BREATH_PERIOD_SEC
        ) + 1.0) / 2.0

        # Ease-in-out curve: slows down near extremes so steps are less visible
        # You can play with the exponent; 2.0–3.0 is usually nice.
        eased = raw ** 2.5

        span = config.GUST_BREATH_MAX - config.GUST_BREATH_MIN
        breath_factor = config.GUST_BREATH_MIN + span * eased

        brightness = base_brightness * breath_factor
    else:
        brightness = base_brightness


    # Apply brightness to base color
    r, g, b = apply_brightness_to_color(base_color, brightness)

    # NOTE: we no longer tint high winds toward yellow.
    # HIGH_WIND_THRESHOLD_KT is available if you want special behavior later.

    # Fill the ring with the (possibly breathing) color
    for i in range(config.LED_COUNT):
        np[i] = (r, g, b)

    # Lightning flashes: occasionally overlay bright white flashes
    if config.ENABLE_LIGHTNING_EFFECT and has_lightning:
        if random.random() < config.LIGHTNING_FREQUENCY:
            flash_count = max(1, config.LED_COUNT // 4)
            for _ in range(flash_count):
                idx = random.randint(0, config.LED_COUNT - 1)
                np[idx] = apply_brightness_to_color((255 * config.LIGHTNING_BRIGHTNESS,
                                                     255 * config.LIGHTNING_BRIGHTNESS,
                                                     255 * config.LIGHTNING_BRIGHTNESS), brightness)

    np.write()


# ===== Main =====

def main():
    global last_metar_update, last_sun_update

    wlan = connect_wifi()
    if not wlan.isconnected():
        # Flash red forever
        while True:
            for i in range(config.LED_COUNT):
                np[i] = (50, 0, 0)
            np.write()
            time.sleep(0.5)
            show_static_color((0, 0, 0))
            time.sleep(0.5)

    sync_time()
    update_sun_times()
    update_metar_state()

    frame_delay = 0.02  # seconds between animation frames

    while True:
        now = time.time()

        # Refresh sun times periodically
        if config.USE_SUN_TIMES and (now - last_sun_update) > config.SUN_TIMES_REFRESH_SECONDS:
            update_sun_times()

        # Refresh METAR periodically
        if (now - last_metar_update) > config.UPDATE_INTERVAL_SECONDS:
            update_metar_state()

        # Update LED animation
        animate_frame()

        time.sleep(frame_delay)


# Run main if this file is executed directly
if __name__ == "__main__":
    main()


