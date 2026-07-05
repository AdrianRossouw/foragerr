"""SSRF egress validation for outbound requests (FRG-SEC-001).

Every hop of every outbound request — including the initial request — is
validated here BEFORE any connection is attempted:

- the scheme must be ``http`` or ``https``;
- the URL host is interpreted as an IP literal where possible, including the
  decimal (``http://2130706433/``) and hex (``http://0x7f000001/``) single-
  integer IPv4 encodings — such hosts are never handed to DNS;
- otherwise the host is DNS-resolved, and the request is refused if ANY
  resolved address is loopback, link-local, RFC-1918 private, or IPv6
  unique-local (ULA);
- refusals are logged as policy-violation errors naming the offending
  address, with the URL redacted (FRG-NFR-008).

Two client profiles exist (design decision 9):

- ``external`` (default): the full policy applies to every hop.
- ``local-service``: an operator explicitly configured this integration's
  base URL (e.g. SABnzbd on a LAN/RFC-1918 address); requests matching that
  exact base URL origin (scheme + host + port) are allowed. Any OTHER
  destination — including redirect hops leaving the base origin — falls back
  to the full ``external`` policy.

Residual risk — DNS-rebinding TOCTOU: the host is resolved and policy-checked
here, then the hostname is handed to httpx, which re-resolves it at connect
time. A hostile authoritative DNS server can answer the policy check with a
public address and the connect-time lookup with a private one. This window is
an accepted residual at foragerr's home-server threat level and is recorded in
``docs/security/risk-register.md`` (RISK-025); per-hop re-validation and
disabled auto-redirects are the compensating M1 controls.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
from typing import Awaitable, Callable, Iterable, NoReturn, Sequence

import httpx

from foragerr.http.errors import EgressPolicyError
from foragerr.logging import redact

logger = logging.getLogger("foragerr.http.egress")

#: Client profiles (FRG-SEC-001).
EXTERNAL = "external"
LOCAL_SERVICE = "local-service"

ALLOWED_SCHEMES = frozenset({"http", "https"})

#: async resolver signature: hostname -> sequence of IP address strings.
Resolver = Callable[[str], Awaitable[Sequence[str]]]

_DECIMAL_HOST_RE = re.compile(r"[0-9]+")
_HEX_HOST_RE = re.compile(r"0[xX][0-9a-fA-F]+")

_RFC_1918 = tuple(
    ipaddress.ip_network(net)
    for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
_IPV6_ULA = ipaddress.ip_network("fc00::/7")

_IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


async def default_resolver(host: str) -> Sequence[str]:
    """Resolve ``host`` to all of its A/AAAA addresses (non-blocking)."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None)
    return [info[4][0] for info in infos]


def interpret_host_as_ip(host: str) -> _IPAddress | None:
    """Interpret a URL host string as an IP literal, if it is one.

    Handles dotted/colon literals (``127.0.0.1``, ``::1`` — httpx strips the
    brackets), plus single-integer decimal (``2130706433``) and hex
    (``0x7f000001``) IPv4 encodings. These forms arrive as the URL host
    string and MUST be treated as addresses, never DNS-resolved as names.

    Returns ``None`` when the host is a plain DNS name. Raises
    ``ValueError`` for numeric-shaped hosts that are not valid addresses
    (all-digit / hex hosts are never legitimate DNS names, so the caller
    refuses them rather than resolving).
    """
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    if _DECIMAL_HOST_RE.fullmatch(host):
        # leading-zero decimal forms are octal per inet_aton
        value = int(host, 8) if len(host) > 1 and host.startswith("0") else int(host)
    elif _HEX_HOST_RE.fullmatch(host):
        value = int(host, 16)
    else:
        return None  # a plain DNS name — resolve it
    if 0 <= value <= 0xFFFF_FFFF:
        return ipaddress.IPv4Address(value)
    raise ValueError(f"numeric host is not a valid IPv4 encoding: {host}")


def _forbidden_ipv4_reason(address: ipaddress.IPv4Address) -> str | None:
    """Why an IPv4 address is refused, or ``None`` if it is acceptable."""
    if address.is_unspecified:
        return "unspecified"
    if address.is_loopback:
        return "loopback"
    if address.is_link_local:
        return "link-local"
    if any(address in net for net in _RFC_1918):
        return "private (RFC 1918)"
    return None


def _embedded_ipv4_candidates(
    address: ipaddress.IPv6Address,
) -> list[ipaddress.IPv4Address]:
    """Every IPv4 address an IPv6 literal can smuggle past IPv6-only checks.

    Covers the IPv4-mapped (``::ffff:a.b.c.d``), IPv4-compatible ``::/96``
    (``::a.b.c.d`` — routes via the embedded IPv4 on Linux yet is neither
    ``is_loopback`` nor ``is_private``), 6to4 (``2002::/16``) and Teredo
    (``2001:0::/32``) tunnelling forms. Each candidate is judged with the
    same IPv4 policy so none of these encodings can reach a forbidden host.
    """
    candidates: list[ipaddress.IPv4Address] = []
    mapped = address.ipv4_mapped
    if mapped is not None:
        candidates.append(mapped)
    # IPv4-compatible ::/96: 12 leading zero bytes, IPv4 in the low 32 bits.
    # :: (unspecified) and ::1 (loopback) are already refused as IPv6 below,
    # so they are excluded here per FRG-SEC-001.
    if (
        address.packed[:12] == b"\x00" * 12
        and not address.is_unspecified
        and not address.is_loopback
    ):
        candidates.append(ipaddress.IPv4Address(address.packed[12:]))
    sixtofour = address.sixtofour
    if sixtofour is not None:
        candidates.append(sixtofour)
    teredo = address.teredo
    if teredo is not None:
        candidates.append(teredo[1])  # (server, client): the client is embedded
    return candidates


