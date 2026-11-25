"""Sort transactions into categories with merchant rules.

Order of work:
1. Rules (this file) place every merchant they recognize. They never need the AI.
2. Merchants the rules cannot place are sent to Claude (core/ai.py).
3. Anything still unplaced goes to "Miscellaneous", tagged "Unplaced" so the
   user can find and fix it with the review toggle.

The rules are written for Canadian (mostly Calgary/Alberta) card and bank
descriptions. Card processors add prefixes such as "SQ *" (Square),
"TST*" (Toast, used by restaurants), "DD *" (DoorDash) and "PAYPAL *"; these
are handled here.
"""
from __future__ import annotations

import re

import pandas as pd

SPENDING_CATEGORIES = [
    "Housing", "Groceries", "Dining Out", "Transport", "Subscriptions", "Shopping",
    "Bills & Utilities", "Health & Personal", "Entertainment", "Travel", "Miscellaneous",
]
MISC = "Miscellaneous"
TRANSFERS = "Transfers (excluded)"
INCOMING = "Money in (ignored)"
NEEDS_REVIEW = "Needs review"   # temporary state between the rules and the AI step
ALL_CHOICES = SPENDING_CATEGORIES + [TRANSFERS]
EXCLUDED = {TRANSFERS, INCOMING}
DISCRETIONARY = ["Dining Out", "Shopping", "Entertainment"]

W = r"(?<![A-Z])"   # start of a word (letters only, so '#1234' or '*' before a name still matches)
E = r"(?![A-Z])"    # end of a word

