#!/usr/bin/env python3
"""
weather_cli_rich.py — Terminal UI using rich: colorful table + hourly sparkline

Usage:
  python weather_cli_rich.py [City]
Deps:
  pip install requests rich
"""

import sys, os, json, time
from datetime import datetime, timezone
try:
    import requests
except ImportError:
    print("Install requests: pip install requests")
    raise SystemExit(1)

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.align import Align
    from rich.text import Text
except ImportError:
    print("Install rich: pip install rich")
    raise SystemExit(1)

# ---------- CONFIG ----------
import os
OPENWEATHER_KEY = os.environ.get("OPENWEATHER_KEY", "").strip()
USE_OWM = bool(OPENWEATHER_KEY)
CFG_PATH = os.path.expanduser("~/.weather_cfg.json")
DEFAULT_CITY = "London"

console = Console()

# ---------- helpers ----------
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

def cap(s): return s.capitalize() if isinstance(s, str) else s
def human_time(ts, tz_offset=0):
    return datetime.fromtimestamp((ts or int(time.time())) + (tz_offset or 0), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")

# sparkline with unicode blocks (same idea)
SPARK = "▁▂▃▄▅▆▇█"
def sparkline(values, width=30):
    if not values: return ""
    if len(values) > width:
        step = len(values)/width
        vals = [values[int(i*step)] for i in range(width)]
    else:
        vals = values + [values[-1]]*(width-len(values))
    lo = min(vals); hi = max(vals)
    if hi==lo: return "".join(SPARK[0] for _ in vals)
    out = "".join(SPARK[int((v-lo)/(hi-lo)*(len(SPARK)-1))] for v in vals)
    return out

# fetchers
def geocode_owm(city):
    url = f"https://api.openweathermap.org/geo/1.0/direct?q={requests.utils.requote_uri(city)}&limit=1&appid={OPENWEATHER_KEY}"
    r = requests.get(url, timeout=8)
    r.raise_for_status()
    j = r.json()
    if not j:
        raise ValueError("City not found")
    it = j[0]
    return it["lat"], it["lon"], it.get("name", city), it.get("country", "")

# ---------- OWM fetchers (try One Call, fallback to weather+forecast) ----------
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
            return fetch_weather_and_forecast(lat, lon, units)
    except requests.RequestException:
        return fetch_weather_and_forecast(lat, lon, units)

def fetch_weather_and_forecast(lat, lon, units="metric"):
    """
    Use /weather (current) and /forecast (3-hourly) to build a OneCall-like payload.
    """
    # current
    cur_url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&units={units}&appid={OPENWEATHER_KEY}"
    fr_url  = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&units={units}&appid={OPENWEATHER_KEY}"
    rcur = requests.get(cur_url, timeout=8); rcur.raise_for_status(); cur = rcur.json()
    rfr  = requests.get(fr_url, timeout=10);  rfr.raise_for_status(); fr = rfr.json()

    # build hourly: take up to next 24 3-hour entries and repeat to approximate hourly resolution
    fr_list = fr.get("list", [])  # 3-hour steps
    hourly = []
    for item in fr_list:
        hourly.append({
            "dt": item.get("dt"),
            "temp": item.get("main", {}).get("temp"),
            "weather": item.get("weather", [])
        })
        if len(hourly) >= 24:
            break
    if hourly and len(hourly) < 24:
        last = hourly[-1]
        while len(hourly) < 24:
            hourly.append(last)

    # build daily: aggregate by calendar day (min/max + representative weather)
    from datetime import datetime as _dt, timezone as _tz
    daily_map = {}
    for item in fr_list:
        dt = item.get("dt")
        # convert to timezone-aware UTC date
        day = _dt.fromtimestamp(dt, tz=_tz.utc).date()
        t = item.get("main", {})
        w = item.get("weather", [{}])[0]
        entry = daily_map.setdefault(day, {"temps": [], "weathers": [], "dts": []})
        entry["temps"].append((t.get("temp_min"), t.get("temp_max")))
        entry["weathers"].append(w)
        entry["dts"].append(dt)

    daily = []
    for day in sorted(daily_map.keys()):
        group = daily_map[day]
        mins = [a for a,b in group["temps"] if a is not None]
        maxs = [b for a,b in group["temps"] if b is not None]
        tmin = min(mins) if mins else None
        tmax = max(maxs) if maxs else None
        mid_idx = len(group["weathers"]) // 2
        w = group["weathers"][mid_idx] if group["weathers"] else {}
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
            "temp": cur.get("main", {}).get("temp"),
            "feels_like": cur.get("main", {}).get("feels_like"),
            "humidity": cur.get("main", {}).get("humidity"),
            "wind_speed": cur.get("wind", {}).get("speed"),
            "weather": cur.get("weather", [])
        },
        "hourly": hourly,
        "daily": daily,
        "timezone_offset": 0
    }
    return owm_like

def fetch_wttr_city(city):
    r = requests.get(f"https://wttr.in/{requests.utils.requote_uri(city)}?format=j1", timeout=10)
    r.raise_for_status()
    return r.json()

