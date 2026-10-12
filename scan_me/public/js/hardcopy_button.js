// Adds an "Advanced Print" entry (toolbar icon + ⋮ menu item) to forms of the
// document types that have Advanced Print turned on in Scan Me Settings.
//
// Frappe rebuilds the form toolbar on every refresh, and it does so after
// Form.refresh() has returned, so anything added earlier is wiped. The
// "form-refresh" event fires after the toolbar is rebuilt, which is the only
// safe moment to add buttons. Nothing is remembered between refreshes: each time
// the entry is checked for and added again if it is missing.
//
// This file must never break a form: every path is wrapped, the settings are
// fetched without Frappe's error dialogs, and any failure just means "no button".
(function () {
	const EVENT = "form-refresh.scan_me_hardcopy";
	const TTL_MS = 60 * 1000;
	const RETRY_AFTER_FAILURE_MS = 10 * 1000;

	let cache = null; // { allowed: Set, show_button: bool, at: ms }
	let inflight = null;
	let failed_at = 0;

	function fetch_integration() {
		const now = Date.now();
		if (cache && now - cache.at < TTL_MS) return Promise.resolve(cache);
		if (inflight) return inflight;
		if (failed_at && now - failed_at < RETRY_AFTER_FAILURE_MS) return Promise.resolve(null);

		const url =
			"/api/method/scan_me.scan_me.doctype.scan_me_settings.scan_me_settings.get_form_integration";
		inflight = fetch(url, {
			credentials: "same-origin",
			headers: { Accept: "application/json" },
		})
			.then((resp) =>
				resp.ok ? resp.json() : Promise.reject(new Error("HTTP " + resp.status))
			)
			.then((body) => {
				const msg = (body && body.message) || {};
				cache = {
					allowed: new Set(msg.allowed_doctypes || []),
					show_button: !!msg.show_advanced_print_button,
					at: Date.now(),
				};
				failed_at = 0;
				return cache;
			})
			.catch(() => {
				// Not cached as "off": the next refresh simply tries again (after a pause).
				failed_at = Date.now();
				return null;
			})
			.then((result) => {
				inflight = null;
				return result;
			});
		return inflight;
	}

	function is_usable(frm) {
		return !!(
			frm &&
			frm.doctype &&
			frm.doc &&
			frm.page &&
			frm.page.wrapper &&
			!(frm.is_new && frm.is_new()) &&
			!(frm.meta && (frm.meta.istable || frm.meta.issingle))
		);
	}

	function open_print_page(frm) {
		frappe.set_route("scan-me-print", frm.doctype, frm.docname);
	}

	function ensure_menu_item(frm) {
		if (!frm.page.menu || frm.page.menu.find(".sm-hardcopy-menu").length) return;
		const $item = frm.page.add_menu_item(
			__("Advanced Print (Scan Me)"),
			() => open_print_page(frm),
			true
		);
		if ($item && $item.addClass) $item.addClass("sm-hardcopy-menu");
	}

	function find_print_button($wrapper) {
		const print_label = __("Print");
		return $wrapper
			.find(".page-actions button")
			.filter(function () {
				const t =
					this.getAttribute("data-original-title") || this.getAttribute("title") || "";
				return t === "Print" || t === print_label;
			})
			.first();
	}

	function build_button(frm) {
		const $btn = $(
			'<button class="btn btn-default icon-btn sm-hardcopy-btn" type="button"' +
				' title="' +
				__("Advanced Print (Scan Me)") +
				'">' +
				'<svg viewBox="0 0 24 24" width="14" height="14" fill="none"' +
				' stroke="currentColor" stroke-width="2" stroke-linecap="round"' +
				' stroke-linejoin="round">' +
				'<rect x="5" y="3" width="14" height="18" rx="2"></rect>' +
				'<line x1="8" y1="7" x2="16" y2="7"></line>' +
				'<line x1="8" y1="11" x2="16" y2="11"></line>' +
				'<line x1="8" y1="15" x2="12" y2="15"></line>' +
				"</svg></button>"
		);
		$btn.on("click", () => open_print_page(frm));
		return $btn;
	}

	function ensure_icon(frm) {
		const $wrapper = frm.page.wrapper;
		const $existing = $wrapper.find(".sm-hardcopy-btn");
		const $print = find_print_button($wrapper);

		if ($existing.length) {
			// Keep it right after the Print icon if that has appeared since.
			if ($print.length && !$print.next().is(".sm-hardcopy-btn")) {
				$existing.first().detach();
				$print.after($existing.first());
			}
			return;
		}

		const $btn = build_button(frm);
		if ($print.length) {
			$print.after($btn);
			return;
		}
		// Print icon not exposed (yet): fall back to the actions area.
		let $group = $wrapper.find(".page-actions .custom-actions").first();
		if (!$group.length) $group = $wrapper.find(".page-actions").first();
		if ($group.length) $group.append($btn);
	}

	function remove_entry(frm) {
		frm.page.wrapper.find(".sm-hardcopy-btn").remove();
		if (frm.page.menu) frm.page.menu.find(".sm-hardcopy-menu").remove();
	}

	function sync_entry(frm) {
		if (!is_usable(frm)) return;
		const docname = frm.docname;

		fetch_integration().then((cfg) => {
			try {
				if (!cfg) return; // settings unavailable: leave the form alone
				// The form may have moved on while the request was running.
				if (!is_usable(frm) || frm.docname !== docname) return;

				if (!cfg.show_button || !cfg.allowed.has(frm.doctype)) {
					remove_entry(frm);
					return;
				}
				ensure_menu_item(frm);
				ensure_icon(frm);
			} catch (e) {
				// never let the button break a form
			}
		});
	}

	function install() {
		$(document)
			.off(EVENT)
			.on(EVENT, function (_e, frm) {
				// This runs inside Frappe's render chain: an exception here would stop the
				// form from finishing, so nothing may escape.
				try {
					sync_entry(frm);
				} catch (e) {
					// ignore
				}
			});

		// A form may already be open if this script loaded late.
		try {
			if (window.cur_frm) sync_entry(window.cur_frm);
		} catch (e) {
			// ignore
		}
	}

	function ready() {
		return !!(
			window.$ &&
			window.frappe &&
			frappe.ui &&
			frappe.ui.form &&
			typeof __ === "function"
		);
	}

	if (ready()) {
		install();
	} else {
		let tries = 0;
		const wait = setInterval(() => {
			tries += 1;
			if (ready()) {
				clearInterval(wait);
				install();
			} else if (tries > 80) {
				clearInterval(wait); // give up quietly after ~20 s
			}
		}, 250);
	}
})();
