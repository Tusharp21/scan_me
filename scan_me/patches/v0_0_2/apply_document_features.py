import frappe

SIG_TYPE_PDF = {"Cryptographic (PAdES)", "Both"}


def _flag(settings_field):
	"""Global toggle value; a missing value counts as on, like the old runtime code."""
	value = frappe.db.get_single_value("Scan Me Settings", settings_field)
	return 1 if value in (None, 1, "1", True) else 0


def _removed_signature_type(pades_on):
	"""The old Signature Type setting. The field has been removed from the DocType, so
	read tabSingles directly; when it was never stored, use what the old patch chose."""
	value = frappe.db.sql(
		"select value from `tabSingles` where doctype = 'Scan Me Settings' and field = 'signature_type'"
	)
	if value and value[0][0]:
		return value[0][0]
	return "Both" if pades_on else "Visual Block"


def execute():
	"""Fill Signing Mode, Advanced Print and Document Marks on existing allowlist rows.

	Behaviour is preserved: before these columns existed, the row's `enable` flag
	gated both signing and Advanced Print, and the global toggles applied to every
	row. `enable` and `signature_type` are no longer DocType fields, so both are read
	straight from the database.

	A row counts as not migrated when Signing Mode is empty, or "None" (the column
	default) while `enable` is still on. Rows already set up in the UI are left alone."""
	if not frappe.db.exists("DocType", "Scan Me Settings"):
		return
	if not frappe.db.has_column("Scan Me Doctype", "allow_document_marks"):
		return
	if not frappe.db.has_column("Scan Me Doctype", "enable"):
		return  # fresh install, nothing to migrate

	show_copies = _flag("show_copies_section")
	show_qr = _flag("show_qr_section")
	show_signature = _flag("show_signature_section")
	pades_on = frappe.db.get_single_value("Scan Me Settings", "enable_pades_signing") in (1, "1", True)
	sig_type = _removed_signature_type(pades_on)
	watermark_on = (
		frappe.db.get_single_value("Scan Me Settings", "watermark_mode") or "Disabled"
	) != "Disabled"

	# Marks on if any of QR, copies, signature stamp or watermark was available before.
	marks = 1 if (show_qr or show_copies or show_signature or watermark_on) else 0

	rows = frappe.db.sql(
		"select name, `enable`, signing_mode from `tabScan Me Doctype` where parenttype = 'Scan Me Settings'",
		as_dict=True,
	)
	for row in rows:
		enabled = 1 if row.enable else 0
		if row.signing_mode and not (row.signing_mode == "None" and enabled):
			continue

		pdf_signature = pades_on and show_signature and sig_type in SIG_TYPE_PDF
		if not enabled:
			mode = "None"
		elif pdf_signature:
			mode = "Verified QR + PDF signature"
		else:
			mode = "Verified QR"

		frappe.db.set_value(
			"Scan Me Doctype",
			row.name,
			{"signing_mode": mode, "allow_advanced_print": enabled, "allow_document_marks": marks},
			update_modified=False,
		)
	frappe.db.commit()
