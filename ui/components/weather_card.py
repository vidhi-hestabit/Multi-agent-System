from __future__ import annotations


def format_weather_card(weather: dict) -> str:
    if not weather:
        return ""

    city        = weather.get("city", "")
    country     = weather.get("country", "")
    temp        = weather.get("temperature", "")
    feels_like  = weather.get("feels_like", "")
    humidity    = weather.get("humidity", "")
    wind        = weather.get("wind_speed", "")
    description = weather.get("description", "").capitalize()
    unit        = weather.get("unit_symbol", "C")
    is_mock     = weather.get("_mock", False)

    location = f"{city}, {country}" if country else city

    mock_banner = ""
    if is_mock:
        mock_banner = (
            '<div class="weather-mock-banner">'
            'Placeholder data &mdash; set OPENWEATHER_API_KEY for live weather'
            '</div>'
        )

    return f"""
<style>
.weather-card {{
  background: linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%);
  border-radius: 14px;
  padding: 20px 22px;
  color: #ffffff;
  font-family: inherit;
}}
.weather-location {{
  font-size: 1.1rem;
  font-weight: 700;
  margin-bottom: 2px;
}}
.weather-description {{
  font-size: 0.85rem;
  opacity: 0.8;
  margin-bottom: 16px;
}}
.weather-temp {{
  font-size: 3rem;
  font-weight: 800;
  line-height: 1;
  margin-bottom: 16px;
}}
.weather-grid {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}}
.weather-stat {{
  background: rgba(255,255,255,0.15);
  border-radius: 8px;
  padding: 8px 12px;
}}
.weather-stat-label {{
  font-size: 0.7rem;
  opacity: 0.7;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}}
.weather-stat-value {{
  font-size: 0.95rem;
  font-weight: 600;
  margin-top: 2px;
}}
.weather-mock-banner {{
  background: rgba(255,255,255,0.2);
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 0.75rem;
  margin-bottom: 12px;
  opacity: 0.9;
}}
</style>
<div class="weather-card">
  {mock_banner}
  <div class="weather-location">{location}</div>
  <div class="weather-description">{description}</div>
  <div class="weather-temp">{temp}&deg;{unit}</div>
  <div class="weather-grid">
    <div class="weather-stat">
      <div class="weather-stat-label">Feels Like</div>
      <div class="weather-stat-value">{feels_like}&deg;{unit}</div>
    </div>
    <div class="weather-stat">
      <div class="weather-stat-label">Humidity</div>
      <div class="weather-stat-value">{humidity}%</div>
    </div>
    <div class="weather-stat">
      <div class="weather-stat-label">Wind Speed</div>
      <div class="weather-stat-value">{wind} m/s</div>
    </div>
  </div>
</div>
"""
