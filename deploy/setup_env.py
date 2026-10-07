"""Create server-only credentials interactively; never print or overwrite secrets."""
from getpass import getpass
from pathlib import Path
import os
import secrets


def dotenv_value(value):
    if any(char in value for char in "\r\n\0"):
        raise ValueError("A setting must be a single line.")
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def main():
    target = Path(__file__).resolve().parent.parent / ".env"
    if target.exists():
        raise SystemExit(".env already exists; kept unchanged.")
    username = input("ISO-NE account/email: ").strip()
    password = getpass("ISO-NE password (hidden): ")
    if not username or not password:
        raise SystemExit("Account and password are required; no file created.")
    settings = {
        "MYSQL_DATABASE": "OOOO",
        "MYSQL_USER": "smartgrid",
        "MYSQL_ROOT_PASSWORD": secrets.token_hex(32),
        "MYSQL_PASSWORD": secrets.token_hex(32),
        "AUTH_JWT_SECRET_KEY": secrets.token_hex(32),
        "ISO_NE_USERNAME": username,
        "ISO_NE_PASSWORD": password,
        "EIA_API_KEY": "",
    }
    content = "".join(f"{key}={dotenv_value(value)}\n" for key, value in settings.items())
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(content)
    print("Server .env created. Credentials are saved locally, not printed.")


if __name__ == "__main__":
    main()
