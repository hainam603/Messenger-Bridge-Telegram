from __future__ import annotations

import sys
import os
import threading
import logging
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler


HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
	sys.path.insert(0, str(HERE))

from bridge import MessengerTelegramBridge
from config import load_config
from messenger.client import MessengerClient
from store import BridgeStore
from tg.bot import build_application


class HealthHandler(BaseHTTPRequestHandler):
	def do_GET(self) -> None:
		self.send_response(200)
		self.send_header("Content-type", "text/plain; charset=utf-8")
		self.end_headers()
		self.wfile.write(b"OK")

	def log_message(self, format: str, *args: any) -> None:
		# Keep console logging quiet for requests
		pass


def start_health_server() -> None:
	port = int(os.environ.get("PORT", "8080"))
	server = HTTPServer(("0.0.0.0", port), HealthHandler)
	thread = threading.Thread(target=server.serve_forever, daemon=True)
	thread.start()
	logging.getLogger(__name__).info("Health check server listening on port %d", port)


def setup_logging(level_name: str) -> None:
	level = getattr(logging, level_name.upper(), logging.DEBUG)
	logging.basicConfig(
		level=level,
		format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
		datefmt="%Y-%m-%d %H:%M:%S",
		force=True,
	)
	logging.getLogger("httpx").setLevel(logging.WARNING)
	logging.getLogger("telegram.ext.Application").setLevel(logging.INFO)


def main() -> None:
	config = load_config()
	setup_logging(config.log_level)
	logger = logging.getLogger(__name__)
	store = BridgeStore(
		config.store_path,
		message_cache_limit=config.message_cache_limit,
	)
	messenger = MessengerClient(config)
	bridge = MessengerTelegramBridge(config, store, messenger)
	application = build_application(config, bridge, store)

	# Start background health server for Render/Koyeb
	start_health_server()

	print("+----------------------------------------+")
	print("| Messenger <-> Telegram Bridge          |")
	print("| fbchat-v2 E2EE listener/send enabled   |")
	print("+----------------------------------------+")
	logger.info("Starting bridge with LOG_LEVEL=%s data_dir=%s topics=%s", config.log_level, config.data_dir, len(store.all_topics()))
	application.run_polling(allowed_updates=["message", "message_reaction"], close_loop=False)


if __name__ == "__main__":
	main()
