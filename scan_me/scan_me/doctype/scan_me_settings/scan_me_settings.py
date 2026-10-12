# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from scan_me.utils.verification import QR_MODES, get_doctype_features, get_print_doctypes


def _normalize_row(row):
	"""Keep a row's feature flags consistent; returns a list of human-readable fixes."""
	fixes = []

	if not row.signing_mode:
		row.signing_mode = "None"

	# PDF signing happens on the Advanced Print page, so it needs Advanced Print.
	if not row.allow_advanced_print:
		if row.signing_mode == "Verified QR + PDF signature":
			row.signing_mode = "Verified QR"
			fixes.append(
				frappe._("{0}: PDF signature needs Advanced Print, switched to Verified QR.").format(
					row.ref_doctype
				)
			)
		elif row.signing_mode == "PDF signature only":
			row.signing_mode = "None"
			fixes.append(
				frappe._("{0}: PDF signature needs Advanced Print, switched to None.").format(row.ref_doctype)
			)

	# A signature image only makes sense with a Verified QR.
	if row.signing_mode not in QR_MODES:
		row.signature_required = 0
	return fixes


class ScanMeSettings(Document):
	def validate(self):
		fixes = []
		# Per-row checks here: Frappe doesn't call child validate() on parent save.
		for row in self.get("ref_doctype_info") or []:
			if not row.ref_doctype:
				continue
			fixes.extend(_normalize_row(row))
			meta = frappe.get_meta(row.ref_doctype)
			if getattr(meta, "issingle", 0):
				frappe.throw(
					frappe._(
						"'{0}' is a Single doctype and can't be signed — pick a doctype with individual records."
					).format(row.ref_doctype)
				)
			if getattr(meta, "istable", 0):
				frappe.throw(
					frappe._(
						"'{0}' is a child table and can't be signed on its own — pick the parent doctype instead."
					).format(row.ref_doctype)
				)
		if fixes:
			frappe.msgprint(
				"<br>".join(fixes),
				title=frappe._("Settings adjusted"),
				indicator="orange",
				alert=True,
			)


def _user_allowed_doctypes():
	"""Signable doctypes filtered by caller's write perm — prevents low-role enumeration of privileged targets."""
	from scan_me.utils.verification import get_allowed_doctypes

	return [dt for dt in sorted(get_allowed_doctypes()) if frappe.has_permission(dt, "write")]


def _user_print_doctypes():
	"""Advanced Print doctypes filtered by caller's print perm."""
	return [dt for dt in sorted(get_print_doctypes()) if frappe.has_permission(dt, "print")]


@frappe.whitelist(allow_guest=False)
def get_allowed_doctypes():
	"""Get the subset of allowlisted doctypes the caller can actually sign."""
	return _user_allowed_doctypes()


@frappe.whitelist(allow_guest=False)
def get_form_integration():
	"""Form-JS payload: allowlist + button visibility; one call avoids 2 round trips per refresh."""
	settings = frappe.get_single("Scan Me Settings")
	# Default on for older installs missing the field.
	show = settings.get("enable_advanced_print_button") in (None, 1, "1", True)
	return {
		# The Advanced Print icon: doctypes with Advanced Print on that the user may print.
		"allowed_doctypes": _user_print_doctypes(),
		"show_advanced_print_button": 1 if show else 0,
	}


@frappe.whitelist(allow_guest=False)
def get_print_defaults(doctype):
	"""Default Print Format + Letter Head for a doctype; gated by print perm to block enumeration."""
	if not frappe.db.exists("DocType", doctype):
		frappe.throw(
			frappe._("DocType {0} does not exist.").format(doctype),
			frappe.DoesNotExistError,
		)
	if not frappe.has_permission(doctype, "print"):
		frappe.throw(
			frappe._("No permission to print '{0}'.").format(doctype),
			frappe.PermissionError,
		)
	pf = frappe.db.get_value("DocType", doctype, "default_print_format") or "Standard"
	lh = (
		frappe.db.get_value(
			"Letter Head",
			{"is_default": 1, "disabled": 0},
			"name",
		)
		or ""
	)
	return {"print_format": pf, "letter_head": lh}


@frappe.whitelist(allow_guest=False)
def get_dialog_settings(doctype=None, docname=None):
	"""UI flags for the print dialog. With `doctype`, the flags are narrowed to what
	that document type gets (Document Marks, Signing Mode); with `docname` it also
	reports whether that document has a Verified QR."""
	s = frappe.get_single("Scan Me Settings")

	def on(field, default_on=True):
		allowed = (None, 1, "1", True) if default_on else (1, "1", True)
		return 1 if s.get(field) in allowed else 0

	settings = {
		"show_copies": on("show_copies_section"),
		"show_header_footer": on("show_header_footer_section"),
		"show_qr": on("show_qr_section"),
		"show_signature": on("show_signature_section"),
		"show_live_preview": on("show_live_preview"),
		"signature_type": "Visual Block",
		"enable_pades_signing": on("enable_pades_signing", default_on=False),
		"watermark_mode": s.get("watermark_mode") or "Disabled",
	}
	if not doctype:
		return settings

	if not frappe.has_permission(doctype, "print"):
		frappe.throw(
			frappe._("No permission to print '{0}'.").format(doctype),
			frappe.PermissionError,
		)
	feats = get_doctype_features(doctype)
	marks = feats["document_marks"]
	# Document Marks group: QR, watermark, copies, signature card.
	settings["show_copies"] = 1 if (settings["show_copies"] and marks) else 0
	settings["show_qr"] = 1 if (settings["show_qr"] and marks) else 0
	if not marks:
		settings["watermark_mode"] = "Disabled"

	# What "Apply Signature" does. A document type signed with the certificate gets
	# the invisible PDF signature only; the on-page signature card is for the plain
	# "Verified QR" mode (and needs Document Marks).
	visual = bool(feats["signing_mode"] == "Verified QR" and marks)
	pades = bool(feats["pdf_signature"] and settings["enable_pades_signing"])
	settings["signature_type"] = "Cryptographic (PAdES)" if pades else "Visual Block"
	if not (visual or pades):
		settings["show_signature"] = 0
	settings["signing_mode"] = feats["signing_mode"]
	settings["document_signed"] = bool(
		docname
		and frappe.has_permission(doctype, "print", docname)
		and frappe.db.exists("Verified QR", {"ref_doctype": doctype, "ref_docname": docname})
	)
	return settings
