"""Versioned fictional stories; keys never depend on database or tracking IDs."""

VERSION = "motionmate-logistics-test-dataset-v2"

CLIENTS = (
    ("coral-books", "Avery", "Morgan", "Coral Bay Books"),
    ("harbor-cafe", "Jordan", "Ellis", "Harbor Cafe"),
    ("island-supplies", "Casey", "Bennett", "Island Supplies"),
    ("roseau-market", "Riley", "Foster", "Roseau Market"),
    ("sunrise-house", "Morgan", "Reed", "Sunrise Guest House"),
    ("blue-design", "Taylor", "Hayes", "Blue Horizon Design"),
    ("seabreeze-shop", "Robin", "Campbell", "Seabreeze Shop"),
    ("palm-textiles", "Drew", "Parker", "Palm Textiles"),
    ("lagoon-ceramics", "Jamie", "Brooks", "Lagoon Ceramics"),
    ("cargo-print", "Alex", "Rivera", "Cargo Print Studio"),
    ("dominica-school", "Quinn", "James", "Dominica School Supplies"),
    ("island-repairs", "Skyler", "Lewis", "Island Repair Supplies"),
)

# key, source, destination, preferred mode, target shipment state, parcel count,
# bill-to client index. AIR falls back to SEA only when AIR is not configured.
SHIPMENTS = (
    ("miami-sea-delivered", "MIA-HUB", "SXM-PORT", "SEA", "COMPLETED", 4, 0),
    ("miami-sea-moving", "MIA-HUB", "SXM-PORT", "SEA", "IN_TRANSIT", 4, 1),
    ("port-warehouse-handoff", "SXM-PORT", "SXM-DC", "ROAD", "COMPLETED", 4, 2),
    ("dominica-sea-arrival", "SXM-PORT", "DM-HUB", "SEA", "ARRIVED", 4, 3),
    ("local-sxm-ready", "SXM-DC", "SXM-DC", "ROAD", "READY", 4, 4),
    ("miami-air-booking", "MIA-HUB", "SXM-PORT", "AIR", "DRAFT", 4, 5),
    ("dominica-sea-ready", "SXM-PORT", "DM-HUB", "SEA", "READY", 4, 6),
    ("miami-cancelled-booking", "MIA-HUB", "SXM-PORT", "SEA", "CANCELLED", 4, 7),
    ("sxm-road-moving", "SXM-PORT", "SXM-DC", "ROAD", "IN_TRANSIT", 2, 8),
    ("miami-air-arrival", "MIA-HUB", "SXM-PORT", "AIR", "ARRIVED", 2, 9),
)

MULTILEG = (
    ("miami-sxm-dominica-school", "DELIVERED"),
    ("miami-sxm-dominica-repairs", "READY"),
)
CANCELLATIONS = ("cancelled-before-intake", "cancelled-local-booking")
SITE_WORKERS = {
    "MIA-HUB": "miami",
    "SXM-PORT": "sxm-port",
    "SXM-DC": "sxm-warehouse",
    "DM-HUB": "dominica",
}
CONTENTS = (
    ("Books and stationery", "490199"),
    ("Reusable cafe containers", "392410"),
    ("Cotton clothing and shop supplies", "610910"),
    ("Ceramic tableware", "691200"),
    ("Printed display materials", "491110"),
    ("Repair supplies and hand tools", "820559"),
)
EXPECTED_COUNTS = {
    "clients": 12,
    "parcels": 40,
    "shipments": 10,
    "parcel_events": 179,
    "invoices": 12,
    "invoice_lines": 24,
    "logistics_charges": 24,
    "activity_logs": 12,
    "handling_sites": 2,
}
