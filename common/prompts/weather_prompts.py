CITY_EXTRACTION_SYSTEM: str = """Extract the city name from the user's message.
Return ONLY the city name, nothing else. No punctuation, no explanation.
If no city is mentioned, return: Delhi
Examples:
  "weather in Mumbai" → Mumbai
  "can you tell the weather of delhi and send via gmail" → Delhi
  "what is the temperature in New York today?" → New York
  "get weather for Tokyo and make a report" → Tokyo
  "weather" → Delhi"""