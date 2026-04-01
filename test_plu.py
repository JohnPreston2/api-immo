import requests

for ville, lat, lon in [('Lyon', 45.75, 4.85), ('Marseille', 43.30, 5.37)]:
    params = {
        'SERVICE': 'WFS', 'VERSION': '2.0.0', 'REQUEST': 'GetFeature',
        'TYPENAMES': 'gpu:zone_urba', 'OUTPUTFORMAT': 'application/json',
        'SRSNAME': 'EPSG:4326',
        'BBOX': f'{lon-0.04},{lat-0.04},{lon+0.04},{lat+0.04},EPSG:4326',
        'COUNT': 5,
    }
    r = requests.get('https://data.geopf.fr/wfs/geoserver/ows', params=params, timeout=30)
    feats = r.json().get('features', [])
    print(ville, len(feats), 'features')
    if feats:
        p = feats[0].get('properties', {})
        print('  partition:', p.get('partition'))
        print('  typezone:', p.get('typezone'))
        print('  libelong:', str(p.get('libelong', ''))[:50])
