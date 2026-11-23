"""Integracao com a Telegram Bot API. Credenciais SOMENTE por variaveis de ambiente."""
import os
import logging
import requests

log = logging.getLogger("monitor")


class Telegram:
    def __init__(self, token=None, chat_id=None, session=None):
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = str(chat_id or os.environ.get("TELEGRAM_CHAT_ID", ""))
        self.s = session or requests.Session()

    @property
    def enabled(self):
        return bool(self.token and self.chat_id)

    def _call(self, method, **kw):
        r = self.s.post(f"https://api.telegram.org/bot{self.token}/{method}", timeout=30, **kw)
        data = r.json() if r.content else {}
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method} falhou: {data.get('description', r.status_code)}")
        return data["result"]

    def send(self, text):
        if not self.enabled:
            log.info("[Telegram desativado] %s", text.replace("\n", " | ")[:200])
            return False
        for i in range(0, len(text), 4000):
            self._call("sendMessage", data={"chat_id": self.chat_id, "text": text[i:i + 4000],
                                            "parse_mode": "HTML", "disable_web_page_preview": "true"})
        return True

    def send_photo(self, path, caption=""):
        if not self.enabled:
            return False
        with open(path, "rb") as f:
            self._call("sendPhoto", data={"chat_id": self.chat_id, "caption": caption[:900]}, files={"photo": f})
        return True

    def updates(self, offset=None):
        if not self.enabled:
            return []
        p = {"timeout": 0, "allowed_updates": '["message"]'}
        if offset:
            p["offset"] = offset
        return self._call("getUpdates", data=p)


HELP = ("<b>Comandos</b>\n/precos – melhores ofertas e combinações agora\n/status – última execução e lojas\n"
        "/ajuda – esta mensagem\n\nOs comandos são respondidos a cada execução automática (até ~30 min).")


def handle_commands(conn, tg: Telegram, cfg, builders):
    """Processa /start /status /precos /ajuda. Responde apenas ao chat configurado."""
    from . import db
    if not tg.enabled:
        return 0
    offset = int(db.get_meta(conn, "tg_offset", 0) or 0)
    n = 0
    for u in tg.updates(offset or None):
        offset = max(offset, u["update_id"] + 1)
        m = u.get("message") or {}
        if str((m.get("chat") or {}).get("id")) != tg.chat_id:
            continue
        cmd = (m.get("text") or "").strip().split()[0].split("@")[0].lower() if m.get("text") else ""
        try:
            if cmd == "/start":
                tg.send("Olá! Monitoro PS5 e GTA 6 e aviso quando houver oferta dentro das suas metas.\n\n" + HELP)
            elif cmd == "/ajuda":
                tg.send(HELP)
            elif cmd == "/status":
                tg.send(builders["status"]())
            elif cmd == "/precos":
                tg.send(builders["precos"]())
                for p in builders.get("charts", lambda: [])():
                    tg.send_photo(p, "Evolução do menor preço (30 dias)")
            elif cmd.startswith("/"):
                tg.send("Comando desconhecido. Use /ajuda.")
            n += 1
        except Exception as e:  # um comando com erro nao derruba o resto
            log.exception("erro no comando %s: %s", cmd, e)
    db.set_meta(conn, "tg_offset", offset)
    return n
