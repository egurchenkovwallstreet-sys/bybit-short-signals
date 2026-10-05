"""Точка входа: python -m ws_server"""

import logging

import config
import uvicorn


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    uvicorn.run(
        "ws_server.app:app",
        host=config.WEB_HOST,
        port=config.WEB_PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
