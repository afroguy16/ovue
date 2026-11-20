"""Translate untrusted JSON objects into typed pointer submissions."""

from ovue.operations.validation import Issue, IssueRejected, Payload


def parse_pointer_payload(value: object) -> Payload:
    """Validate pointer object structure and collect safe field-type issues."""
    if not isinstance(value, dict):
        raise IssueRejected((Issue("invalid_type", "Expected a JSON object", ()),))
    issues: list[Issue] = []
    allowed = {"to", "ref", "description", "kind"}
    for key in value:
        if key == "from":
            issues.append(
                Issue(
                    "field_not_allowed",
                    "Sender is derived from authentication",
                    ("from",),
                )
            )
        elif key not in allowed:
            issues.append(Issue("field_not_allowed", "Field is not allowed", (key,)))

    recipients = value.get("to")
    if not isinstance(recipients, list) or not all(
        isinstance(seat_id, str) for seat_id in recipients
    ):
        issues.append(Issue("invalid_type", "Expected a list of seat IDs", ("to",)))
        recipients = []

    reference = value.get("ref")
    if not isinstance(reference, dict):
        issues.append(Issue("required", "Reference is required", ("ref",)))
        reference = {}
    ref_url = reference.get("url")
    if not isinstance(ref_url, str):
        issues.append(Issue("required", "Reference URL is required", ("ref", "url")))
        ref_url = ""
    ref_title = reference.get("title")
    if ref_title is not None and not isinstance(ref_title, str):
        issues.append(Issue("invalid_type", "Expected a text title", ("ref", "title")))
        ref_title = None
    for field in reference:
        if field not in {"url", "title"}:
            issues.append(
                Issue(
                    "field_not_allowed",
                    "Reference field is not allowed",
                    ("ref", field),
                )
            )

    description = value.get("description")
    if not isinstance(description, str):
        issues.append(Issue("required", "Description is required", ("description",)))
        description = ""
    kind = value.get("kind")
    if not isinstance(kind, str):
        issues.append(Issue("required", "Pointer kind is required", ("kind",)))
        kind = ""

    if issues:
        raise IssueRejected(tuple(issues))
    return Payload(tuple(recipients), ref_url, ref_title, description, kind)
