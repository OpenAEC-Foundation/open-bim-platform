app_name = "openaec_bim"
app_title = "OpenAEC BIM"
app_publisher = "OpenAEC Foundation"
app_description = "Open BIM Platform: modelmappen in OpenAEC Storage omzetten en tonen in de werkplek"
app_email = "openaecstudio@gmail.com"
# De projectlicentie van open-bim-platform is nog niet gekozen (besluit van de eigenaar).
app_license = "NOASSERTION"

required_apps = ["frappe", "openaec_storage"]

# Lopende omzettingen bij de kern volgen, ook als niemand het project open heeft.
scheduler_events = {"cron": {"* * * * *": ["openaec_bim.afgeleid.volg_lopende"]}}
