"""Value pools for synthetic identifiers. Everything here is made up or generic."""

FEMALE_FIRST = [
    "Maria", "Linda", "Susan", "Karen", "Patricia", "Jennifer", "Angela", "Priya",
    "Mei", "Fatima", "Olivia", "Hannah", "Grace", "Denise", "Rosa", "Tamara",
    "Ingrid", "Yuki", "Amara", "Beatriz", "Colleen", "Dolores", "Eleanor",
    "Frances", "Gloria", "Harriet", "Imani", "Joanne", "Kimberly", "Lorraine",
]
MALE_FIRST = [
    "James", "Robert", "Michael", "David", "William", "Carlos", "Anil", "Wei",
    "Omar", "Ethan", "Marcus", "Thomas", "Raymond", "Walter", "Dennis", "Gerald",
    "Hector", "Isaac", "Jerome", "Kenneth", "Leonard", "Mohammed", "Nathan",
    "Oscar", "Patrick", "Quentin", "Ronald", "Stanley", "Tyrone", "Victor",
]
# Includes surnames that double as common words or eponyms (Wilson, Bell, Page,
# Hunter) so detectors cannot rely on a capitalised-word heuristic alone.
LAST_NAMES = [
    "Nguyen", "Patel", "Garcia", "Kowalski", "Okafor", "Lindqvist", "Ramirez",
    "Schmidt", "O'Brien", "Yamamoto", "Abdi", "Haddad", "Johansson", "Petrov",
    "Castillo", "Bergstrom", "Murphy", "Dalton", "Hughes", "Kim", "Chen", "Singh",
    "Rossi", "Novak", "Fischer", "Wilson", "Parker", "Bell", "Hunter", "Cross",
    "Young", "King", "Rice", "Long", "White", "Green", "Brown", "Page", "Mason",
    "Walsh", "Reyes", "Foster", "Coleman", "Daniels", "Ellis", "Fletcher",
    "Gibson", "Holland", "Ibrahim", "Jensen", "Keller", "Larsen", "Morales",
    "Nash", "Ortega", "Price", "Quinn", "Russo", "Sandoval", "Tran",
]

STREET_NAMES = [
    "Maple", "Oak", "Cedar", "Elm", "Pine", "Lakeview", "Highland", "Sunset",
    "Willow", "Church", "Mill", "River", "Park", "Meadow", "Prairie", "Washington",
    "Franklin", "Jefferson", "Lincoln", "Madison", "Hillcrest", "Orchard", "Birch",
    "Chestnut", "Walnut", "Spring", "Ridge", "Forest", "Valley", "Summit",
]
STREET_TYPES = ["St", "Ave", "Dr", "Rd", "Ln", "Blvd", "Ct", "Way"]
UNIT_TYPES = ["Apt", "Unit", "Suite"]

# (town, state). Invented combinations; not tied to real addresses.
TOWNS = [
    ("Lindenfield", "IA"), ("Copper Falls", "WI"), ("Marrow Creek", "MN"),
    ("Eastvale", "IL"), ("Harlan Springs", "MO"), ("Pinebrook", "NE"),
    ("Westmoor", "IA"), ("Granite Bend", "SD"), ("Alder Ridge", "WI"),
    ("Fox Hollow", "IL"), ("Stillwater Bay", "MN"), ("Cedar Mills", "IA"),
    ("Ironwood", "MO"), ("Larkspur", "NE"), ("Quail Run", "KS"),
    ("Thornbury", "IL"), ("Brightwater", "WI"), ("Ashgrove", "IA"),
]

PROVIDER_CREDENTIALS = ["MD", "MD", "MD", "DO", "NP", "PA-C"]
PROVIDER_SPECIALTIES = [
    "internal medicine", "cardiology", "pulmonology", "infectious disease",
    "general surgery", "endocrinology", "nephrology", "radiology",
]

EMAIL_DOMAINS = ["example.com", "example.org"]
