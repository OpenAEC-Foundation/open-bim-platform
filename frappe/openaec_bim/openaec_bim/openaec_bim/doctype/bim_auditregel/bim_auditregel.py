import frappe
from frappe import _
from frappe.model.document import Document


class BIMAuditregel(Document):
	"""Eén regel in het auditlog: wie wat wanneer deed aan een BIM-object. Een regel verandert nooit meer."""

	def validate(self):
		if not self.is_new():
			frappe.throw(_("Een auditregel kan niet gewijzigd worden."), frappe.PermissionError)

	def on_trash(self):
		frappe.throw(_("Een auditregel kan niet verwijderd worden."), frappe.PermissionError)
