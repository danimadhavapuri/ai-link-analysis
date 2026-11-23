"""
SSRF-safe URL validator.

Defence layers:
  1. Scheme whitelist (http / https only)
  2. Hostname blocklist (localhost, .local, .internal, cloud-metadata)
  3. Direct-IP check via ipaddress — covers private/loopback/link-local/reserved
  4. NAT64 (64:ff9b::/96) and IPv4-mapped (::ffff:0:0/96) — unwrap and re-check
  5. DNS resolution → check every resolved address
"""
import ipaddress
import socket
from typing import List, Tuple
from urllib.parse import urlsplit


# ── Custom exceptions ─────────────────────────────────────────────────────────

class URLValidationError(Exception):
    """Bad URL structure or unsupported scheme."""


class SSRFValidationError(URLValidationError):
    """URL resolves to a private / internal / cloud-metadata address."""


# ── Blocked networks (explicit, beyond Python's built-in flags) ───────────────

_BLOCKED_NETS: List[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
    # IPv4
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),    # CGNAT / shared space
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),   # link-local / cloud metadata
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),     # TEST-NET-1
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),  # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),   # TEST-NET-3
    ipaddress.ip_network("224.0.0.0/4"),      # multicast
    ipaddress.ip_network("240.0.0.0/4"),      # reserved
    ipaddress.ip_network("255.255.255.255/32"),
    # IPv6
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("100::/64"),         # discard
    ipaddress.ip_network("2001:db8::/32"),    # documentation
    ipaddress.ip_network("fc00::/7"),         # ULA
    ipaddress.ip_network("fe80::/10"),        # link-local
    ipaddress.ip_network("ff00::/8"),         # multicast
]

_NAT64_PREFIX = ipaddress.ip_network("64:ff9b::/96")

_BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "ip6-loopback",
    "broadcasthost",
    "metadata.google.internal",
    "instance-data",
    "169.254.169.254",
}


# ── Core helpers ──────────────────────────────────────────────────────────────

def _is_ip_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if the IP must be blocked (private / internal / reserved)."""
    # Unwrap IPv4-mapped and NAT64 to validate the embedded IPv4 address.
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            return _is_ip_blocked(ip.ipv4_mapped)
        if ip in _NAT64_PREFIX:
            return _is_ip_blocked(ipaddress.IPv4Address(ip.packed[-4:]))

    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        return True
    if ip.is_reserved and not ip.is_global:
        return True
    for net in _BLOCKED_NETS:
        if ip in net:
            return True
    return False


def validate_and_sanitize_url(url: str, resolve_dns: bool = True) -> Tuple[str, List[str]]:
    """
    Validate *url* and optionally resolve its hostname.

    Returns:
        (clean_url, resolved_ip_strings)

    Raises:
        URLValidationError  – bad syntax / unsupported scheme / missing host
        SSRFValidationError – blocked IP / internal hostname
    """
    if not url or not isinstance(url, str):
        raise URLValidationError("URL must be a non-empty string.")
    url = url.strip()
    if not url:
        raise URLValidationError("URL cannot be empty.")

    try:
        parsed = urlsplit(url)
    except Exception as exc:
        raise URLValidationError(f"Malformed URL: {exc}") from exc

    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise URLValidationError(
            f"Unsupported scheme '{scheme}'. Only http and https are allowed."
        )

    hostname = parsed.hostname
    if not hostname:
        raise URLValidationError("URL is missing a valid hostname.")

    hn = hostname.lower()

    # Hostname blocklist
    if hn in _BLOCKED_HOSTS:
        raise SSRFValidationError(f"SSRF Protection: host '{hostname}' is blocked.")
    if hn.endswith(".localhost") or hn.endswith(".local") or hn.endswith(".internal"):
        raise SSRFValidationError(f"SSRF Protection: domain '{hostname}' is blocked.")

    # Direct IP literal check
    try:
        direct_ip = ipaddress.ip_address(hn)
        if _is_ip_blocked(direct_ip):
            raise SSRFValidationError(
                f"SSRF Protection: IP address '{direct_ip}' is blocked."
            )
        return url, [str(direct_ip)]
    except ValueError:
        pass  # not a literal IP — proceed to DNS

    if not resolve_dns:
        return url, []

    # DNS resolution — check every returned address
    try:
        port = parsed.port or (443 if scheme == "https" else 80)
        addr_infos = socket.getaddrinfo(hn, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise URLValidationError(f"Cannot resolve '{hostname}': {exc.strerror}") from exc

    resolved: List[str] = []
    for entry in addr_infos:
        ip_str = entry[4][0]
        resolved.append(ip_str)
        try:
            ip_obj = ipaddress.ip_address(ip_str)
            if _is_ip_blocked(ip_obj):
                raise SSRFValidationError(
                    f"SSRF Protection: '{hostname}' resolves to blocked IP '{ip_str}'."
                )
        except ValueError:
            continue

    if not resolved:
        raise URLValidationError(f"No IP addresses resolved for '{hostname}'.")

    return url, resolved
