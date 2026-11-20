import ipaddress
import socket
from typing import List, Optional, Tuple
from urllib.parse import urlsplit


class URLValidationError(Exception):
    """Raised when a URL is syntactically invalid or unsupported."""
    pass


class SSRFValidationError(URLValidationError):
    """Raised when a URL targets a private, loopback, or cloud metadata address."""
    pass


# Specific cloud metadata and non-routable IP networks to explicitly block
BLOCKED_IP_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),         # Current network (only valid as source)
    ipaddress.ip_network("10.0.0.0/8"),        # Private network
    ipaddress.ip_network("100.64.0.0/10"),     # Shared address space / CGNAT
    ipaddress.ip_network("127.0.0.0/8"),       # Loopback
    ipaddress.ip_network("169.254.0.0/16"),    # Link-local / Cloud metadata (169.254.169.254)
    ipaddress.ip_network("172.16.0.0/12"),     # Private network
    ipaddress.ip_network("192.0.0.0/24"),      # IETF Protocol Assignments
    ipaddress.ip_network("192.0.2.0/24"),      # Documentation (TEST-NET-1)
    ipaddress.ip_network("192.88.99.0/24"),    # 6to4 relay
    ipaddress.ip_network("192.168.0.0/16"),    # Private network
    ipaddress.ip_network("198.18.0.0/15"),     # Network interconnect benchmark testing
    ipaddress.ip_network("198.51.100.0/24"),   # Documentation (TEST-NET-2)
    ipaddress.ip_network("203.0.113.0/24"),    # Documentation (TEST-NET-3)
    ipaddress.ip_network("224.0.0.0/4"),       # Multicast
    ipaddress.ip_network("240.0.0.0/4"),       # Reserved for future use
    ipaddress.ip_network("255.255.255.255/32"),# Broadcast
    # IPv6 ranges
    ipaddress.ip_network("::/128"),            # Unspecified
    ipaddress.ip_network("::1/128"),           # Loopback
    ipaddress.ip_network("::ffff:0:0/96"),     # IPv4-mapped IPv6
    ipaddress.ip_network("100::/64"),          # Discard prefix
    ipaddress.ip_network("2001:db8::/32"),     # Documentation
    ipaddress.ip_network("fc00::/7"),          # Unique local address (ULA)
    ipaddress.ip_network("fe80::/10"),         # Link-local
    ipaddress.ip_network("ff00::/8"),          # Multicast
]

BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "ip6-loopback",
    "instance-data",
    "metadata.google.internal",
}


def is_ip_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if an IP address belongs to any blocked or private/reserved range."""
    # Built-in standard checks
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        return True

    # Check against explicit blocked networks (e.g., metadata, CGNAT)
    for network in BLOCKED_IP_NETWORKS:
        if ip in network:
            return True

    return False


def validate_and_sanitize_url(url: str, resolve_dns: bool = True) -> Tuple[str, List[str]]:
    """
    Validate URL structure and enforce comprehensive SSRF protection.
    
    Returns:
        Tuple of (clean_normalized_url, list_of_resolved_ip_addresses)
        
    Raises:
        URLValidationError: For syntax, unsupported schemes, or missing hosts.
        SSRFValidationError: For blocked IP addresses, loopback, or cloud metadata.
    """
    if not url or not isinstance(url, str):
        raise URLValidationError("URL parameter must be a non-empty string.")

    url_clean = url.strip()
    if not url_clean:
        raise URLValidationError("URL cannot be empty.")

    try:
        parsed = urlsplit(url_clean)
    except Exception as exc:
        raise URLValidationError(f"Invalid URL format: {exc}")

    # Validate scheme
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise URLValidationError(
            f"Unsupported scheme '{scheme}'. Only 'http' and 'https' are allowed."
        )

    # Validate hostname presence
    hostname = parsed.hostname
    if not hostname:
        raise URLValidationError("URL is missing a valid hostname.")

    hostname_lower = hostname.lower()

    # Block well-known internal hostnames and suffix patterns
    if hostname_lower in BLOCKED_HOSTNAMES:
        raise SSRFValidationError(
            f"SSRF Protection: Access to internal host '{hostname}' is blocked."
        )

    if (
        hostname_lower.endswith(".localhost")
        or hostname_lower.endswith(".local")
        or hostname_lower.endswith(".internal")
    ):
        raise SSRFValidationError(
            f"SSRF Protection: Access to internal domain '{hostname}' is blocked."
        )

    # Check if host is a direct IP literal
    direct_ip = None
    try:
        direct_ip = ipaddress.ip_address(hostname_lower)
    except (ValueError, TypeError):
        pass

    if direct_ip is not None:
        if is_ip_blocked(direct_ip):
            raise SSRFValidationError(
                f"SSRF Protection: Access to IP address '{direct_ip}' is blocked."
            )
        return url_clean, [str(direct_ip)]

    if not resolve_dns:
        return url_clean, []

    # Resolve DNS to catch DNS rebinding or domains mapping to private/internal IPs
    resolved_ips: List[str] = []
    try:
        # Use port from URL or default for scheme
        port = parsed.port or (443 if scheme == "https" else 80)
        addr_info = socket.getaddrinfo(hostname_lower, port, proto=socket.IPPROTO_TCP)
        
        for entry in addr_info:
            sockaddr = entry[4]
            ip_str = sockaddr[0]
            resolved_ips.append(ip_str)
            try:
                ip_obj = ipaddress.ip_address(ip_str)
                if is_ip_blocked(ip_obj):
                    raise SSRFValidationError(
                        f"SSRF Protection: Domain '{hostname}' resolves to blocked IP address '{ip_str}'."
                    )
            except ValueError:
                continue

    except socket.gaierror as e:
        raise URLValidationError(f"Unable to resolve domain '{hostname}': {e.strerror}")
    except socket.herror as e:
        raise URLValidationError(f"Host error resolving '{hostname}': {e.strerror}")
    except SSRFValidationError:
        raise
    except Exception as e:
        raise URLValidationError(f"Failed to resolve host '{hostname}': {e}")

    if not resolved_ips:
        raise URLValidationError(f"No IP addresses could be resolved for '{hostname}'.")

    return url_clean, resolved_ips
