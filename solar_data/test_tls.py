# test_tls.py - Force TLS 1.2 and test NREL API
import sys
sys.stdout.reconfigure(encoding='utf-8')
import ssl
import socket
import json

# Force TLS 1.2
ctx = ssl.create_default_context()
ctx.minimum_version = ssl.TLSVersion.TLSv1_2
ctx.maximum_version = ssl.TLSVersion.TLSv1_2

print(f"SSL version: {ssl.OPENSSL_VERSION}")
print(f"Python SSL default min: {ssl.create_default_context().minimum_version}")

# Test raw socket connection
print("\nTest 1: Raw socket to developer.nrel.gov:443")
try:
    sock = socket.create_connection(("developer.nrel.gov", 443), timeout=15)
    ssock = ctx.wrap_socket(sock, server_hostname="developer.nrel.gov")
    print(f"  TLS connected: {ssock.version()}")
    ssock.close()
except Exception as e:
    print(f"  Error: {type(e).__name__}: {e}")

# Test with urllib
print("\nTest 2: urllib with custom SSL context")
try:
    import urllib.request
    url = "https://developer.nrel.gov/api/solar/solar_resource/v1.json?api_key=QfH6aBgNoDFOMjxbA4NIBnk1o2NeRBO1nQO21Rb9&lat=42.3601&lon=-71.0589"
    req = urllib.request.Request(url)
    resp = urllib.request.urlopen(req, context=ctx, timeout=30)
    data = resp.read().decode()
    print(f"  Status: {resp.status}")
    print(f"  Body: {data[:300]}")
except Exception as e:
    print(f"  Error: {type(e).__name__}: {e}")

# Test with httpx
print("\nTest 3: try httpx")
try:
    import httpx
    client = httpx.Client(verify=False, timeout=30)
    url = "https://developer.nrel.gov/api/solar/solar_resource/v1.json?api_key=QfH6aBgNoDFOMjxbA4NIBnk1o2NeRBO1nQO21Rb9&lat=42.3601&lon=-71.0589"
    resp = client.get(url)
    print(f"  Status: {resp.status_code}")
    print(f"  Body: {resp.text[:300]}")
    client.close()
except ImportError:
    print("  httpx not installed, trying to install...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "httpx", "-q"])
    import httpx
    client = httpx.Client(verify=False, timeout=30)
    url = "https://developer.nrel.gov/api/solar/solar_resource/v1.json?api_key=QfH6aBgNoDFOMjxbA4NIBnk1o2NeRBO1nQO21Rb9&lat=42.3601&lon=-71.0589"
    resp = client.get(url)
    print(f"  Status: {resp.status_code}")
    print(f"  Body: {resp.text[:300]}")
    client.close()
except Exception as e:
    print(f"  Error: {type(e).__name__}: {e}")

# Test general HTTPS connectivity
print("\nTest 4: General HTTPS test (google.com)")
try:
    import requests
    r = requests.get("https://httpbin.org/get", timeout=10, verify=False)
    print(f"  httpbin.org Status: {r.status_code}")
except Exception as e:
    print(f"  httpbin.org Error: {e}")

try:
    r = requests.get("https://api.open-meteo.com/v1/forecast?latitude=42.36&longitude=-71.06&current=temperature_2m", timeout=10)
    print(f"  open-meteo.com Status: {r.status_code}")
except Exception as e:
    print(f"  open-meteo.com Error: {e}")
