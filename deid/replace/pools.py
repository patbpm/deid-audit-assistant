"""Surrogate value pools for the replacement engine.

Deliberately disjoint from deid/synth/pools.py, so a surrogate never equals a
name the generator can produce (a test enforces this). They are invented or
generic, and the engine also refuses any surrogate that equals a real value
found in the notes being processed.
"""

FIRST = [
    "Adrian", "Beverly", "Cordell", "Delphine", "Everett", "Felicity", "Gideon",
    "Henrietta", "Ignatius", "Jocelyn", "Lazarus", "Marguerite", "Nolan", "Ophelia",
    "Percival", "Rosalind", "Silas", "Theodora", "Ulysses", "Vivian", "Wendell",
    "Xavier", "Yolanda", "Zachary", "Anselm", "Bernadette", "Cyrus", "Dorothea",
    "Emmett", "Fenella", "Gareth", "Hortense", "Ivor", "Josephine", "Lucian",
    "Mirabel", "Nigel", "Odette", "Peregrine", "Rowena", "Sylvester", "Tabitha",
    "Uriah", "Verity", "Winifred", "Alaric", "Blythe", "Caspian", "Donovan",
    "Elspeth", "Floyd", "Genevieve", "Horatio", "Isolde", "Julian", "Kendra",
    "Leopold", "Millicent", "Ambrose", "Cecily", "Desmond", "Eulalia", "Fergus",
    "Giselle", "Hamish", "Iris", "Jasper", "Lenora", "Magnus", "Nadine", "Orson",
    "Philippa", "Rupert", "Sabrina", "Tobias", "Una", "Viola", "Willem", "Agatha",
    "Barnaby", "Clement", "Dahlia", "Edmund", "Flora", "Gustav", "Helena", "Ingeborg",
    "Jonas", "Kit", "Lydia", "Mortimer", "Nell", "Otis", "Pearl", "Quincy", "Reuben",
    "Stella", "Thaddeus", "Ursula", "Vernon", "Wilhelmina", "Alden", "Briar",
]
LAST = [
    "Ashworth", "Blackwood", "Carrow", "Dunmore", "Eastman", "Fairweather",
    "Galloway", "Hargrove", "Ingram", "Jessup", "Kingsley", "Lockhart", "Marlowe",
    "Northcott", "Oakley", "Pemberton", "Quillfeather", "Ravenscroft", "Sutcliffe",
    "Thistlewood", "Underhill", "Vandermeer", "Whitlock", "Yarborough", "Zeller",
    "Aldous", "Bramwell", "Calloway", "Delacroix", "Ellsworth", "Farnsworth",
    "Gladstone", "Hawthorne", "Islington", "Jarrett", "Kensington", "Lanchester",
    "Mortensen", "Nightingale", "Ormsby", "Prescott", "Rutherford", "Stanhope",
    "Treadwell", "Upshaw", "Valmont", "Wetherby", "Ainsley", "Barrington", "Castellan",
    "Drummond", "Everhart", "Fenwick", "Grantham", "Holloway", "Ivesley", "Kirkland",
    "Langford", "Montrose", "Norwood", "Overton", "Penhallow", "Radcliffe", "Selwyn",
    "Thorne", "Ulrich", "Vickery", "Winslow", "Alcott", "Brockway", "Cavendish",
    "Dalrymple", "Edgerton", "Fitzwilliam", "Goodwin", "Harcourt", "Inglewood",
    "Jameson", "Kettering", "Lovelace", "Merriweather", "Nethercott", "Oswald",
    "Pickering", "Quarles", "Rosewell", "Spalding", "Tennison", "Umber", "Wexford",
    "Yardley", "Abernathy", "Birchall", "Colebrook", "Dorrance", "Eldridge", "Frost",
]
# Usable as a first or a last name; used for a name seen only on its own.
EITHER = [
    "Morgan", "Taylor", "Jordan", "Avery", "Rowan", "Sutton", "Emerson", "Harper",
    "Quinlan", "Reese", "Sawyer", "Tatum", "Wren", "Linden", "Marlow", "Sloane",
    "Briggs", "Carson", "Dallas", "Elliot", "Finley", "Greer", "Hollis", "Jules",
    "Kendall", "Landry", "Monroe", "Nico", "Oakes", "Palmer",
]
STREETS = [
    "Aspen", "Bluebell", "Clover", "Dogwood", "Evergreen", "Fernwood", "Goldenrod",
    "Heather", "Ivy", "Juniper", "Kestrel", "Laurel", "Magnolia", "Nutmeg", "Osprey",
    "Primrose", "Quarry", "Rosemary", "Sycamore", "Tamarack", "Violet", "Wisteria",
    "Alder", "Bayberry", "Cypress", "Driftwood", "Elderberry", "Foxglove", "Hickory",
    "Lavender",
]
TOWNS = [
    "Ambergate", "Brookhaven", "Coldwater Gap", "Dunmere", "Elmsford Hollow",
    "Fairhaven Point", "Glenrock", "Havenwood", "Iron Mill", "Juniper Flats",
    "Kestrel Bluff", "Lakemont", "Maplecrest", "Northfold", "Oak Harbor Ridge",
    "Pebble Run", "Quarry Hill", "Redfield Springs", "Silverbrook", "Tamarack Pass",
    "Upland Creek", "Valleyview Grove", "Willowmere", "Yewdale", "Zephyr Glen",
    "Ashby Crossing", "Briarwood Falls", "Cinder Lake", "Dovecote", "Emberfield",
]
EMAIL_DOMAINS = ("example.com", "example.org")
