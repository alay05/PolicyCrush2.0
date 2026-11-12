from sources.congress_meetings import fetch_committee_hearings


SENATE_COMMITTEE_BY_PREFIX = {
    "spag": "Aging",
    "ssap": "Appropriations",
    "ssbu": "Budget",
    "ssfi": "Finance",
    "sshr": "Health, Education, Labor & Pensions (HELP)",
    "ssga": "Homeland Security and Governmental Affairs (Oversight)",
    "slia": "Indian Affairs",
    "ssju": "Judiciary",
    "ssva": "Veterans Affairs",
    "sssb": "Small Business",
}


def fetch_senate_hearings(start_date=None, *, today=None):
    """Return official Congress.gov Senate hearings for existing committees."""
    return fetch_committee_hearings(
        "senate",
        SENATE_COMMITTEE_BY_PREFIX,
        start_date,
        today=today,
    )
