import copy
import ipaddress


def fix_ip_format(axon):
    """Wrap bare IPv6 addresses in brackets so httpx can connect to them."""
    ax = copy.copy(axon)
    ip = ax.ip.strip()
    if not (ip.startswith("[") and ip.endswith("]")):
        try:
            if ipaddress.ip_address(ip).version == 6:
                ax.ip = f"[{ip}]"
        except ValueError:
            pass
    return ax
