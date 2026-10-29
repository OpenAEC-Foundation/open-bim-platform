from frappe.model.document import Document


class BIMIssue(Document):
	"""Een issue volgens het datamodel van BCF 3.0 (topic); de naam is de BCF-guid."""
