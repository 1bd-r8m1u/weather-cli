# Weather CLI 🌦️

A colorful terminal weather dashboard written in Python.  
Uses [OpenWeatherMap](https://openweathermap.org/) (One Call / fallback) and [wttr.in](https://wttr.in/).

## Running without an API key (default)

If `OPENWEATHER_KEY` is **not** set in your environment the scripts will use `wttr.in` (no signup needed).

To run without a key:
```bash
unset OPENWEATHER_KEY
python weather_cli_rich.py London
python weather_cli_spark.py London

## Features
- Current conditions, 3-day forecast
- Sparkline of next 24h temps
- Toggle between °C / °F
- Rich formatting

### Included scripts

- `weather_cli_rich.py` — colorful TUI using `rich` (requires `requests`, `rich`).
- `weather_cli_spark.py` — lightweight CLI with ASCII hourly sparkline (requires `requests`).

Run:
```bash
python weather_cli_rich.py [City]
python weather_cli_spark.py [City]

## Install
```bash
pip install requests rich