# ---------- render ----------
ICON = {"Thunderstorm":"⛈️","Drizzle":"🌦️","Rain":"🌧️","Snow":"❄️","Clear":"☀️","Clouds":"☁️","Mist":"🌫️","Haze":"🌫️"}

def render_rich_owm(data, place_label, units):
    cur = data.get("current",{}); daily = data.get("daily",[]); hourly=data.get("hourly",[])
    tz_offset = data.get("timezone_offset",0)
    unit_sym = "°C" if units=="metric" else "°F"
    w = cur.get("weather",[{}])[0]; desc = w.get("description",""); main=w.get("main","")
    icon = ICON.get(main,"")
    temps24 = [h.get("temp") for h in hourly[:24] if h.get("temp") is not None]

    head = Text(f"{place_label}  ", style="bold cyan") + Text(f"{human_time(cur.get('dt',int(time.time())),tz_offset)}", style="dim")
    console.print(Panel(head, style="white on #071725"))

    left = Table(show_header=False, box=None)
    left.add_row("Condition", f"{icon} {cap(desc)}")
    left.add_row("Temp", f"{round(cur.get('temp',0))}{unit_sym} (feels {round(cur.get('feels_like',0))}{unit_sym})")
    left.add_row("Humidity", f"{cur.get('humidity','—')}%")
    left.add_row("Wind", f"{round(cur.get('wind_speed',0))} {'m/s' if units=='metric' else 'mph'}")

    if temps24:
        spark = sparkline(temps24, width=36)
        left.add_row("Next 24h", spark + f"  min {round(min(temps24))}{unit_sym} max {round(max(temps24))}{unit_sym}")
    else:
        left.add_row("Next 24h", "—")

    right = Table(show_header=False, box=None)
    right.add_row("3-day forecast", "")
    for i in range(1,4):
        if i>=len(daily): break
        d = daily[i]
        ddate = datetime.fromtimestamp(d["dt"] + (tz_offset or 0), tz=timezone.utc).strftime("%a %d %b")
        desc = d.get("weather",[{}])[0].get("description","")
        tmax = round(d.get("temp",{}).get("max",0)) if d.get("temp",{}).get("max") is not None else 0
        tmin = round(d.get("temp",{}).get("min",0)) if d.get("temp",{}).get("min") is not None else 0
        right.add_row(f"[bold]{ddate}[/bold]", f"{cap(desc):18} {tmax}{unit_sym}/{tmin}{unit_sym}")

    grid = Table.grid(expand=True)
    grid.add_column(ratio=2); grid.add_column(ratio=3)
    grid.add_row(left, right)
    console.print(grid)

def render_rich_wttr(data, place_label, units):
    cur = data.get("current_condition",[{}])[0]; days = data.get("weather",[])
    unit_sym = "°C" if units=="metric" else "°F"
    temp = cur.get("temp_C") if units=="metric" else cur.get("temp_F")
    feels = cur.get("FeelsLikeC") if units=="metric" else cur.get("FeelsLikeF")
    head = Text(f"{place_label}  ", style="bold green") + Text(datetime.now().strftime("%Y-%m-%d %H:%M"), style="dim")
    console.print(Panel(head))
    t = Table(box=None)
    t.add_row("Condition", cap((cur.get("weatherDesc") or [{}])[0].get("value","")))
    t.add_row("Temp", f"{temp}{unit_sym} (feels {feels}{unit_sym})")
    t.add_row("Humidity", f"{cur.get('humidity','—')}%")
    console.print(t)
    f = Table(title="3-day forecast")
    f.add_column("Day"); f.add_column("High/Low")
    for d in days[1:4]:
        dt = datetime.strptime(d["date"], "%Y-%m-%d").strftime("%a %d %b")
        tmax = d.get("maxtempC") if units=="metric" else d.get("maxtempF")
        tmin = d.get("mintempC") if units=="metric" else d.get("mintempF")
        f.add_row(dt, f"{tmax}{unit_sym}/{tmin}{unit_sym}")
    console.print(f)

# ---------- main ----------
def main():
    cfg = load_cfg(); units = cfg.get("units","metric"); last_city = cfg.get("last_city", DEFAULT_CITY)
    args = sys.argv[1:]
    lat=lon=None; city=None
    if args:
        city = " ".join(args); place_label = city; last_city = city
    else:
        city = last_city; place_label = city

    console.print("\n[u] toggle units   [Enter] continue   [q] quit", style="dim")
    c = input("Choice: ").strip().lower()
    if c == "u":
        units = "imperial" if units=="metric" else "metric"
        console.print(f"Units now: {'°F' if units=='imperial' else '°C'}")

    cfg["units"]=units; cfg["last_city"]=last_city; save_cfg(cfg)

    try:
        if USE_OWM and city:
            lat, lon, name, country = geocode_owm(city)
            place_label = f"{name}, {country}" if country else name
            data = fetch_onecall(lat, lon, units=units)
            render_rich_owm(data, place_label, units)
        else:
            data = fetch_wttr_city(city)
            render_rich_wttr(data, place_label, units)
    except requests.HTTPError as e:
        console.print("Network/API error: " + str(e), style="red")
    except Exception as e:
        console.print("Error: " + str(e), style="red")

if __name__ == "__main__":
    main()