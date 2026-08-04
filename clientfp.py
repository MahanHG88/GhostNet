"""
clientfp — protocol-agnostic client fingerprinting for the GhostNet honeypot.

WHY THIS EXISTS
---------------
`honeypot.calculate_tls_fingerprints()` only produces JA3/JA4 for a TLS ClientHello
(first byte 0x16, handshake type 0x01). Everything else — plaintext HTTP, SSH, RDP,
raw scanner probes — returned (None, None), so ~96% of captured attacks had no
identity beyond an IP address. An attacker who rotates IPs or VPN exits defeated the
blocklist completely.

This module derives a stable identity from *how a client speaks* rather than *where it
connects from*, for the non-TLS protocols. It deliberately uses only traits that are a
property of the attacker's tooling:

  - No IP addresses      (rotated trivially)
  - No MAC addresses     (spoofed trivially, and not visible past the first router)
  - No cookies/session   (attacker controls them)

WHAT IS ACTUALLY STABLE
-----------------------
Client software betrays itself through structure, not content:

  HTTP  Header ORDER is emitted by the client library's own code path and is highly
        distinctive (curl, python-requests, Go net/http, nmap NSE and browsers each
        have a signature order). Header NAME CASING ("User-Agent" vs "user-agent"),
        the HTTP version, whether CRLF or bare LF is used, and which optional headers
        appear at all are all library-level traits. A User-Agent string is trivially
        spoofable, so it is hashed as a SEPARATE, weaker component — never the core.

  SSH   The version banner ("SSH-2.0-libssh2_1.11.1") names the client library and
        build. Attackers rarely change it because it is baked into the library.

  RDP   The X.224 connection request shape — PDU length, the mstshash cookie form,
        and the requested security protocol flags — varies by tool.

  OTHER Structural shape of the first packet: length bucket, leading byte signature,
        byte-class histogram, line endings. Weak alone, useful as a correlator.

FALSE POSITIVES ARE THE REAL RISK
---------------------------------
These fingerprints feed an automatic ban and are sold on via the threat-intel API, so a
fingerprint that is too generic would blocklist innocent traffic and poison customer
data. Every result therefore carries a `specificity` score, and `is_bannable()` refuses
anything below MIN_BANNABLE_SPECIFICITY. A bare "GET / HTTP/1.0" with no headers — which
an uptime monitor might legitimately send — scores too low to ever be auto-banned.

Fingerprint strings are namespaced by a family prefix ("h4h_", "sshc_", "rdpc_",
"gsig_") so they can live in the same flat banned_fingerprints.json list as the existing
JA3 (32 hex chars) and JA4 (t13..._..._...) values without any chance of collision.
"""

import hashlib
import re

# A fingerprint must score at least this to be eligible for an automatic ban.
# Below it the signature is considered too generic to attribute to one actor.
MIN_BANNABLE_SPECIFICITY = 3

# Headers whose PRESENCE and ORDER are meaningful. Values are ignored (attacker-controlled)
# except where noted, so this stays a fingerprint of the client, not of the request.
_HTTP_METHOD_RE = re.compile(
    rb"^([A-Z]{3,10}) +(\S+) +HTTP/(\d\.\d)\r?\n", re.IGNORECASE
)


def _sha(text, n=12):
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:n]


def _byte_class_profile(raw):
    """Coarse histogram of byte classes — a shape signature for opaque binary probes."""
    if not raw:
        return "0-0-0"
    printable = sum(1 for b in raw if 0x20 <= b < 0x7F)
    control = sum(1 for b in raw if b < 0x20)
    high = len(raw) - printable - control
    total = len(raw)
    # bucket to tenths so small payload variations don't change the fingerprint
    return "%d-%d-%d" % (
        printable * 10 // total,
        control * 10 // total,
        high * 10 // total,
    )


def _len_bucket(n):
    """Exponential length buckets — resilient to a few bytes of variation."""
    for edge in (0, 8, 16, 32, 64, 128, 256, 512, 1024, 2048):
        if n <= edge:
            return edge
    return 4096


