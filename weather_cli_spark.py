#!/usr/bin/env python3
"""
weather_cli_spark.py — CLI weather + 3-day forecast + hourly sparkline (ASCII)

Usage:
  python weather_cli_spark.py            # uses saved city or prompts
  python weather_cli_spark.py London     # search a city
  python weather_cli_spark.py --coords 51.5 -0.1

Dependencies: requests
Install: pip install requests
"""

import sys, os, json, time
from datetime import datetime
try:
    import requests
except ImportError:
    print("Install requests: pip install requests")
    raise SystemExit(1)

# ---------- CONFIG ----------
OPENWEATHER_KEY = "REMOVED_OPENWEATHER_KEY"   # <<< your key
USE_OWM = bool(OPENWEATHER_KEY)

CFG_PATH = os.path.expanduser("~/.weather_cfg.json")
DEFAULT_CITY = "London"

# ---------- small helpers ----------
def load_cfg():
    try:
        return json.load(open(CFG_PATH, "r"))
    except Exception:
        return {}

def save_cfg(cfg):
    try:
        json.dump(cfg, open(CFG_PATH, "w"))
    except Exception:
        pass

def human_time(ts, tz_offset=0):
    return datetime.utcfromtimestamp(ts + tz_offset).strftime("%Y-%m-%d %H:%M")

def cap(s): return s.capitalize() if isinstance(s, str) else s

# sparkline helper using block characters
SPARK = "▁▂▃▄▅▆▇█"
def sparkline(values, width=24):
    if not values: return ""
    # sample/fit to width
    if len(values) > width:
        step = len(values) / width
        vals = [values[int(i*step)] for i in range(width)]
    else:
        vals = values + [values[-1]]*(width - len(values))
    lo = min(vals); hi = max(vals)
    if hi == lo:
        return "".join(SPARK[0] for _ in vals)
    out = ""
    for v in vals:
        idx = int((v - lo) / (hi - lo) * (len(SPARK)-1))
        out += SPARK[max(0, min(len(SPARK)-1, idx))]
    return out

# ---------- OWM fetchers ----------
def geocode_owm(city):
    url = f"https://api.openweathermap.org/geo/1.0/direct?q={requests.utils.requote_uri(city)}&limit=1&appid={OPENWEATHER_KEY}"
    r = requests.get(url, timeout=8); r.raise_for_status()
    j = r.json()
    if not j: raise ValueError("City not found")
    it = j[0]; return it["lat"], it["lon"], it.get("name", city), it.get("country","")

# ---------- OWM fetchers (replace older fetch_onecall) ----------
def fetch_onecall(lat, lon, units="metric"):
    """
    Try One Call. If it fails (401 or other), fall back to /weather + /forecast.
    Returns a dict compatible with the rest of the script: keys: current, hourly, daily, timezone_offset
    """
    base_one = ("https://api.openweathermap.org/data/2.5/onecall"
                f"?lat={lat}&lon={lon}&units={units}&exclude=minutely,alerts&appid={OPENWEATHER_KEY}")
    try:
        r = requests.get(base_one, timeout=10)
        if r.status_code == 200:
            return r.json()
        else:
            # if unauthorized or other problem, fall back
            # print debug (you can comment this out)
            # print("One Call failed:", r.status_code, r.text)
            return fetch_weather_and_forecast(lat, lon, units)
    except requests.RequestException:
        return fetch_weather_and_forecast(lat, lon, units)

