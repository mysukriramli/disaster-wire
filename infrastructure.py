"""
Static reference table of critical global infrastructure hubs.
Zero-cost, zero-API dependency.
"""

CRITICAL_INFRASTRUCTURE = [
    # Top Global Container Ports (UN/LOCODE)
    {"name": "Port of Shanghai", "type": "port", "code": "CNSHG", "country": "China", "lat": 31.2304, "lon": 121.4737},
    {"name": "Port of Singapore", "type": "port", "code": "SGSIN", "country": "Singapore", "lat": 1.29027, "lon": 103.851959},
    {"name": "Port of Ningbo-Zhoushan", "type": "port", "code": "CNNGB", "country": "China", "lat": 29.8683, "lon": 121.5440},
    {"name": "Port of Shenzhen", "type": "port", "code": "CNSZX", "country": "China", "lat": 22.5431, "lon": 114.0579},
    {"name": "Port of Busan", "type": "port", "code": "KRPUS", "country": "South Korea", "lat": 35.1796, "lon": 129.0756},
    {"name": "Port of Rotterdam", "type": "port", "code": "NLRTM", "country": "Netherlands", "lat": 51.9244, "lon": 4.4777},
    {"name": "Port of Los Angeles / Long Beach", "type": "port", "code": "USLAX", "country": "USA", "lat": 33.7431, "lon": -118.2673},
    {"name": "Port of Tokyo / Yokohama", "type": "port", "code": "JPTYO", "country": "Japan", "lat": 35.6528, "lon": 139.8394},
    {"name": "Port Klang", "type": "port", "code": "MYPKG", "country": "Malaysia", "lat": 3.0000, "lon": 101.4000},
    {"name": "Port of Antwerp-Bruges", "type": "port", "code": "BEANR", "country": "Belgium", "lat": 51.2194, "lon": 4.4025},

    # Primary Air Freight Hubs (IATA)
    {"name": "Hong Kong International Cargo Hub", "type": "airport", "code": "HKG", "country": "Hong Kong", "lat": 22.3080, "lon": 113.9185},
    {"name": "Memphis International (FedEx SuperHub)", "type": "airport", "code": "MEM", "country": "USA", "lat": 35.0424, "lon": -89.9767},
    {"name": "Shanghai Pudong Cargo Hub", "type": "airport", "code": "PVG", "country": "China", "lat": 31.1443, "lon": 121.8083},
    {"name": "Anchorage Ted Stevens (Trans-Pacific Cargo)", "type": "airport", "code": "ANC", "country": "USA", "lat": 61.1744, "lon": -149.9964},
    {"name": "Incheon International Airport", "type": "airport", "code": "ICN", "country": "South Korea", "lat": 37.4602, "lon": 126.4407},
    {"name": "Louisville Muhammad Ali (UPS Worldport)", "type": "airport", "code": "SDF", "country": "USA", "lat": 38.1741, "lon": -85.7360},
    {"name": "Frankfurt Airport CargoCity", "type": "airport", "code": "FRA", "country": "Germany", "lat": 50.0379, "lon": 8.5622},
    {"name": "Tokyo Narita Cargo Gateway", "type": "airport", "code": "NRT", "country": "Japan", "lat": 35.7647, "lon": 140.3863},

    # Critical Cloud Data Center Hubs
    {"name": "Northern Virginia Data Center Alley (us-east-1)", "type": "datacenter", "code": "US-VA", "country": "USA", "lat": 39.0438, "lon": -77.4874},
    {"name": "Frankfurt Cloud Region (eu-central-1)", "type": "datacenter", "code": "EU-FRA", "country": "Germany", "lat": 50.1109, "lon": 8.6821},
    {"name": "Tokyo Cloud Region (ap-northeast-1)", "type": "datacenter", "code": "AP-TYO", "country": "Japan", "lat": 35.6895, "lon": 139.6917},
    {"name": "Singapore Cloud Region (ap-southeast-1)", "type": "datacenter", "code": "AP-SIN", "country": "Singapore", "lat": 1.3521, "lon": 103.8198},
    {"name": "Dublin Cloud Hub (eu-west-1)", "type": "datacenter", "code": "EU-DUB", "country": "Ireland", "lat": 53.3498, "lon": -6.2603}
]