def forbidden_reason(address: _IPAddress) -> str | None:
    """Why this address is refused by the egress policy, or ``None`` if it
    is acceptable (FRG-SEC-001: loopback, link-local, RFC-1918, IPv6 ULA).

    IPv6 addresses are additionally screened for any embedded IPv4 they route
    to — IPv4-mapped, IPv4-compatible ``::/96``, 6to4 and Teredo — and refused
    when that embedded IPv4 is forbidden, so none of those tunnelling forms
    can smuggle a request to a loopback/private host past the IPv6 checks."""
    if isinstance(address, ipaddress.IPv6Address):
        for candidate in _embedded_ipv4_candidates(address):
            reason = _forbidden_ipv4_reason(candidate)
            if reason is not None:
                return reason
        if address.is_unspecified:
            return "unspecified"
        if address.is_loopback:
            return "loopback"
        if address.is_link_local:
            return "link-local"
        if address in _IPV6_ULA:
            return "unique-local (ULA)"
        return None
    return _forbidden_ipv4_reason(address)


def same_origin(url: httpx.URL, base: httpx.URL) -> bool:
    """True when ``url`` shares scheme, host, and effective port with ``base``."""
    default_ports = {"http": 80, "https": 443}
    return (
        url.scheme == base.scheme
        and url.host.lower() == base.host.lower()
        and (url.port or default_ports.get(url.scheme))
        == (base.port or default_ports.get(base.scheme))
    )


class EgressValidator:
    """Validates one request hop against the egress policy (FRG-SEC-001).

    Parameters
    ----------
    resolver:
        DNS resolution injection point. Production always uses
        :func:`default_resolver`; tests inject a stub to simulate hostile
        records (e.g. a name whose A records mix public and private
        addresses) without real DNS traffic.
    test_allow_addresses:
        TEST-ONLY escape hatch: IP addresses listed here are treated as
        public so the test suite can exercise the full request path against
        fixture servers bound to 127.0.0.1. Production wiring never passes
        this argument (the static-guard test keeps all client construction
        inside this package, and nothing in ``foragerr`` sets it); it does
        not weaken scheme checks, redirect bounds, or any other control.
    """

    def __init__(
        self,
        *,
        resolver: Resolver | None = None,
        test_allow_addresses: Iterable[str] = (),
    ) -> None:
        self._resolver: Resolver = resolver or default_resolver
        self._test_allow = frozenset(
            ipaddress.ip_address(addr) for addr in test_allow_addresses
        )

    async def validate(
        self,
        url: httpx.URL,
        *,
        profile: str = EXTERNAL,
        local_base: httpx.URL | None = None,
    ) -> None:
        """Validate a single hop BEFORE any connection is made.

        Raises :class:`EgressPolicyError` (already logged, URL redacted) when
        the hop violates the policy; returns silently when it is allowed.
        """
        if url.scheme not in ALLOWED_SCHEMES:
            self._refuse(url, reason=f"forbidden scheme {url.scheme!r}")
        if not url.host:
            self._refuse(url, reason="URL has no host")

        if (
            profile == LOCAL_SERVICE
            and local_base is not None
            and same_origin(url, local_base)
        ):
            # Operator-configured base URL: explicitly trusted for THIS
            # client only. Anything off the base origin (e.g. a redirect)
            # falls through to the full external policy below.
            return

        try:
            literal = interpret_host_as_ip(url.host)
        except ValueError:
            self._refuse(url, reason=f"unparseable numeric host {url.host!r}")
        if literal is not None:
            addresses: Sequence[_IPAddress] = [literal]
        else:
            try:
                resolved = await self._resolver(url.host)
            except OSError as exc:
                self._refuse(url, reason=f"DNS resolution failed: {exc}")
            addresses = [ipaddress.ip_address(addr) for addr in resolved]
            if not addresses:
                self._refuse(url, reason="DNS resolution returned no addresses")

        # ANY forbidden record refuses the whole request (multi-record names
        # where only one address is private are still refused).
        for address in addresses:
            if address in self._test_allow:
                continue
            reason = forbidden_reason(address)
            if reason is not None:
                self._refuse(url, reason=reason, offending_address=str(address))

    def _refuse(
        self,
        url: httpx.URL,
        *,
        reason: str,
        offending_address: str | None = None,
    ) -> NoReturn:
        safe_url = redact(str(url))
        detail = f" (resolved address {offending_address})" if offending_address else ""
        message = f"egress policy violation: {reason}{detail} for url {safe_url}"
        logger.error(message)
        raise EgressPolicyError(
            message, url=safe_url, offending_address=offending_address, reason=reason
        )
