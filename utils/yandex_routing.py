import httpx
from config import settings
import hashlib
from loguru import logger
from cachetools import TTLCache
import math
import asyncio

# Кэш на 30 дней (координаты городов не меняются)
route_cache = TTLCache(maxsize=2000, ttl=30*24*3600)

# Семафор: максимум 5 одновременных запросов к Яндекс API
_yandex_semaphore = asyncio.Semaphore(5)

async def geocode(city: str) -> tuple[float, float] | None:
    """Возвращает координаты города через Яндекс Геокодер"""
    cache_key = f"geo_{city.lower()}"
    if cache_key in route_cache:
        return route_cache[cache_key]
    
    async with _yandex_semaphore:
        try:
            url = "https://geocode-maps.yandex.ru/1.x/"
            params = {
                "apikey": settings.YANDEX_API_KEY,
                "geocode": city,
                "format": "json",
                "results": 1
            }
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, params=params, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                
                feature_members = data["response"]["GeoObjectCollection"]["featureMember"]
                if not feature_members:
                    logger.warning(f"City not found: {city}")
                    return None
                
                pos = feature_members[0]["GeoObject"]["Point"]["pos"]
                lon, lat = map(float, pos.split())
                coords = (lat, lon)
                route_cache[cache_key] = coords
                return coords
                
        except Exception as e:
            logger.error(f"Geocode failed for '{city}': {e}")
            return None


def haversine_distance(coord1: tuple, coord2: tuple) -> float:
    """Вычисляет расстояние между точками в км по формуле гаверсинуса"""
    lat1, lon1 = coord1
    lat2, lon2 = coord2
    
    R = 6371
    
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    
    a = (math.sin(dlat/2)**2 + 
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2)
    c = 2 * math.asin(math.sqrt(a))
    
    return R * c


def angle_between_vectors(from1: tuple, to1: tuple, from2: tuple, to2: tuple) -> float:
    """Вычисляет угол между двумя направлениями в градусах"""
    v1_lat = to1[0] - from1[0]
    v1_lon = to1[1] - from1[1]
    
    v2_lat = to2[0] - from2[0]
    v2_lon = to2[1] - from2[1]
    
    len1 = math.sqrt(v1_lat**2 + v1_lon**2)
    len2 = math.sqrt(v2_lat**2 + v2_lon**2)
    
    if len1 == 0 or len2 == 0:
        return 0
    
    dot = v1_lat * v2_lat + v1_lon * v2_lon
    cos_angle = dot / (len1 * len2)
    cos_angle = max(-1, min(1, cos_angle))
    angle = math.degrees(math.acos(cos_angle))
    
    return angle


async def check_intermediate_route(
    route_from: str, 
    route_to: str, 
    trip_from: str, 
    trip_to: str, 
    max_detour_km: int = 80,
    max_angle: int = 110
) -> bool:
    """
    Проверяет, лежит ли маршрут пассажира на пути поездки водителя.
    Учитывает расстояние и угол между направлениями.
    """
    try:
        # Если маршруты совпадают - точно подходит
        if (route_from.lower() == trip_from.lower() and 
            route_to.lower() == trip_to.lower()):
            return True
        
        # Если начало совпадает - проверяем направление и расстояние
        if route_from.lower() == trip_from.lower():
            from_coords = await geocode(route_from)
            to_coords = await geocode(route_to)
            trip_to_coords = await geocode(trip_to)
            
            if all([from_coords, to_coords, trip_to_coords]):
                # Проверяем угол между направлениями
                angle = angle_between_vectors(from_coords, to_coords, from_coords, trip_to_coords)
                
                if angle > max_angle:
                    logger.info(f"Route check: {route_from}→{route_to} on {trip_from}→{trip_to}: "
                               f"angle={angle:.0f}° > {max_angle}° ❌ (opposite directions)")
                    return False
                
                # Проверяем расстояние
                direct_dist = haversine_distance(from_coords, trip_to_coords)
                passenger_dist = haversine_distance(from_coords, to_coords)
                remaining_dist = haversine_distance(to_coords, trip_to_coords)
                
                total_via_passenger = passenger_dist + remaining_dist
                detour = total_via_passenger - direct_dist
                
                logger.info(f"Route check (same start): {route_from}→{route_to} on {trip_from}→{trip_to}: "
                           f"angle={angle:.0f}°, direct={direct_dist:.0f}km, via={total_via_passenger:.0f}km, "
                           f"detour={detour:.0f}km, result={'✅' if detour <= max_detour_km else '❌'}")
                
                return detour <= max_detour_km
        
        # Полная проверка для разных начальных точек
        from_coords = await geocode(route_from)
        to_coords = await geocode(route_to)
        trip_from_coords = await geocode(trip_from)
        trip_to_coords = await geocode(trip_to)

        if not all([from_coords, to_coords, trip_from_coords, trip_to_coords]):
            logger.warning("Could not geocode all cities")
            return False

        # Проверяем угол между направлениями
        angle = angle_between_vectors(trip_from_coords, trip_to_coords, from_coords, to_coords)
        
        if angle > max_angle:
            logger.info(f"Route check: {route_from}→{route_to} on {trip_from}→{trip_to}: "
                       f"angle={angle:.0f}° > {max_angle}° ❌ (different directions)")
            return False

        # Прямой путь водителя
        driver_direct = haversine_distance(trip_from_coords, trip_to_coords)
        
        # Путь через города пассажира
        d1 = haversine_distance(trip_from_coords, from_coords)
        d2 = haversine_distance(from_coords, to_coords)
        d3 = haversine_distance(to_coords, trip_to_coords)
        
        detour_total = d1 + d2 + d3
        detour = detour_total - driver_direct
        
        is_on_route = detour <= max_detour_km
        logger.info(f"Route check: {route_from}→{route_to} on {trip_from}→{trip_to}: "
                   f"angle={angle:.0f}°, driver={driver_direct:.0f}km, via={detour_total:.0f}km, "
                   f"detour={detour:.0f}km, result={'✅' if is_on_route else '❌'}")
        
        return is_on_route
        
    except Exception as e:
        logger.error(f"Routing check failed: {e}")
        return False