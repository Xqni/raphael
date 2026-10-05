import pytest

# Simulating the logic often found in supervisor for IP resolution
def simulate_wsl_ip_parse(output):
    """Mock of the supervisor's hostname -I parsing logic."""
    if not output:
        return None
    # Usually returns "172.x.x.x 192.x.x.x"
    parts = output.strip().split()
    return parts[0] if parts else None

def test_wsl_ip_parse_success():
    output = "172.21.10.5 192.168.1.10\n"
    assert simulate_wsl_ip_parse(output) == "172.21.10.5"

def test_wsl_ip_parse_empty():
    assert simulate_wsl_ip_parse("") is None
    assert simulate_wsl_ip_parse("   \n") is None

def test_wsl_ip_parse_single():
    assert simulate_wsl_ip_parse("172.21.10.5") == "172.21.10.5"