RULES: list[tuple[str, str]] = [
    # ---- transfers between the user's own accounts, card payments ----
    (r"PAYMENT\s*-\s*.*(VISA|MASTERCARD|AMEX|CARD)|PAYMENT RECEIVED|THANK YOU|PAYMENT FROM|"
     r"PYMT|AUTOPAY|CREDIT CARD PAYMENT|MB-CREDIT CARD|PC TO \d|TRANSFER (TO|FROM)|(?<!E-)\bTFR\b|OWN ACCOUNT|"
     r"WEALTHSIMPLE|QUESTRADE|TFSA|RRSP|INVESTMENT", TRANSFERS),

    # ---- subscriptions (before shopping/entertainment, so APPLE.COM/BILL is not "Shopping") ----
    (r"NETFLIX|SPOTIFY|DISNEY|CRAVE|AUDIBLE|APPLE\.COM/BILL|ICLOUD|XBOX|PLAYSTATION NETWORK|" + W + r"PSN" + E + r"|"
     r"PARAMOUNT|PRIME VIDEO|AMAZON PRIME|PRIME MEMBER|AMZN PRIME|YOUTUBE|GOOGLE \*|GOOGLE ONE|PATREON|"
     r"GOODLIFE|ANYTIME FITNESS|PLANET FITNESS|EVOLVE STRENGTH|OPENAI|CHATGPT|CLAUDE\.AI|ANTHROPIC|"
     r"MICROSOFT\*|MSFT \*|ADOBE|DROPBOX|CANVA|NOTION|DUOLINGO|HELLOFRESH|CHEFS PLATE|"
     r"SIRIUSXM|DAZN|TSN DIRECT|SPORTSNET|NINTENDO ONLINE|LINKEDIN|SUBSTACK|MEDIUM\.COM", "Subscriptions"),

    # ---- car rental and liquor stores (before housing/groceries, whose words they contain) ----
    (r"RENT-A-CAR|RENT A CAR|CAR RENTAL|ENTERPRISE RENT|BUDGET RENT|NATIONAL CAR|" + W + r"AVIS" + E + r"|HERTZ",
     "Transport"),
    (r"CO-OP WINE|COOP WINE|WINE AND BEYOND|WINE & BEYOND|LIQUOR|SPIRITS|BEER STORE|LIQUOR DEPOT", "Shopping"),

    # ---- housing ----
    (W + r"RENT" + E + r"|MORTGAGE|CONDO FEE|CONDO CORP|PROPERTY TAX|STRATA|PROPERTY MGMT|"
     r"BOARDWALK|MAINSTREET EQUITY|SKYLINE LIVING|HOMESTEAD", "Housing"),

    # ---- bills, utilities, phone, internet, insurance, bank fees ----
    (r"ENMAX|ATCO|EPCOR|DIRECT ENERGY|CITY OF CALGARY|UTILITIES|TELUS|ROGERS|BELL CANADA|BELL MOBILITY|"
     r"FIDO|KOODO|VIRGIN PLUS|VIRGIN MOBILE|PUBLIC MOBILE|CHATR|" + W + r"SHAW" + E + r"|FREEDOM MOBILE|LUCKY MOBILE|"
     r"FIZZ|NOVUS|INSURANCE|INTACT|TD INSUR|AVIVA|WAWANESA|BELAIR|SQUARE ONE|COOPERATORS|CO-OPERATORS|"
     r"MANULIFE|SUN LIFE|CANADA LIFE|SERVICE CHARGE|MONTHLY FEE|ANNUAL FEE|OVERDRAFT|NSF|"
     r"INTEREST CHARGE|PURCHASE INTEREST|" + W + r"CRA" + E + r"|CANADA REVENUE|AMA MEMBERSHIP|ALBERTA MOTOR ASS", "Bills & Utilities"),

    # ---- travel (before transport so airlines/hotels are not "Transport") ----
    (r"AIR CANADA|WESTJET|FLAIR|PORTER AIR|LYNX AIR|SWOOP|AIRBNB|EXPEDIA|BOOKING\.COM|HOTELS\.COM|"
     r"HOTEL|MARRIOTT|HILTON|HYATT|BEST WESTERN|SANDMAN|HOLIDAY INN|FAIRMONT|DELTA HOTELS|"
     r"PARKS CANADA|YYC AIRPORT|CALGARY AIRPORT|DUTY FREE|VIA RAIL", "Travel"),

    # ---- transport (gas bars of grocery/hardware chains go here first) ----
    (r"CO-OP GAS|COOP GAS|CO-OP FUEL|CANADIAN TIRE GAS|CTC GAS|COSTCO GAS|SUPERSTORE GAS|SAFEWAY GAS|"
     r"PETRO-CANADA|PETRO CANADA|PETROCAN|" + W + r"SHELL" + E + r"|" + W + r"ESSO" + E + r"|HUSKY|CHEVRON|" + W + r"MOBIL" + E + r"|PIONEER|ULTRAMAR|FAS GAS|"
     r"7-ELEVEN.*GAS|GAS BAR|" + W + r"UBER" + E + r"(?!.*EATS)|UBER \*TRIP|UBER\* TRIP|LYFT|"
     r"CALGARY TRANSIT|TRANSIT|MY FARE|COMPASS|PRESTO|PARKPLUS|PARK PLUS|IMPARK|INDIGO PARK|PRECISE PARK|"
     r"PARKING|EASYPARK|HONKMOBILE|CAR WASH|PETRO-PASS|JIFFY LUBE|MR\.? LUBE|KAL TIRE|" + W + r"MIDAS" + E + r"|"
     r"ENTERPRISE RENT|BUDGET RENT|NATIONAL CAR|" + W + r"AVIS" + E + r"|HERTZ|EVO CAR|COMMUNAUTO|REGISTRY|AUTO REPAIR", "Transport"),

    # ---- groceries ----
    (r"SAFEWAY|SUPERSTORE|REAL CDN|REAL CANADIAN|SOBEYS|CO-OP|" + W + r"COOP" + E + r"|NO FRILLS|NOFRILLS|COSTCO|"
     r"T&T|T & T|FRESHCO|SAVE ON FOODS|SAVE-ON-FOODS|LOBLAW|" + W + r"IGA" + E + r"|" + W + r"METRO" + E + r"|FOOD BASICS|WHOLE FOODS|FARM BOY|"
     r"H MART|HMART|INSTACART|VOILA|FRESH ST|BULK BARN|SUNTERRA|COMMUNITY NATURAL|BLUSH LANE|"
     r"OKANAGAN MARKET|GROCERY|SUPERMARKET|PRICESMART|"
     r"FRUITICANA|BUTCHER|MEAT SHOP|BAKERY|DOLLAR GROCER", "Groceries"),

    # ---- dining out ----
    (r"TST\*|TST \*|DD \*|DOORDASH|SKIP THE DISHES|SKIPTHEDISHES|SKIP \*|UBER\s*\*?\s*EATS|UBEREATS|"
     r"TIM HORTONS|TIMHORTONS|STARBUCKS|SECOND CUP|BLENZ|PHIL & SEBASTIAN|PHIL&SEBASTIAN|ROSSO|"
     r"MCDONALD|A&W|A & W|WENDY|BURGER KING|KFC|POPEYES|CHICK-FIL-A|SUBWAY|MR\.? SUB|FIVE GUYS|"
     r"DAIRY QUEEN|" + W + r"DQ" + E + r"|MARY BROWN|HARVEY|CARL'S JR|TACO BELL|TACO TIME|CHIPOTLE|BARBURRITO|"
     r"MUCHO BURRITO|QUESADA|OSMOW|NANDO|FRESHII|PANAGO|PIZZA|PIZZERIA|DOMINO|LITTLE CAESAR|BOSTON PIZZA|"
     r"MONTANA|CACTUS CLUB|EARLS|JOEY|MOXIE|KELSEY|DENNY|" + W + r"CORA" + E + r"|" + W + r"OEB" + E + r"|ORIGINAL JOE|BROWNS SOCIALHOUSE|"
     r"MILESTONES|THE KEG|CHOP STEAK|SMITTY|ELEPHANT & CASTLE|BIG SECRET|SPOLUMBO|"
     r"BOOSTER JUICE|JUGO JUICE|DAVIDSTEA|DAVID'S TEA|CHATIME|COCO FRESH|GONG CHA|BUBBLE TEA|"
     r"KRISPY KREME|COBS BREAD|CINNABON|BEAVERTAILS|MENCHIE|MARBLE SLAB|"
     r"RESTAURANT|RESTAURA|GRILL|PUB" + E + r"|TAVERN|DINER|BISTRO|CAFE|CAFFE|COFFEE|ESPRESSO|"
     r"ROASTER|BREWING|BREWERY|BREWPUB|KITCHEN|EATERY|EATS|SUSHI|RAMEN|PHO" + E + r"|NOODLE|DUMPLING|"
     r"" + W + r"THAI" + E + r"|VIETNAM|" + W + r"VIET" + E + r"|INDIAN|CURRY|TANDOORI|SHAWARMA|DONAIR|KEBAB|GYRO|TACO|BURRITO|BURGER|WINGS|"
     r"CHICKEN|BBQ|BAR-B-Q|SMOKEHOUSE|STEAKHOUSE|" + W + r"STEAK" + E + r"|BUFFET|DIM SUM|BAR & GRILL|LOUNGE|" + W + r"BAR" + E + r"|"
     r"FOOD TRUCK|FOOD COURT|DELI" + E + r"|BAGEL|CREPE|WAFFLE|GELATO|ICE CREAM|DONUT|DOUGHNUT", "Dining Out"),

    # ---- health and personal care ----
    (r"SHOPPERS DRUG|SHOPPERS|REXALL|LONDON DRUGS|PHARMA|DRUG MART|DRUGS|DENTAL|DENTIST|CLINIC|MEDICAL|"
     r"PHYSIO|CHIRO|MASSAGE|OPTOMETR|OPTICAL|SPECSAVERS|CLEARLY|LENSCRAFTERS|SALON|BARBER|HAIR|NAILS|"
     r"" + W + r"SPA" + E + r"|SEPHORA|LUSH|BATH & BODY|BATH AND BODY|MAC COSMETICS|" + W + r"VET" + E + r"|VETERINAR|"
     r"COUNSELL|PSYCH|LIFELABS|DYNACARE", "Health & Personal"),

    # ---- shopping (general merchandise, online, clothing, home, electronics) ----
    (r"WALMART|WAL-MART|WAL MART|AMAZON|AMZN|DOLLARAMA|DOLLAR TREE|GIANT TIGER|CANADIAN TIRE|CDN TIRE|"
     r"WINNERS|MARSHALLS|HOMESENSE|HOME SENSE|HOME DEPOT|RONA|LOWE'S|LOWES|IKEA|STRUCTUBE|WAYFAIR|"
     r"BEST BUY|BESTBUY|STAPLES|THE SOURCE|APPLE STORE|APPLE\.COM/CA|MEMORY EXPRESS|VISIONS|"
     r"INDIGO|CHAPTERS|SPORT CHEK|SPORTCHEK|SPORTING LIFE|" + W + r"MEC" + E + r"|MOUNTAIN EQUIP|ATMOSPHERE|"
     r"MARK'S|MARKS WORK|OLD NAVY|" + W + r"GAP" + E + r"|UNIQLO|H&M|H & M|ZARA|LULULEMON|ARITZIA|SIMONS|HUDSON'S BAY|"
     r"HUDSONS BAY|THE BAY|NORDSTROM|SAKS|NIKE|ADIDAS|FOOT LOCKER|SPORTS EXPERTS|SOFTMOC|ALDO|"
     r"AMERICAN EAGLE|ABERCROMBIE|HOLLISTER|URBAN OUTFITTERS|GARAGE|DYNAMITE|REITMANS|PENNINGTON|"
     r"SHEIN|TEMU|ALIEXPRESS|EBAY|ETSY|SHOPIFY|PAYPAL \*|BEST BUY|PETSMART|PET VALU|PETLAND|"
     r"MICHAELS|DESERRES|TOYS R US|EB GAMES|GAMESTOP|LEGO|BED BATH|KITCHEN STUFF|CRATE & BARREL|"
     r"POTTERY BARN|CHAPTERS|COSTCO\.CA|SAMSUNG|" + W + r"SONY" + E + r"|" + W + r"DELL" + E + r"|LENOVO|FLORIST|FLOWERS|"
     r"LIQUOR|WINE|SPIRITS|BEER STORE|CO-OP WINE|WINE AND BEYOND|WINE & BEYOND|STAR LIQUOR|"
     r"PURE CANADIAN|7-ELEVEN|7 ELEVEN|CIRCLE K|MACS CONV|HUSKY MARKET|CONVENIENCE", "Shopping"),

    # ---- entertainment ----
    (r"CINEPLEX|LANDMARK CINEMA|IMAX|TICKETMASTER|EVENTBRITE|STUBHUB|LIVE NATION|SCOTIABANK SADDLEDOME|"
     r"STAMPEDE|CALGARY ZOO|HERITAGE PARK|TELUS SPARK|STUDIO BELL|GLENBOW|CONTEMPORARY CALGARY|"
     r"BOWLING|BOWL" + E + r"|GOLF|TOPGOLF|CLIMB|BOULDER|ESCAPE ROOM|ARCADE|CHUCK E|LASER TAG|" + W + r"SKI" + E + r"|SUNSHINE VILLAGE|"
     r"LAKE LOUISE|NORQUAY|NAKISKA|WINSPORT|STEAM" + E + r"|NINTENDO|PLAYSTATION|EPIC GAMES|RIOT|"
     r"BLIZZARD|TWITCH|STEAMGAMES|THEATRE|THEATER|CONCERT|MUSEUM|GALLERY|CASINO|LOTTO|LOTTERY|AGLC", "Entertainment"),

    # ---- recognized, but purpose unknown ----
    (r"E-TRANSFER|ETRANSFER|E-TFR|INTERAC E|SEND E-TFR|" + W + r"ATM" + E + r"|CASH WITHDRAWAL|" + W + r"ABM" + E + r"|CHEQUE|CHECK #|"
     r"PAYPAL|VENMO", MISC),
]
_COMPILED = [(re.compile(p, re.I), c) for p, c in RULES]


def rule_category(description: str, amount: float) -> str:
    desc = str(description).upper()
    if amount > 0:
        for rx, cat in _COMPILED:
            if cat == TRANSFERS and rx.search(desc):
                return TRANSFERS
        return INCOMING
    for rx, cat in _COMPILED:
        if rx.search(desc):
            return cat
    return NEEDS_REVIEW


def apply_rules(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["Category"] = [rule_category(d, a) for d, a in zip(df["Description"], df["Amount"])]
    df["Source"] = "Rule"
    df.loc[df["Category"] == NEEDS_REVIEW, "Source"] = "Unplaced"
    df.loc[df["Category"] == INCOMING, "Source"] = "Money in"
    return df


def unplaced_merchants(df: pd.DataFrame) -> list[str]:
    return sorted(df.loc[df["Category"] == NEEDS_REVIEW, "Description"].unique().tolist())


def finish_unplaced(df: pd.DataFrame) -> pd.DataFrame:
    """Anything neither the rules nor the AI placed becomes Miscellaneous, tagged Unplaced."""
    df = df.copy()
    left = df["Category"] == NEEDS_REVIEW
    df.loc[left, "Category"] = MISC
    df.loc[left, "Source"] = "Unplaced"
    return df