def _fingerprint_http(raw):
    m = _HTTP_METHOD_RE.match(raw)
    if not m:
        return None

    method = m.group(1).decode("ascii", "ignore").upper()
    target = m.group(2).decode("ascii", "ignore")
    version = m.group(3).decode("ascii", "ignore")

    # Line endings are a library trait: compliant clients send CRLF, many hand-rolled
    # scanners and Go-based tools send bare LF.
    head = raw.split(b"\r\n\r\n", 1)[0].split(b"\n\n", 1)[0]
    crlf = "c" if b"\r\n" in head else "l"

    lines = head.replace(b"\r\n", b"\n").split(b"\n")[1:]
    names_raw, names_lower = [], []
    for line in lines:
        if not line.strip() or b":" not in line:
            continue
        name = line.split(b":", 1)[0].decode("ascii", "ignore").strip()
        if not name:
            continue
        names_raw.append(name)
        names_lower.append(name.lower())

    # Casing pattern: T=Title-Case, l=lowercase, U=UPPERCASE, m=mixed/other.
    casing = ""
    for n in names_raw:
        if n.islower():
            casing += "l"
        elif n.isupper():
            casing += "U"
        elif n == n.title() or all(p[:1].isupper() for p in n.split("-") if p):
            casing += "T"
        else:
            casing += "m"

    order_hash = _sha(",".join(names_lower), 12)
    casing_hash = _sha(casing, 6)

    # Space after the colon is another library-level quirk.
    spacing = "s" if b": " in head else "n"
    # Absolute-URI in the request line means the client is talking proxy-style.
    absuri = "a" if target.lower().startswith("http") else "r"

    # The User-Agent is the ONE header an attacker rotates casually, so it is recorded
    # for reporting but deliberately excluded from the fingerprint itself. Changing only
    # the UA therefore buys no evasion — the order/casing/shape core is unchanged.
    ua = ""
    accept_encoding = ""
    connection_val = ""
    for line in lines:
        low = line.lower()
        if low.startswith(b"user-agent:"):
            ua = line.split(b":", 1)[1].decode("utf-8", "ignore").strip()
        elif low.startswith(b"accept-encoding:"):
            accept_encoding = line.split(b":", 1)[1].decode("ascii", "ignore").strip()
        elif low.startswith(b"connection:"):
            connection_val = line.split(b":", 1)[1].decode("ascii", "ignore").strip()

    legacy_fp = "h4h_%s%s%s%s%s_%d_%s_%s" % (
        version.replace(".", ""), method[:4].lower(), crlf, spacing, absuri,
        len(names_lower), order_hash, casing_hash,
    )
    fp = legacy_fp
    if accept_encoding or connection_val:
        # These are library-DEFAULT values (curl/requests/Go each ship their own
        # Accept-Encoding/Connection defaults) - not attacker-controlled the way
        # User-Agent is, so folding them in raises specificity without the false-
        # positive risk the UA carries. Only appended when present so a client that
        # sends neither header still gets the exact legacy fp (nothing lost).
        extra_hash = _sha(f"{accept_encoding}|{connection_val}", 8)
        fp = f"{legacy_fp}_{extra_hash}"

    # Specificity: how much distinguishing evidence did the client give us, counting
    # only UA-independent traits (the UA is excluded from the fingerprint above).
    spec = 0
    if len(names_lower) >= 2:
        spec += 1
    if len(names_lower) >= 4:
        spec += 1
    if len(names_lower) >= 7:
        spec += 1
    if len(set(casing)) > 1:      # inconsistent casing is a strong hand-rolled-tool tell
        spec += 1
    if crlf == "l":               # non-compliant line endings are unusual and telling
        spec += 1
    if absuri == "a":
        spec += 1
    if method not in ("GET", "POST", "HEAD"):
        spec += 1                 # exotic verbs (PROPFIND, OPTIONS probes) are tool tells
    if accept_encoding:
        spec += 1

    return {
        "fp": fp,
        "legacy_fp": legacy_fp,
        "family": "http",
        "specificity": spec,
        "detail": {
            "method": method,
            "http_version": version,
            "header_count": len(names_lower),
            "header_order": ",".join(names_lower[:12]),
            "casing_pattern": casing[:24],
            "line_ending": "LF" if crlf == "l" else "CRLF",
            "user_agent": ua[:120],
            "accept_encoding": accept_encoding[:60],
            "connection": connection_val[:30],
        },
    }


