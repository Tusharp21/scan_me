/* global QRCode */

frappe.after_ajax(() => {
	frappe.call({
		method: "scan_me.scan_me.doctype.scan_me_settings.scan_me_settings.get_allowed_doctypes",
		callback(r) {
			const allowed_doctypes = r.message || [];

			if (!allowed_doctypes.length) {
				console.warn("[Scan Me] No doctypes configured for Verified QR button.");
				return;
			}
			allowed_doctypes.forEach((dt) => {
				frappe.ui.form.on(dt, {
					refresh(frm) {
						if (!frm || frm.is_new() || !frm.doc) return;
						// Frappe clears custom buttons on every refresh (save, submit,
						// reload), so the button has to be added again each time.
						add_generate_qr_button(frm);
					},
				});
			});
		},
	});
});

function add_generate_qr_button(frm) {
	if (!frm || !frm.doctype) return;

	const label = __("Generate Verified QR");
	const docname = frm.doc.name;

	frappe.call({
		method: "scan_me.scan_me.doctype.verified_qr.verified_qr.check_button_required",
		args: { doctype: frm.doctype, docname: docname },
		callback(r) {
			if (!r.message) return;

			// The form may have moved on (another document, or already has the button).
			if (!frm.doc || frm.doc.name !== docname || frm.is_new()) return;
			if (frm.custom_buttons && frm.custom_buttons[label]) return;

			frm.add_custom_button(label, () => generate_verified_qr(frm), __("Actions")).addClass(
				"btn-primary"
			);
		},
	});
}

function generate_verified_qr(frm) {
	frappe.call({
		method: "scan_me.scan_me.doctype.verified_qr.verified_qr.check_signature_required",
		args: { doctype: frm.doctype },
		callback(r) {
			if (!r.message) return;

			const is_signature_required = r.message;
			if (is_signature_required) {
				if (frappe.session.user == "Administrator") {
					frappe.throw("Administrator cannot sign documents.");
				}

				signature_required(frm);
			} else {
				frappe.call({
					method: "scan_me.utils.generate_qr.generate_verified_qr",
					args: {
						doctype: frm.doctype,
						docname: frm.doc.name,
					},
					freeze: true,
					freeze_message: __("Generating Verified QR..."),
					callback(res) {
						const msg = res.message || {};
						frappe.msgprint({
							message: __(msg.message || "Verified QR created successfully!"),
							title: __("Verified QR"),
							indicator: msg.existing ? "orange" : "green",
						});
						frm.reload_doc();
					},
				});
			}
		},
	});
}

function signature_required(frm) {
	let d = new frappe.ui.Dialog({
		title: "Signature Required",
		fields: [
			{
				label: "Signed By",
				fieldname: "signed_by",
				fieldtype: "Link",
				options: "User",
				default: frappe.session.user,
				readonly: 1,
			},
			{
				fieldtype: "column_break",
			},
			{
				label: "Signed On",
				fieldname: "signed_on",
				fieldtype: "Date",
				readonly: 1,
				default: frappe.datetime.get_today(),
			},
			{
				fieldtype: "section_break",
			},
			{
				label: "Signature",
				fieldname: "signature",
				fieldtype: "Signature",
			},
		],
		size: "large",
		primary_action_label: "Sign QR",
		primary_action(values) {
			frappe.call({
				method: "scan_me.utils.generate_qr.generate_verified_qr",
				args: {
					doctype: frm.doctype,
					docname: frm.doc.name,
					signature_data: values.signature,
				},
				freeze: true,
				freeze_message: __("Generating Verified QR..."),
				callback(res) {
					const response = res.message || {};
					frappe.msgprint({
						message: __(response.message || "Verified QR created successfully!"),
						title: __("Verified QR"),
						indicator: response.existing ? "orange" : "green",
					});
					frm.reload_doc();
					d.hide();
				},
			});
		},
	});

	d.show();
}

function add_qr_to_description(frm, fieldname, value) {
	const field = frm.fields_dict[fieldname];
	if (!field) return;

	const $wrapper = field.$wrapper;
	if (!$wrapper?.length) return;

	let $desc = $wrapper.find(".help");
	if (!$desc.length) {
		$desc = $('<div class="help"></div>').appendTo($wrapper);
	}

	$desc.empty();

	const $qr_div = $('<div class="qr-code-box" style="margin: 10px 0;"></div>').appendTo($desc);

	new QRCode($qr_div[0], {
		text: value || __("No Value"),
		width: 120,
		height: 120,
	});
}
