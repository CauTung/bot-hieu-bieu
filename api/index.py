from http.server import BaseHTTPRequestHandler
from api.webhook import handler as WebhookHandler
from api.check_reminders import handler as CheckRemindersHandler

class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if "/api/webhook" in self.path:
            WebhookHandler.do_POST(self)
        elif "/api/check_reminders" in self.path or "/api/check-reminders" in self.path:
            CheckRemindersHandler.do_POST(self)
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self) -> None:
        if "/api/check_reminders" in self.path or "/api/check-reminders" in self.path:
            CheckRemindersHandler.do_GET(self)
        else:
            self.send_response(404)
            self.end_headers()