def _parse_ssh_kexinit(raw, after_banner_offset):
    """Opportunistically parse the client's SSH_MSG_KEXINIT (RFC 4253 7.1) when it was
    buffered along with the version banner - many SSH clients pipeline both without
    waiting for the server's reply. Returns the 10 name-lists in spec order, or None if
    not present/parseable (client is waiting for our banner first; falls back to the
    banner-only fingerprint below, nothing lost)."""
    data = raw[after_banner_offset:]
    if len(data) < 6:
        return None
    pkt_len = int.from_bytes(data[0:4], "big")
    if pkt_len <= 0 or len(data) < 4 + pkt_len:
        return None
    pad_len = data[4]
    if pad_len + 1 > pkt_len:
        return None
    payload = data[5:5 + pkt_len - pad_len - 1]
    if not payload or payload[0] != 20:  # SSH_MSG_KEXINIT
        return None
    pos = 1 + 16  # msg code + 16-byte cookie
    names = []
    for _ in range(10):
        if pos + 4 > len(payload):
            return None
        nlen = int.from_bytes(payload[pos:pos+4], "big")
        pos += 4
        if pos + nlen > len(payload):
            return None
        names.append(payload[pos:pos+nlen].decode("ascii", "ignore"))
        pos += nlen
    return names


def _fingerprint_ssh(raw):
    if not raw.startswith(b"SSH-"):
        return None
    line_end = raw.find(b"\n")
    banner_line = raw if line_end == -1 else raw[:line_end + 1]
    banner = banner_line.strip().decode("ascii", "ignore")
    parts = banner.split("-", 2)
    proto = parts[1] if len(parts) > 2 else "?"
    software = parts[2] if len(parts) > 2 else ""
    # Split "OpenSSH_8.9p1 Debian-3" into product and comment
    softid = software.split(" ", 1)[0]
    comment = software.split(" ", 1)[1] if " " in software else ""

    legacy_fp = "sshc_%s_%s_%s" % (proto.replace(".", ""), _sha(softid, 10), _sha(comment, 4))
    fp = legacy_fp

    spec = 2  # a client banner is already a real tool identifier
    if softid:
        spec += 1
    if comment:
        spec += 1
    if not raw.endswith(b"\r\n") and raw.rstrip().endswith(softid.encode(errors="ignore")):
        spec += 1  # missing CRLF terminator — hand-rolled client

    # HASSH-style hardening: if the client's KEXINIT (algorithm negotiation) was
    # buffered too, hash its kex/encryption/mac/compression algorithm lists. This is a
    # far deeper trait than the banner string - patching a client to lie about its
    # banner is trivial; changing which crypto algorithms it offers, in what order,
    # means actually reconfiguring or rebuilding the SSH library.
    hassh = None
    kex_names = _parse_ssh_kexinit(raw, line_end + 1) if line_end != -1 else None
    if kex_names:
        kex, host_key, enc_c2s, enc_s2c, mac_c2s, mac_s2c, comp_c2s, comp_s2c, lang_c2s, lang_s2c = kex_names
        hassh_input = ";".join([kex, enc_c2s, mac_c2s, comp_c2s])
        hassh = hashlib.md5(hassh_input.encode("utf-8", "ignore")).hexdigest()
        fp = f"{legacy_fp}_h{hassh[:10]}"
        spec += 3

    detail = {
        "banner": banner[:120],
        "protocol": proto,
        "software": softid,
        "comment": comment[:60],
    }
    if hassh:
        detail["hassh"] = hassh
        detail["kex_algorithms"] = kex_names[0][:200]

    return {
        "fp": fp,
        "legacy_fp": legacy_fp,
        "family": "ssh",
        "specificity": spec,
        "detail": detail,
    }


