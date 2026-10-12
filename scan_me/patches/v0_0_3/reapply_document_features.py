def execute():
	"""Run the document-feature migration once more on sites that ran an earlier,
	narrower version of it. It only touches rows that are not migrated yet."""
	from scan_me.patches.v0_0_2.apply_document_features import execute as apply_document_features

	apply_document_features()
