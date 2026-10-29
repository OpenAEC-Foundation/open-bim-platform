"""Kortlevende, ondertekende leestokens voor de delen van een omzetting: één deel, één gebruiker, een paar minuten.

De gastpagina haalt de bytes zonder cookies met `openaec_bim.api.lees?token=…` en geeft ze aan het frame (dat zelf
nooit een adres of token krijgt). Zelfde opzet als de leestokens van de werkplek.
"""

import base64
import hashlib
import hmac
import json
import time

import frappe
from frappe.utils.password import get_encryption_key

GELDIG_SECONDEN = 300


def _sleutel() -> bytes:
	return hashlib.sha256(f"openaec-bim-leestoken:{get_encryption_key()}".encode()).digest()


def _b64(data: bytes) -> str:
	return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(tekst: str) -> bytes:
	return base64.urlsafe_b64decode(tekst + "=" * (-len(tekst) % 4))


def maak(gegevens: dict) -> str:
	inhoud = _b64(json.dumps(gegevens, separators=(",", ":"), sort_keys=True).encode())
	handtekening = _b64(hmac.new(_sleutel(), inhoud.encode(), hashlib.sha256).digest())
	return f"{inhoud}.{handtekening}"


def nieuw(afgeleid: str, deel: str, gebruiker: str) -> str:
	return maak(
		{"a": afgeleid, "d": deel, "u": gebruiker, "s": frappe.local.site, "e": int(time.time()) + GELDIG_SECONDEN}
	)


def lees(token: str) -> dict:
	"""De gegevens uit een geldig token; anders PermissionError (zonder te zeggen wat er mis is)."""
	try:
		inhoud, handtekening = (token or "").split(".")
		verwacht = _b64(hmac.new(_sleutel(), inhoud.encode(), hashlib.sha256).digest())
		if not hmac.compare_digest(verwacht, handtekening):
			raise ValueError
		gegevens = json.loads(_unb64(inhoud))
	except (ValueError, TypeError):
		frappe.throw(frappe._("Deze link is ongeldig of verlopen."), frappe.PermissionError)
	if gegevens.get("s") != frappe.local.site or int(gegevens.get("e", 0)) < time.time():
		frappe.throw(frappe._("Deze link is ongeldig of verlopen."), frappe.PermissionError)
	return gegevens
