import base64
import secrets


def main() -> None:
    key = secrets.token_bytes(32)
    print(base64.b64encode(key).decode("utf-8"))


if __name__ == "__main__":
    main()