def fetch_weather_and_forecast(lat, lon, units="metric"):
    """
    Use /weather (current) and /forecast (3-hourly) to build a simpler compatible payload.
    """
    # current
    cur_url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&units={units}&appid={OPENWEATHER_KEY}"
    fr_url  = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&units={units}&appid={OPENWEATHER_KEY}"
    rcur = requests.get(cur_url, timeout=8); rcur.raise_for_status(); cur = rcur.json()
    rfr  = requests.get(fr_url, timeout=8);  rfr.raise_for_status(); fr = rfr.json()

    # build hourly: take up to next 24 3-hour entries and interpolate to hourly-ish by repeating
    fr_list = fr.get("list", [])  # 3-hour steps
    # extract hourly-like temps (we'll approximate by repeating each 3-hr entry 3 times so length>=24)
    hourly = []
    for item in fr_list:
        # item.dt is unix ts
        hourly.append({
            "dt": item.get("dt"),
            "temp": item.get("main",{}).get("temp"),
            "weather": item.get("weather",[])
        })
        if len(hourly) >= 24:
            break
    # If there are fewer than 24 entries, pad with last known
    if hourly and len(hourly) < 24:
        last = hourly[-1]
        while len(hourly) < 24:
            hourly.append(last)

    # build daily: aggregate by calendar day (simple min/max and choose midday weather)
    daily_map = {}
    for item in fr_list:
        dt = item.get("dt")
        day = datetime.utcfromtimestamp(dt).date()
        t = item.get("main",{})
        w = item.get("weather",[{}])[0]
        entry = daily_map.setdefault(day, {"temps":[], "weathers":[], "dts":[]})
        entry["temps"].append((t.get("temp_min"), t.get("temp_max")))
        entry["weathers"].append(w)
        entry["dts"].append(dt)
    # create list sorted by day; skip today to mirror OneCall's indexing where daily[0] is today
    daily = []
    for day in sorted(daily_map.keys()):
        group = daily_map[day]
        # compute min/max
        mins = [a for a,b in group["temps"] if a is not None]
        maxs = [b for a,b in group["temps"] if b is not None]
        tmin = min(mins) if mins else None
        tmax = max(maxs) if maxs else None
        # choose a representative weather (middle)
        mid_idx = len(group["weathers"])//2
        w = group["weathers"][mid_idx] if group["weathers"] else {}
        # take a dt (midday-ish)
        dt_val = group["dts"][mid_idx] if group["dts"] else int(time.time())
        daily.append({
            "dt": dt_val,
            "temp": {"min": tmin, "max": tmax},
            "weather": [w]
        })

    # Construct a OneCall-like dict
    owm_like = {
        "current": {
            "dt": cur.get("dt"),
            "temp": cur.get("main",{}).get("temp"),
            "feels_like": cur.get("main",{}).get("feels_like"),
            "humidity": cur.get("main",{}).get("humidity"),
            "wind_speed": cur.get("wind",{}).get("speed"),
            "weather": cur.get("weather",[])
        },
        "hourly": hourly,
        "daily": daily,
        "timezone_offset": 0
    }
    return owm_like

# wttr fallback
def fetch_wttr_city(city):
    r = requests.get(f"https://wttr.in/{requests.utils.requote_uri(city)}?format=j1", timeout=10)
    r.raise_for_status(); return r.json()

# ---------- Render ----------
ICON = {
    "Thunderstorm":"⛈️","Drizzle":"🌦️","Rain":"🌧️","Snow":"❄️","Clear":"☀️",
    "Clouds":"☁️","Mist":"🌫️","Smoke":"🌫️","Haze":"🌫️","Fog":"🌫️","Dust":"🌫️",
    "Ash":"🌋","Squall":"🌬️","Tornado":"🌪️"
}

def print_banner():
    print("="*48)
    print(" Quick Weather — CLI with hourly sparkline")
    print("="*48)

