"""v8.3 (04/11/2026): ✈️ viajes ciudad a ciudad — distancia, horas de viaje estimadas y cambio horario entre dos torneos.

Todo se calcula con una tabla propia de ciudades del circuito (latitud, longitud, huso horario estándar, continente); no se consulta
ninguna web. Las horas de viaje son ESTIMADAS (no sabemos el vuelo real del jugador): vuelo directo a 850 km/h + 0.75 h de maniobras
+ 3 h de traslados y aeropuerto + 2 h de escala si pasa de 4.000 km. El huso es el estándar (sin horario de verano: puede errar 1 h).
Una ciudad que no esté en la tabla NO inventa nada: se devuelve None y el paso del worker la lista como «sin ciudad» para añadirla."""
import math
import re
import unicodedata
from typing import Optional

# bloque: continente → [(nombre, lat, lon, huso)]; los nombres van sin tildes y en minúscula (se aceptan varios alias separados por «/»)
_BLOQUES = {
    "Europa": [
        ("paris", 48.86, 2.35, 1), ("bratislava", 48.15, 17.11, 1), ("metz", 49.12, 6.18, 1), ("lyon", 45.76, 4.84, 1),
        ("montpellier", 43.61, 3.88, 1), ("marseille/marsella", 43.30, 5.37, 1), ("toulouse", 43.60, 1.44, 1), ("bordeaux", 44.84, -0.58, 1),
        ("nantes", 47.22, -1.55, 1), ("rennes", 48.11, -1.68, 1), ("quimper", 47.99, -4.10, 1), ("orleans", 47.90, 1.91, 1),
        ("cherbourg", 49.64, -1.62, 1), ("lille", 50.63, 3.06, 1), ("grenoble", 45.19, 5.72, 1), ("brest", 48.39, -4.49, 1),
        ("strasbourg", 48.57, 7.75, 1), ("mouilleron", 46.67, -1.0, 1), ("saint-tropez", 43.27, 6.64, 1), ("ajaccio", 41.92, 8.74, 1),
        ("florence/firenze", 43.77, 11.26, 1), ("rome/roma", 41.90, 12.50, 1), ("milan/milano", 45.46, 9.19, 1), ("turin/torino", 45.07, 7.69, 1),
        ("bologna", 44.49, 11.34, 1), ("naples/napoli", 40.85, 14.27, 1), ("taranto", 40.47, 17.24, 1), ("rovereto", 45.89, 11.04, 1),
        ("trieste", 45.65, 13.78, 1), ("genoa/genova", 44.41, 8.93, 1), ("cagliari", 39.22, 9.12, 1), ("palermo", 38.12, 13.36, 1),
        ("padova/padua", 45.41, 11.88, 1), ("perugia", 43.11, 12.39, 1), ("bergamo", 45.70, 9.67, 1), ("brescia", 45.54, 10.22, 1),
        ("biella", 45.57, 8.05, 1), ("cordenons", 45.99, 12.69, 1), ("trento", 46.07, 11.12, 1), ("barletta", 41.32, 16.28, 1),
        ("caltanissetta", 37.49, 14.06, 1), ("lecce", 40.35, 18.17, 1), ("sassuolo", 44.54, 10.78, 1), ("bari", 41.12, 16.87, 1),
        ("parma", 44.80, 10.33, 1), ("forli", 44.22, 12.04, 1), ("olbia", 40.92, 9.50, 1), ("san marino", 43.94, 12.45, 1),
        ("todi", 42.78, 12.41, 1), ("verona", 45.44, 10.99, 1), ("vicenza", 45.55, 11.55, 1), ("modena", 44.65, 10.93, 1),
        ("madrid", 40.42, -3.70, 1), ("barcelona", 41.39, 2.17, 1), ("valencia", 39.47, -0.38, 1), ("seville/sevilla", 37.39, -5.98, 1),
        ("marbella", 36.51, -4.89, 1), ("alicante", 38.35, -0.48, 1), ("zaragoza", 41.65, -0.88, 1), ("girona", 41.98, 2.82, 1),
        ("murcia", 37.99, -1.13, 1), ("pozoblanco", 38.38, -4.85, 1), ("santander", 43.46, -3.80, 1), ("tarragona", 41.12, 1.25, 1),
        ("granollers", 41.61, 2.29, 1), ("villena", 38.63, -0.87, 1), ("benicarlo", 40.42, 0.43, 1), ("lleida", 41.62, 0.62, 1),
        ("sabadell", 41.55, 2.11, 1), ("vigo", 42.24, -8.72, 1), ("oviedo", 43.36, -5.85, 1), ("palma/mallorca", 39.57, 2.65, 1),
        ("tenerife", 28.47, -16.25, 0), ("las palmas/gran canaria", 28.12, -15.43, 0), ("malaga", 36.72, -4.42, 1), ("cordoba es", 37.89, -4.78, 1),
        ("lisbon/lisboa", 38.72, -9.14, 0), ("porto", 41.15, -8.61, 0), ("oeiras", 38.69, -9.31, 0), ("braga", 41.55, -8.42, 0),
        ("maia", 41.23, -8.62, 0), ("vilamoura", 37.08, -8.12, 0), ("vale do lobo/faro", 37.02, -7.93, 0),
        ("munich/muenchen", 48.14, 11.58, 1), ("stuttgart", 48.78, 9.18, 1), ("hamburg", 53.55, 9.99, 1), ("berlin", 52.52, 13.40, 1),
        ("cologne/koeln", 50.94, 6.96, 1), ("halle", 51.48, 11.97, 1), ("eckental", 49.55, 11.20, 1), ("ismaning", 48.23, 11.68, 1),
        ("augsburg", 48.37, 10.90, 1), ("mannheim", 49.49, 8.47, 1), ("heilbronn", 49.14, 9.22, 1), ("bad homburg", 50.23, 8.62, 1),
        ("oberstaufen", 47.55, 10.02, 1), ("braunschweig", 52.27, 10.52, 1), ("essen", 51.46, 7.01, 1), ("karlsruhe", 49.01, 8.40, 1),
        ("leipzig", 51.34, 12.37, 1), ("hamburgo", 53.55, 9.99, 1), ("ludwigshafen", 49.48, 8.44, 1), ("bonn", 50.74, 7.10, 1),
        ("vienna/wien", 48.21, 16.37, 1), ("kitzbuhel", 47.45, 12.39, 1), ("salzburg", 47.81, 13.04, 1), ("innsbruck", 47.26, 11.39, 1),
        ("graz", 47.07, 15.44, 1), ("poertschach/portschach", 46.62, 14.15, 1), ("tulln", 48.33, 16.06, 1),
        ("basel", 47.56, 7.59, 1), ("geneva/geneve", 46.20, 6.14, 1), ("zurich", 47.38, 8.54, 1), ("gstaad", 46.47, 7.29, 1),
        ("lugano", 46.00, 8.95, 1), ("bern", 46.95, 7.45, 1), ("biel/bienne", 47.14, 7.25, 1), ("lausanne", 46.52, 6.63, 1),
        ("rotterdam", 51.92, 4.48, 1), ("amsterdam", 52.37, 4.90, 1), ("s-hertogenbosch/den bosch", 51.69, 5.30, 1), ("antwerp/amberes", 51.22, 4.40, 1),
        ("brussels/bruselas", 50.85, 4.35, 1), ("liege", 50.63, 5.57, 1), ("eindhoven", 51.44, 5.48, 1), ("luxembourg", 49.61, 6.13, 1),
        ("london/londres", 51.51, -0.13, 0), ("eastbourne", 50.77, 0.28, 0), ("birmingham", 52.49, -1.89, 0), ("nottingham", 52.95, -1.15, 0),
        ("manchester", 53.48, -2.24, 0), ("glasgow", 55.86, -4.25, 0), ("edinburgh", 55.95, -3.19, 0), ("dublin", 53.35, -6.26, 0),
        ("ilkley", 53.93, -1.82, 0), ("cardiff", 51.48, -3.18, 0), ("loughborough", 52.77, -1.20, 0), ("shrewsbury", 52.71, -2.75, 0),
        ("stockholm", 59.33, 18.07, 1), ("bastad", 56.43, 12.85, 1), ("copenhagen/kobenhavn", 55.68, 12.57, 1), ("helsinki", 60.17, 24.94, 2),
        ("oslo", 59.91, 10.75, 1), ("gothenburg/goteborg", 57.71, 11.97, 1),
        ("warsaw/varsovia", 52.23, 21.01, 1), ("bucharest/bucarest", 44.43, 26.10, 2), ("cluj", 46.77, 23.59, 2), ("sibiu", 45.80, 24.15, 2),
        ("brasov", 45.65, 25.61, 2), ("budapest", 47.50, 19.04, 1), ("prague/praha", 50.08, 14.44, 1), ("prostejov", 49.47, 17.11, 1),
        ("ostrava", 49.82, 18.26, 1), ("plzen", 49.75, 13.38, 1), ("zagreb", 45.81, 15.98, 1), ("umag", 45.43, 13.52, 1),
        ("split", 43.51, 16.44, 1), ("zadar", 44.12, 15.23, 1), ("belgrade/belgrado", 44.79, 20.45, 1), ("novi sad", 45.27, 19.83, 1),
        ("sofia", 42.70, 23.32, 2), ("plovdiv", 42.14, 24.75, 2), ("athens/atenas", 37.98, 23.73, 2), ("heraklion/iraklion", 35.34, 25.14, 2),
        ("thessaloniki/salonica", 40.64, 22.94, 2), ("istanbul", 41.01, 28.98, 3), ("antalya", 36.90, 30.71, 3), ("ankara", 39.93, 32.86, 3),
        ("izmir", 38.42, 27.14, 3), ("kyiv/kiev", 50.45, 30.52, 2), ("chisinau", 47.01, 28.86, 2), ("tbilisi", 41.72, 44.79, 4),
        ("yerevan", 40.18, 44.51, 4), ("baku", 40.41, 49.87, 4), ("tallinn", 59.44, 24.75, 2), ("riga", 56.95, 24.11, 2),
        ("vilnius", 54.69, 25.28, 2), ("ljubljana", 46.06, 14.51, 1), ("maribor", 46.55, 15.65, 1), ("portoroz", 45.51, 13.59, 1),
        ("banja luka", 44.77, 17.19, 1), ("sarajevo", 43.86, 18.41, 1), ("skopje", 41.99, 21.43, 1), ("tirana", 41.33, 19.82, 1),
        ("podgorica", 42.44, 19.26, 1), ("limassol", 34.68, 33.04, 2), ("nicosia", 35.19, 33.38, 2), ("minsk", 53.90, 27.57, 3),
        ("moscow/moscu", 55.76, 37.62, 3), ("saint petersburg/san petersburgo", 59.93, 30.34, 3), ("kazan", 55.79, 49.12, 3), ("sochi", 43.60, 39.73, 3),
    ],
    "Medio Oriente y África": [
        ("tel aviv", 32.09, 34.78, 2), ("ramat hasharon", 32.15, 34.84, 2), ("dubai", 25.20, 55.27, 4), ("doha", 25.29, 51.53, 3),
        ("abu dhabi", 24.45, 54.38, 4), ("riyadh/riad", 24.71, 46.68, 3), ("jeddah/yeda", 21.54, 39.17, 3), ("cairo/el cairo", 30.04, 31.24, 2),
        ("sharm el sheikh", 27.91, 34.33, 2), ("tunis/tunez", 36.81, 10.18, 1), ("monastir", 35.78, 10.83, 1), ("hammamet", 36.40, 10.62, 1),
        ("casablanca", 33.57, -7.59, 1), ("rabat", 34.02, -6.84, 1), ("marrakech", 31.63, -8.01, 1), ("agadir", 30.43, -9.60, 1),
        ("nairobi", -1.29, 36.82, 3), ("kigali", -1.95, 30.06, 2), ("lagos", 6.52, 3.38, 1), ("johannesburg", -26.20, 28.05, 2),
        ("pretoria", -25.75, 28.19, 2), ("cape town/ciudad del cabo", -33.92, 18.42, 2), ("harare", -17.83, 31.05, 2), ("kampala", 0.35, 32.58, 3),
        ("amman", 31.95, 35.93, 3), ("muscat/mascate", 23.59, 58.41, 4),
    ],
    "América del Norte y Central": [
        ("new york/nueva york/flushing", 40.71, -74.01, -5), ("indian wells", 33.72, -116.34, -8), ("miami", 25.76, -80.19, -5),
        ("washington", 38.91, -77.04, -5), ("cincinnati", 39.10, -84.51, -5), ("toronto", 43.65, -79.38, -5), ("montreal", 45.50, -73.57, -5),
        ("quebec", 46.81, -71.21, -5), ("vancouver", 49.28, -123.12, -8), ("houston", 29.76, -95.37, -6), ("dallas", 32.78, -96.80, -6),
        ("fort worth", 32.76, -97.33, -6), ("austin", 30.27, -97.74, -6), ("charlottesville", 38.03, -78.48, -5),
        ("winston-salem/winston salem", 36.10, -80.24, -5), ("atlanta", 33.75, -84.39, -5), ("newport", 41.49, -71.31, -5),
        ("los angeles", 34.05, -118.24, -8), ("san diego", 32.72, -117.16, -8), ("san francisco", 37.77, -122.42, -8), ("chicago", 41.88, -87.63, -6),
        ("orlando", 28.54, -81.38, -5), ("tallahassee", 30.44, -84.28, -5), ("knoxville", 35.96, -83.92, -5), ("champaign", 40.12, -88.24, -6),
        ("san antonio", 29.42, -98.49, -6), ("las vegas", 36.17, -115.14, -8), ("phoenix", 33.45, -112.07, -7), ("denver", 39.74, -104.99, -7),
        ("columbus", 39.96, -83.00, -5), ("tulsa", 36.15, -95.99, -6), ("norman", 35.22, -97.44, -6), ("lexington", 38.04, -84.50, -5),
        ("los cabos/cabo san lucas", 22.89, -109.91, -7), ("acapulco", 16.85, -99.82, -6), ("mexico city/ciudad de mexico", 19.43, -99.13, -6),
        ("guadalajara", 20.67, -103.35, -6), ("monterrey", 25.69, -100.32, -6), ("merida", 20.97, -89.62, -6), ("cancun", 21.16, -86.85, -5),
        ("leon", 21.12, -101.68, -6), ("tampico", 22.23, -97.86, -6), ("san luis potosi", 22.16, -100.98, -6), ("morelia", 19.71, -101.19, -6),
        ("puebla", 19.04, -98.21, -6), ("queretaro", 20.59, -100.39, -6), ("santo domingo", 18.49, -69.93, -4), ("san jose cr", 9.93, -84.08, -6),
        ("panama", 8.98, -79.52, -5), ("guatemala", 14.63, -90.51, -6), ("san salvador", 13.69, -89.19, -6), ("tegucigalpa", 14.07, -87.19, -6),
        ("kingston", 18.00, -76.79, -5), ("port of spain", 10.66, -61.51, -4), ("san juan pr", 18.47, -66.11, -4), ("havana/la habana", 23.11, -82.37, -5),
    ],
    "América del Sur": [
        ("bogota", 4.71, -74.07, -5), ("cali", 3.45, -76.53, -5), ("medellin", 6.24, -75.57, -5), ("barranquilla", 10.96, -74.78, -5),
        ("cartagena", 10.39, -75.51, -5), ("bucaramanga", 7.12, -73.12, -5), ("pereira", 4.81, -75.69, -5), ("manizales", 5.07, -75.52, -5),
        ("quito", -0.18, -78.47, -5), ("guayaquil", -2.17, -79.92, -5), ("cuenca", -2.90, -79.00, -5), ("lima", -12.05, -77.04, -5),
        ("cusco/cuzco", -13.52, -71.97, -5), ("santiago", -33.45, -70.67, -4), ("vina del mar", -33.02, -71.55, -4), ("concepcion cl", -36.83, -73.05, -4),
        ("buenos aires", -34.60, -58.38, -3), ("cordoba ar", -31.42, -64.18, -3), ("villa maria", -32.41, -63.24, -3), ("santa fe", -31.63, -60.70, -3),
        ("tigre", -34.43, -58.58, -3), ("mar del plata", -38.00, -57.56, -3), ("rosario", -32.95, -60.64, -3), ("mendoza", -32.89, -68.84, -3),
        ("tucuman", -26.81, -65.22, -3), ("salta", -24.79, -65.41, -3), ("corrientes", -27.47, -58.83, -3), ("san juan ar", -31.54, -68.54, -3),
        ("montevideo", -34.90, -56.16, -3), ("punta del este", -34.96, -54.95, -3), ("asuncion", -25.26, -57.58, -3), ("la paz", -16.50, -68.15, -4),
        ("cochabamba", -17.39, -66.16, -4), ("santa cruz", -17.78, -63.18, -4), ("sao paulo", -23.55, -46.63, -3), ("rio de janeiro/rio", -22.91, -43.17, -3),
        ("costa do sauipe/sauipe", -12.45, -37.97, -3), ("curitiba", -25.43, -49.27, -3), ("florianopolis", -27.60, -48.55, -3),
        ("campinas", -22.91, -47.06, -3), ("brasilia", -15.79, -47.88, -3), ("porto alegre", -30.03, -51.23, -3), ("belo horizonte", -19.92, -43.94, -3),
        ("salvador", -12.97, -38.50, -3), ("recife", -8.05, -34.88, -3), ("fortaleza", -3.73, -38.52, -3), ("ribeirao preto", -21.18, -47.81, -3),
        ("caracas", 10.48, -66.90, -4),
    ],
    "Asia": [
        ("tokyo", 35.68, 139.69, 9), ("osaka", 34.69, 135.50, 9), ("shanghai", 31.23, 121.47, 8), ("beijing/pekin", 39.90, 116.41, 8),
        ("chengdu", 30.57, 104.07, 8), ("shenzhen", 22.54, 114.06, 8), ("guangzhou/canton", 23.13, 113.26, 8), ("zhuhai", 22.27, 113.58, 8),
        ("hong kong", 22.32, 114.17, 8), ("wuhan", 30.59, 114.31, 8), ("nanchang", 28.68, 115.86, 8), ("maanshan", 31.69, 118.51, 8),
        ("anning", 24.92, 102.48, 8), ("kunming", 25.04, 102.72, 8), ("taipei", 25.03, 121.57, 8), ("taoyuan", 24.99, 121.30, 8),
        ("seoul/seul", 37.57, 126.98, 9), ("incheon", 37.46, 126.71, 9), ("gimcheon", 36.12, 128.11, 9), ("bangkok", 13.76, 100.50, 7),
        ("nonthaburi", 13.86, 100.52, 7), ("hua hin", 12.57, 99.96, 7), ("kuala lumpur", 3.14, 101.69, 8), ("singapore/singapur", 1.35, 103.82, 8),
        ("jakarta", -6.21, 106.85, 7), ("manila", 14.60, 120.98, 8), ("hanoi", 21.03, 105.85, 7), ("ho chi minh", 10.82, 106.63, 7),
        ("mumbai", 19.08, 72.88, 5.5), ("pune", 18.52, 73.86, 5.5), ("new delhi/delhi", 28.61, 77.21, 5.5), ("bengaluru/bangalore", 12.97, 77.59, 5.5),
        ("chennai", 13.08, 80.27, 5.5), ("hyderabad", 17.39, 78.49, 5.5), ("kolkata", 22.57, 88.36, 5.5), ("colombo", 6.93, 79.86, 5.5),
        ("almaty", 43.24, 76.89, 5), ("astana", 51.17, 71.43, 5), ("tashkent", 41.30, 69.24, 5), ("islamabad", 33.68, 73.05, 5),
        ("nonthaburi th", 13.86, 100.52, 7), ("kobe", 34.69, 135.20, 9), ("yokohama", 35.44, 139.64, 9), ("nagoya", 35.18, 136.91, 9),
    ],
    "Oceanía": [
        ("melbourne", -37.81, 144.96, 10), ("sydney", -33.87, 151.21, 10), ("brisbane", -27.47, 153.03, 10), ("perth", -31.95, 115.86, 8),
        ("adelaide", -34.93, 138.60, 9.5), ("canberra", -35.28, 149.13, 10), ("auckland", -36.85, 174.76, 12), ("wellington", -41.29, 174.78, 12),
        ("hobart", -42.88, 147.33, 10), ("launceston", -41.44, 147.14, 10), ("traralgon", -38.20, 146.54, 10), ("playford", -34.72, 138.67, 9.5),
        ("gold coast", -28.02, 153.40, 10), ("bendigo", -36.76, 144.28, 10), ("ballarat", -37.56, 143.85, 10), ("happy valley", -35.08, 138.55, 9.5),
    ],
}

