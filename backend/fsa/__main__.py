"""Run the API: python3 -m backend.fsa [--host 127.0.0.1] [--port 8000]."""
import argparse

import uvicorn


def main():
    p = argparse.ArgumentParser(description="Flight Safety Command API")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    a = p.parse_args()
    uvicorn.run("backend.fsa.api:app_factory", factory=True, host=a.host, port=a.port)


if __name__ == "__main__":
    main()