def _fingerprint_rdp(raw):
    # X.224 / TPKT connection request: version 3, reserved 0.
    if len(raw) < 11 or raw[0] != 0x03 or raw[1] != 0x00:
        return None
    tpkt_len = int.from_bytes(raw[2:4], "big")
    x224_len = raw[4]
    body = raw[5:]

    cookie = ""
    m = re.search(rb"Cookie:\s*mstshash=([^\r\n]*)", raw)
    if m:
        cookie = m.group(1).decode("ascii", "ignore")

    # The RDP negotiation request trailer advertises which security protocols the
    # client supports — a real per-tool trait.
    neg = ""
    ni = raw.find(b"\x01\x00\x08\x00")
    if ni != -1 and len(raw) >= ni + 8:
        neg = raw[ni:ni + 8].hex()

    # The cookie VALUE is attacker-chosen; its SHAPE (length, charset) is tool-driven.
    shape = "%d%s" % (
        len(cookie),
        "a" if cookie.isalpha() else ("n" if cookie.isdigit() else "m"),
    )

    fp = "rdpc_%d_%d_%s_%s" % (tpkt_len, x224_len, shape, _sha(neg, 8))

    spec = 2
    if neg:
        spec += 1
    if cookie:
        spec += 1
    return {
        "fp": fp,
        "family": "rdp",
        "specificity": spec,
        "detail": {
            "tpkt_length": tpkt_len,
            "x224_length": x224_len,
            "cookie": cookie[:60],
            "cookie_shape": shape,
            "negotiation": neg,
        },
    }


def _fingerprint_generic(raw):
    """Structural shape for opaque probes (scanner beacons, raw binary, empty)."""
    if not raw:
        return {
            "fp": "gsig_empty",
            "family": "generic",
            "specificity": 0,
            "detail": {"note": "client connected but sent nothing"},
        }

    head_sig = raw[:4].hex()
    profile = _byte_class_profile(raw)
    bucket = _len_bucket(len(raw))
    lines = raw.count(b"\n")
    printable_prefix = ""
    try:
        printable_prefix = raw[:32].decode("ascii", "ignore")
        printable_prefix = "".join(c for c in printable_prefix if c.isprintable())
    except Exception:
        pass

    # For printable beacons (e.g. scanner hello strings) the literal token is the
    # strongest signal; strip embedded IP/port so the same probe to a different host
    # still collides.
    token = re.sub(r"\d+\.\d+\.\d+\.\d+", "<ip>", printable_prefix)
    token = re.sub(r"[:_]\d{2,5}\b", "<port>", token)

    fp = "gsig_%s_%d_%s_%s" % (head_sig, bucket, profile, _sha(token, 10))

    spec = 0
    if len(token) >= 6:
        spec += 2          # a stable printable beacon string is quite identifying
    if len(raw) >= 16:
        spec += 1
    if lines > 1:
        spec += 1
    return {
        "fp": fp,
        "family": "generic",
        "specificity": spec,
        "detail": {
            "head_bytes": head_sig,
            "length": len(raw),
            "byte_profile": profile,
            "token": token[:60],
        },
    }


def fingerprint(raw):
    """
    Fingerprint a client from the first bytes it sent.

    Returns a dict: {fp, family, specificity, detail}. Never raises — a honeypot must
    not die on malformed attacker input, so any parsing failure degrades to the generic
    structural fingerprint.
    """
    if raw is None:
        raw = b""
    if isinstance(raw, str):
        raw = raw.encode("utf-8", errors="ignore")

    for parser in (_fingerprint_http, _fingerprint_ssh, _fingerprint_rdp):
        try:
            result = parser(raw)
        except Exception:
            result = None
        if result:
            return result

    try:
        return _fingerprint_generic(raw)
    except Exception:
        return {
            "fp": "gsig_unparsed",
            "family": "generic",
            "specificity": 0,
            "detail": {},
        }


def is_bannable(result):
    """
    Whether a fingerprint is specific enough to auto-ban on.

    Guards the blocklist against generic signatures that legitimate clients could also
    produce — these bans are sold on via the threat-intel API, so a false positive is
    worse than a miss.
    """
    if not result:
        return False
    if result.get("fp", "").startswith("gsig_empty"):
        return False
    return result.get("specificity", 0) >= MIN_BANNABLE_SPECIFICITY


def describe(result):
    """Short human-readable label for logs, Telegram alerts and the dashboard."""
    if not result:
        return "-"
    fam = result.get("family", "?")
    d = result.get("detail", {})
    if fam == "http":
        return "HTTP %s %s, %d hdrs, %s" % (
            d.get("method", "?"), d.get("http_version", "?"),
            d.get("header_count", 0), d.get("line_ending", "?"),
        )
    if fam == "ssh":
        return "SSH client %s" % (d.get("software") or d.get("banner", "?"))
    if fam == "rdp":
        return "RDP cookie=%s" % (d.get("cookie") or "-")
    return "probe %s (%dB)" % (d.get("token") or d.get("head_bytes", "?"), d.get("length", 0))
