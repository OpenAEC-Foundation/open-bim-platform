app_name = "openaec_bim"
app_title = "OpenAEC BIM"
app_publisher = "OpenAEC Foundation"
app_description = "Open BIM Platform: modelmappen in OpenAEC Storage omzetten en tonen in de werkplek"
app_email = "openaecstudio@gmail.com"
# De projectlicentie van open-bim-platform is nog niet gekozen (besluit van de eigenaar).
app_license = "NOASSERTION"

required_apps = ["frappe", "openaec_storage"]

# Elke wijziging aan projecten, issues, standpunten, reacties en botsingen komt in het auditlog (openaec_bim.audit).
_audit = {
	"after_insert": "openaec_bim.audit.aangemaakt",
	"on_update": "openaec_bim.audit.gewijzigd",
	"on_trash": "openaec_bim.audit.verwijderd",
}
doc_events = {
	doctype: _audit
	for doctype in ("BIM Project", "BIM Issue", "BIM Standpunt", "BIM Reactie", "BIM Botsingsronde", "BIM Botsing")
}

# Lopende omzettingen bij de kern volgen, ook als niemand het project open heeft.
scheduler_events = {"cron": {"* * * * *": ["openaec_bim.afgeleid.volg_lopende"]}}

# De BCF-API 3.0 en de Foundation API (/bcf/3.0/..., /foundation/...): alle methoden, ook PUT en DELETE, die
# Frappe buiten /api/ niet naar een paginarenderer stuurt (openaec_bim.bcf_api.renderer).
before_request = ["openaec_bim.bcf_api.renderer.voor_verzoek"]
