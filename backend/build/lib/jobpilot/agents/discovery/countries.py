_NAMES = {
    "germany": "DE", "deutschland": "DE", "de": "DE",
    "austria": "AT", "österreich": "AT", "osterreich": "AT", "at": "AT",
    "switzerland": "CH", "schweiz": "CH", "ch": "CH",
    "netherlands": "NL", "the netherlands": "NL", "niederlande": "NL", "nl": "NL",
    "belgium": "BE", "belgien": "BE", "be": "BE",
    "france": "FR", "frankreich": "FR", "fr": "FR",
    "spain": "ES", "spanien": "ES", "es": "ES",
    "portugal": "PT", "pt": "PT",
    "italy": "IT", "italien": "IT", "it": "IT",
    "poland": "PL", "polen": "PL", "pl": "PL",
    "czechia": "CZ", "czech republic": "CZ", "tschechien": "CZ", "cz": "CZ",
    "denmark": "DK", "dänemark": "DK", "dk": "DK",
    "sweden": "SE", "schweden": "SE", "se": "SE",
    "norway": "NO", "norwegen": "NO", "no": "NO",
    "finland": "FI", "finnland": "FI", "fi": "FI",
    "ireland": "IE", "irland": "IE", "ie": "IE",
    "luxembourg": "LU", "luxemburg": "LU", "lu": "LU",
    "united kingdom": "GB", "uk": "GB", "england": "GB", "gb": "GB",
    "romania": "RO", "ro": "RO", "hungary": "HU", "hu": "HU", "estonia": "EE", "ee": "EE",
    "united states": "US", "usa": "US", "us": "US", "india": "IN", "in": "IN",
}
# Major cities that often appear without a country.
_CITIES = {
    "berlin": "DE", "munich": "DE", "münchen": "DE", "hamburg": "DE", "cologne": "DE", "köln": "DE",
    "frankfurt": "DE", "stuttgart": "DE", "dresden": "DE", "leipzig": "DE", "chemnitz": "DE",
    "düsseldorf": "DE", "nuremberg": "DE", "nürnberg": "DE", "hanover": "DE", "hannover": "DE",
    "karlsruhe": "DE", "ingolstadt": "DE", "wolfsburg": "DE", "vienna": "AT", "wien": "AT",
    "zurich": "CH", "zürich": "CH", "amsterdam": "NL", "eindhoven": "NL", "prague": "CZ", "praha": "CZ",
    "warsaw": "PL", "krakow": "PL", "kraków": "PL", "paris": "FR", "madrid": "ES", "barcelona": "ES",
    "lisbon": "PT", "dublin": "IE", "copenhagen": "DK", "stockholm": "SE", "helsinki": "FI",
    "london": "GB", "brussels": "BE", "milan": "IT",
}


def country_code(text: str | None) -> str | None:
    if not text:
        return None
    t = text.strip().lower()
    t = t.replace("(hybrid)", "").replace("(remote)", "").strip()
    return _NAMES.get(t) or _CITIES.get(t)


def is_country_name(text: str | None) -> bool:
    return bool(text) and text.strip().lower().replace("(hybrid)", "").replace("(remote)", "").strip() in _NAMES
