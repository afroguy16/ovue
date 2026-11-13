"""Pointer use cases and their application-level validation rules."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from ovue.modules.pointers.storage import CapacityExceeded, NewPointer, SQLitePointerStorage


@dataclass(frozen=True)
class AuthenticatedSeat:
    """Identify the sender resolved by the seats module."""

    id: str
    display_name: str
    role: str


@dataclass(frozen=True)
class SendCommand:
    """Carry the pointer fields supplied to the send use case."""

    to: tuple[str, ...]
    ref_url: str
    ref_title: str | None
    description: str
    kind: str


@dataclass(frozen=True)
class PointerSettings:
    """Hold only the limits and URL policy used by pointer sending."""

    allowed_hosts: frozenset[str]
    max_pointer_records: int
    max_logical_database_bytes: int
    max_unread_per_seat: int


@dataclass(frozen=True)
class ValidationIssue:
    """Describe one safe validation failure without submitted values."""

    code: str
    message: str
    path: tuple[str | int, ...]


class SendValidationError(Exception):
    """Expose all send validation issues without reflecting unsafe input."""

    def __init__(self, issues: tuple[ValidationIssue, ...]) -> None:
        """Store structured issues while keeping the exception text generic."""
        self.issues = issues
        super().__init__("Pointer send validation failed")


@dataclass(frozen=True)
class Delivery:
    """Represent one recipient's independent pointer delivery."""

    delivery_id: str
    recipient_id: str
    state: str


@dataclass(frozen=True)
class SendResult:
    """Represent the pointer and deliveries created by a successful send."""

    pointer_id: str
    deliveries: tuple[Delivery, ...]


class PointerService:
    """Validate and persist pointer sends through the storage boundary."""

    _KINDS = frozenset({"done", "blocked", "needs-decision", "info", "acknowledged"})
    _TITLE_PATTERN = re.compile(r"[A-Za-z0-9 _.#-]*\Z")

    def __init__(self, *, storage: SQLitePointerStorage, settings: PointerSettings) -> None:
        """Keep persistence and validated policy explicit dependencies."""
        self._storage = storage
        self._settings = settings

    def send(
        self,
        *,
        sender: AuthenticatedSeat,
        command: SendCommand,
        known_seat_ids: set[str],
    ) -> SendResult:
        """Validate a pointer and atomically persist it with all deliveries."""
        recipients, issues = self._validate(sender, command, known_seat_ids)
        if issues:
            raise SendValidationError(tuple(issues))

        pointer = NewPointer(
            sender_id=sender.id,
            sender_display_name=sender.display_name,
            sender_role=sender.role,
            recipients=recipients,
            ref_url=command.ref_url,
            ref_title=command.ref_title,
            description=command.description,
            kind=command.kind,
        )
        try:
            return self._storage.persist_send(
                pointer,
                max_pointer_records=self._settings.max_pointer_records,
                max_logical_database_bytes=self._settings.max_logical_database_bytes,
                max_unread_per_seat=self._settings.max_unread_per_seat,
            )
        except CapacityExceeded as error:
            issue = ValidationIssue(
                code=error.code,
                message=error.message,
                path=error.path,
            )
            raise SendValidationError((issue,)) from None

    def _validate(
        self,
        sender: AuthenticatedSeat,
        command: SendCommand,
        known_seat_ids: set[str],
    ) -> tuple[tuple[str, ...], list[ValidationIssue]]:
        """Check the pointer contract and normalize duplicate recipients."""
        issues: list[ValidationIssue] = []
        recipients = tuple(dict.fromkeys(command.to))

        if not command.to:
            issues.append(ValidationIssue("required", "At least one recipient is required", ("to",)))
        if len(command.to) > 10:
            issues.append(ValidationIssue("too_many_recipients", "At most 10 recipients are allowed", ("to",)))
        for recipient_id in recipients:
            if recipient_id == sender.id:
                issues.append(ValidationIssue("sender_is_recipient", "A seat cannot send to itself", ("to",)))
            elif recipient_id != "operator" and recipient_id not in known_seat_ids:
                issues.append(ValidationIssue("unknown_seat_id", "Recipient seat is unknown", ("to",)))

        issues.extend(self._validate_url(command.ref_url))
        if command.ref_title is not None:
            if len(command.ref_title) > 12:
                issues.append(ValidationIssue("too_long", "Title exceeds 12 characters", ("ref", "title")))
            if not self._TITLE_PATTERN.fullmatch(command.ref_title):
                issues.append(ValidationIssue("invalid_characters", "Title contains unsupported characters", ("ref", "title")))
        if len(command.description) > 120:
            issues.append(ValidationIssue("too_long", "Description exceeds 120 characters", ("description",)))
        if any(character < " " or character > "~" for character in command.description):
            issues.append(ValidationIssue("invalid_characters", "Description must be printable ASCII only", ("description",)))
        if command.kind not in self._KINDS:
            issues.append(ValidationIssue("unsupported_kind", "Pointer kind is unsupported", ("kind",)))

        return recipients, issues

    def _validate_url(self, value: str) -> list[ValidationIssue]:
        """Validate an absolute reference URL without including it in errors."""
        issues: list[ValidationIssue] = []
        try:
            parsed = urlsplit(value)
            hostname = parsed.hostname
            port = parsed.port
        except ValueError:
            return [ValidationIssue("invalid_url", "URL is invalid", ("ref", "url"))]

        if parsed.scheme != "https":
            issues.append(ValidationIssue("invalid_scheme", "Must be https", ("ref", "url")))
        if not parsed.scheme or not parsed.netloc or hostname is None:
            issues.append(ValidationIssue("invalid_url", "URL must be absolute", ("ref", "url")))
            return issues
        if parsed.username is not None or parsed.password is not None:
            issues.append(ValidationIssue("userinfo_not_allowed", "URL user information is not allowed", ("ref", "url")))
        if parsed.query or parsed.fragment:
            issues.append(ValidationIssue("query_or_fragment_not_allowed", "Remove the query string or fragment from the URL", ("ref", "url")))
        if port not in (None, 443):
            issues.append(ValidationIssue("non_default_port", "URL must use the default port", ("ref", "url")))

        normalized_host = hostname.lower()
        try:
            ipaddress.ip_address(normalized_host)
        except ValueError:
            is_ip_literal = False
        else:
            is_ip_literal = True
        if is_ip_literal or normalized_host.endswith(".") or "xn--" in normalized_host:
            issues.append(ValidationIssue("invalid_host", "URL host is not allowed", ("ref", "url")))
        elif normalized_host not in self._settings.allowed_hosts:
            issues.append(ValidationIssue("host_not_allowed", "URL host is not allowed", ("ref", "url")))
        return issues
