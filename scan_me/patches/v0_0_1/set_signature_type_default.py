import frappe


def execute():
	"""No-op. This used to backfill Scan Me Settings -> signature_type, a field that
	has been replaced by the per-document-type Signing Mode. The value (if present)
	is still read by patches.v0_0_2.apply_document_features to set each row's mode."""
	return
