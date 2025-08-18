import itertools

from followthemoney import EntityProxy


def get_geopoints(entity: EntityProxy) -> list[dict[str, str]]:
    points = []
    lons = entity.get("longitude", quiet=True)
    lats = entity.get("latitude", quiet=True)
    for lon, lat in itertools.product(lons, lats):
        points.append({"lon": lon, "lat": lat})
    return points
