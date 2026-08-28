"""Routing rules: decides what counts as a qualified assignment.

Single source of truth for both the digest (src/digest.py) and the email
notification (src/notify.py). The classifier (src/classifier.py) fills in the
fields this module reads; nothing here calls the LLM or touches the network.
"""

from src.models import Assignment


def is_qualified(a: Assignment) -> bool:
    """True for assignments that belong in the strict "Uppdrag" section.

    An unknown location (location_ok is None) does not disqualify, only an
    explicit False does.
    """
    return (
        a.classified
        and a.employment_type == "contract"
        and a.role_match == "core"
        and a.location_ok is not False
        and a.status == "open"
    )


def disqualify_reason(a: Assignment) -> str:
    """Short Swedish label explaining why an assignment is not qualified.

    Returns "" for qualified assignments. The order below is the priority
    order: the first matching reason wins.
    """
    if not a.classified:
        return "Ej klassificerad"
    if a.status == "filled":
        return "Tillsatt"
    if a.status == "paused":
        return "Pausad"
    if a.employment_type == "permanent":
        return "Anställning"
    if a.employment_type == "unclear":
        return "Oklar uppdragsform"
    if a.role_match == "none":
        return "Fel roll"
    if a.role_match == "adjacent":
        return "Angränsande roll"
    if a.location_ok is False:
        return "Fel ort"
    if a.status == "unknown":
        return "Oklar status"
    return ""