def render_owm(data, place_label, units):
    cur = data.get("current", {})
    daily = data.get("daily", [])
    hourly = data.get("hourly", [])
    tz_offset = data.get("timezone_offset", 0)
    unit_sym = "°C" if units=="metric" else "°F"

    w = cur.get("weather",[{}])[0]
    desc = w.get("description","")
    main = w.get("main","")
    icon = ICON.get(main,"")

    temps_hourly = [h.get("temp") for h in hourly[:24]]  # next 24h
    print_banner()
    print(f"Location: {place_label}")
    print(f"Time: {human_time(cur.get('dt', int(time.time())), tz_offset)}")
    print()
    print(f"{icon} {cap(desc)}")
    print(f"Temp: {round(cur.get('temp',0))}{unit_sym}  Feels: {round(cur.get('feels_like',0))}{unit_sym}")
    print(f"Humidity: {cur.get('humidity','—')}%  Wind: {round(cur.get('wind_speed',0))} {'m/s' if units=='metric' else 'mph'}")
    print("-"*48)
    # hourly spark
    if temps_hourly:
        print("Next 24h:")
        print(sparkline(temps_hourly, width=36), end=" ")
        # show min/max markers
        mn = round(min(temps_hourly)); mx = round(max(temps_hourly))
        print(f"  min {mn}{unit_sym}  max {mx}{unit_sym}")
    print("-"*48)
    print("3-day forecast:")
    for i in range(1,4):
        if i>=len(daily): break
        d = daily[i]
        ddate = datetime.utcfromtimestamp(d["dt"]+tz_offset).strftime("%a %d %b")
        mdesc = d.get("weather",[{}])[0].get("description","")
        tmax = round(d.get("temp",{}).get("max",0)); tmin = round(d.get("temp",{}).get("min",0))
        print(f"{ddate}: {cap(mdesc):18}  {tmax}{unit_sym}/{tmin}{unit_sym}")
    print("="*48)

def render_wttr(data, place_label, units):
    cur = data.get("current_condition",[{}])[0]
    days = data.get("weather",[])
    unit_sym = "°C" if units=="metric" else "°F"
    temp = cur.get("temp_C") if units=="metric" else cur.get("temp_F")
    feels = cur.get("FeelsLikeC") if units=="metric" else cur.get("FeelsLikeF")
    desc = (cur.get("weatherDesc") or [{}])[0].get("value","")
    print_banner()
    print(f"Location: {place_label}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print()
    print(cap(desc))
    print(f"Temp: {temp}{unit_sym}  Feels: {feels}{unit_sym}")
    print("-"*48)
    print("3-day forecast:")
    for d in days[1:4]:
        dt = datetime.strptime(d["date"], "%Y-%m-%d").strftime("%a %d %b")
        tmax = d.get("maxtempC") if units=="metric" else d.get("maxtempF")
        tmin = d.get("mintempC") if units=="metric" else d.get("mintempF")
        print(f"{dt}: {tmax}{unit_sym}/{tmin}{unit_sym}")
    print("="*48)

# ---------- CLI ----------
def main():
    cfg = load_cfg()
    units = cfg.get("units","metric")
    last_city = cfg.get("last_city", DEFAULT_CITY)

    args = sys.argv[1:]
    lat = lon = None; city = None

    if args:
        if args[0] in ("--coords","-c") and len(args)>=3:
            try:
                lat=float(args[1]); lon=float(args[2])
                place_label = f"Lat {lat:.3f}, Lon {lon:.3f}"
            except:
                print("Bad coords. --coords LAT LON"); return
        else:
            city = " ".join(args); place_label = city; last_city = city
    else:
        if last_city:
            city = last_city; place_label = city
        else:
            city = input(f"City [{DEFAULT_CITY}]: ").strip() or DEFAULT_CITY
            place_label = city; last_city = city

    print("\nOptions: [u] toggle units  [q] quit  [Enter] continue")
    k = input("Choice: ").strip().lower()
    if k == 'u':
        units = "imperial" if units=="metric" else "metric"
        print("Units set to", ("°F" if units=="imperial" else "°C"))

    cfg["units"] = units; cfg["last_city"] = last_city; save_cfg(cfg)

    try:
        if USE_OWM and city:
            lat, lon, name, country = geocode_owm(city)
            place_label = f"{name}, {country}" if country else name
            data = fetch_onecall(lat, lon, units=units)
            render_owm(data, place_label, units)
        elif USE_OWM and lat is not None:
            data = fetch_onecall(lat, lon, units=units)
            render_owm(data, place_label, units)
        else:
            if lat is not None:
                data = fetch_wttr_city(f"{lat},{lon}")
                render_wttr(data, place_label, units)
            else:
                data = fetch_wttr_city(city)
                render_wttr(data, place_label, units)
    except requests.HTTPError as e:
        print("Network/API error:", e)
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    main()