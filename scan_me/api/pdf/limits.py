# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
"""Per-user limits for PDF rendering, and the request filter for server-side Chromium.

Each render starts a Chromium process that can take many seconds, so the limit that
matters is how many a single user has running at once. Frappe's built-in
`rate_limit` counts per IP, which would make everyone behind one office address
share a single budget, so it is not used here."""

from urllib.parse import urlparse

import frappe
from frappe.utils import cint

# site_config.json keys that override the defaults.
CONF_PREVIEW_CONCURRENT = "scan_me_pdf_preview_concurrent"
CONF_DOWNLOAD_CONCURRENT = "scan_me_pdf_download_concurrent"
CONF_PREVIEW_PER_MIN = "scan_me_pdf_preview_per_minute"
CONF_DOWNLOAD_PER_MIN = "scan_me_pdf_download_per_minute"
CONF_ALLOWED_HOSTS = "scan_me_pdf_allowed_hosts"

DEFAULTS = {
	"preview": {"concurrent": 2, "per_minute": 60},
	"download": {"concurrent": 2, "per_minute": 20},
}
# A crashed worker never releases its slot; the counter expires on its own.
SLOT_TTL_SECONDS = 180
WINDOW_SECONDS = 60

# Web fonts are part of the supported print CSS, so these stay reachable.
DEFAULT_ALLOWED_HOSTS = ("fonts.googleapis.com", "fonts.gstatic.com")


def _limits(kind):
	conf = frappe.conf
	if kind == "preview":
		return (
			cint(conf.get(CONF_PREVIEW_CONCURRENT) or DEFAULTS["preview"]["concurrent"]),
			cint(conf.get(CONF_PREVIEW_PER_MIN) or DEFAULTS["preview"]["per_minute"]),
		)
	return (
		cint(conf.get(CONF_DOWNLOAD_CONCURRENT) or DEFAULTS["download"]["concurrent"]),
		cint(conf.get(CONF_DOWNLOAD_PER_MIN) or DEFAULTS["download"]["per_minute"]),
	)


def _too_many(message):
	frappe.throw(frappe._(message), frappe.RateLimitExceededError)


def acquire_slot(kind, user=None):
	"""Reserve a render slot for `user` or raise RateLimitExceededError (HTTP 429).

	Returns a function that releases the slot; call it in a `finally`."""
	user = user or frappe.session.user
	max_concurrent, max_per_minute = _limits(kind)

	cache = frappe.cache
	conc_key = cache.make_key(f"scan_me:pdf:conc:{kind}:{user}")
	count_key = cache.make_key(f"scan_me:pdf:count:{kind}:{user}")

	running = cache.incrby(conc_key, 1)
	cache.expire(conc_key, SLOT_TTL_SECONDS)

	def release():
		if cache.decrby(conc_key, 1) < 0:
			cache.set(conc_key, 0)

	if running > max_concurrent:
		release()
		_too_many("Too many PDFs are being prepared for you right now. Please wait a few seconds.")

	used = cache.incrby(count_key, 1)
	if used == 1:
		cache.expire(count_key, WINDOW_SECONDS)
	if used > max_per_minute:
		release()
		_too_many("You are generating PDFs too quickly. Please wait a minute and try again.")

	return release


# ---- request filter for the headless browser -------------------------------


def _allowed_hosts():
	hosts = set(DEFAULT_ALLOWED_HOSTS)
	extra = frappe.conf.get(CONF_ALLOWED_HOSTS) or []
	if isinstance(extra, str):
		extra = [h.strip() for h in extra.split(",") if h.strip()]
	hosts.update(h.lower() for h in extra)
	site_host = urlparse(frappe.utils.get_url()).hostname
	if site_host:
		hosts.add(site_host.lower())
	return hosts


def is_request_allowed(url, allowed_hosts):
	"""data:/blob:/about: and the site itself are allowed, plus the configured hosts."""
	scheme = urlparse(url).scheme.lower()
	if scheme in ("data", "blob", "about"):
		return True
	if scheme not in ("http", "https"):
		return False
	host = (urlparse(url).hostname or "").lower()
	return host in allowed_hosts


def restrict_requests(page):
	"""Stop the print page from fetching arbitrary URLs from the server.

	Document HTML is user-controlled; without this, a remote image makes the server
	download it (slow for large photos) and an internal address can be probed."""
	allowed = _allowed_hosts()

	def handler(route):
		if is_request_allowed(route.request.url, allowed):
			route.continue_()
		else:
			route.abort()

	page.route("**/*", handler)