# palabras que NO son la ciudad en el nombre de un torneo
_RUIDO = re.compile(
    r"\b(atp|wta|itf|utr|pro|tour|challenger|men|women|mens|womens|open|grand|prix|masters|cup|copa|trophy|championships?|classic|international|"
    r"series|125k?|250|500|1000|w\d{1,3}|m\d{1,3}|j\d{1,3}|r\d{1,3}|q\d|qf|sf|f|final|round|ronda|singles|doubles|dobles|and|de|del|la|el|the|of|"
    r"indoors?|outdoors?|clay|hard|grass|carpet|tennis|tenis|challenge|qualifying|qualification)\b")


def _n(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9' -]+", " ", s)).strip()


def _indice() -> dict:
    idx = {}
    for cont, filas in _BLOQUES.items():
        for nombres, lat, lon, tz in filas:
            for alias in nombres.split("/"):
                idx.setdefault(_n(alias), {"nombre": _n(nombres.split("/")[0]).title(), "lat": lat, "lon": lon, "tz": tz, "continente": cont})
    return idx


CIUDADES = _indice()
_ORDEN = sorted(CIUDADES, key=len, reverse=True)           # el nombre más largo primero («san juan» antes que «san»)


def ciudad_de(torneo: Optional[str]) -> Optional[dict]:
    """Ciudad del torneo a partir de su nombre («ATP Challenger Villa Maria - R1» → Villa María). None si no se reconoce."""
    t = _n(torneo)
    if not t:
        return None
    t = " " + _RUIDO.sub(" ", t) + " "
    t = re.sub(r"\s+", " ", t)
    for nombre in _ORDEN:
        if f" {nombre} " in t:
            return CIUDADES[nombre]
    return None


def km(a: dict, b: dict) -> float:
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dl, dp = math.radians(b["lon"] - a["lon"]), p2 - p1
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def horas_viaje(distancia_km: float) -> float:
    """Estimación puerta a puerta (ver el encabezado). 0 si es la misma ciudad."""
    if distancia_km < 30:
        return 0.0
    h = distancia_km / 850.0 + 0.75 + 3.0
    if distancia_km > 4000:
        h += 2.0
    return round(h, 1)


def entre(a: dict, b: dict) -> dict:
    d = km(a, b)
    return {"km": int(round(d, -1)), "horas": horas_viaje(d), "huso": round(b["tz"] - a["tz"], 1),
            "continente_cambia": a["continente"] != b["continente"]}
