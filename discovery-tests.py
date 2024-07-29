import os
from pprint import pformat
import re
import requests
import time
from typing import Any
from typing import Dict
from typing import Set
from typing import Optional
import unittest
import xml.etree.ElementTree as ET
import xml.dom.minidom

"""Must be ran in current enlistment shell. Aside from the suggested workflow below, **you must also be on the feature branch "user/cgonzales/cspp-discovery-drop"**.
To use your python installment out of the box, simply enter the following (see more here: https://docs.python.org/3/library/venv.html#creating-virtual-environments):
	python -m venv c:\path\to\myenv
	c:\path\to\myenv\Scripts\activate.bat
	c:\path\to\myenv\Scripts\pip3.exe install requests
	c:\path\to\myenv\Scripts\python.exe c:\path\to\this\script\discovery-tests.py

	OR to run an individual unit test,
	c:\path\to\myenv\Scripts\python.exe -m unittest c:\path\to\this\script\discovery-tests.py -k <name-of-test>
"""
class DiscoveryTests(unittest.TestCase):
	path_to_brs_ini = "C:\\hosted\\Data\\Local\\brs.ini"
	lkg_commit = "fb8f40d166a1aa9f196bd6206671a2ec84f3303b"
	brs_overrides_cspp_changes_base = {
		"CSPPChangesEnabled": "(System.Boolean)True",
		"WopiDiscoveryRefactoringChangesEnabled": "(System.Boolean)True",
		"WopiDiscoveryHighRiskRefactoringEnabled": "(System.Boolean)True",
		"CSPPLeaveOutBootstrapperUrlWOPI": "(System.Boolean)True",
		"CSPPLeaveOutApplicationBaseUrlWOPI": "(System.Boolean)True",
		"CSPPLeaveOutAppBootstrapperUrlsWOPI": "(System.Boolean)True"
	}
	brs_overrides_static_uri_overrides = {
		"RegionBoundary": "(System.String)PPC",
		"WordViewerHostNameOverride": "(System.String)word-view",
		"VisioWebHostNameOverride": "(System.String)visio",
		"ExcelHostNameOverride": "(System.String)excel",
		"PowerPointHostNameOverride": "(System.String)powerpoint",
		"OneNoteHostNameOverride": "(System.String)onenote",
		"StaticContentHost": "(System.String)c1-{0}"
	}
	brs_overrides_sovereign_environment = {
		"StaticContentHostOverride": "(System.String)dod.cdn.office365.us",
		"ClientRequestDomainSuffix": "(System.String)dod.online.office365.us"
	}
	cache_invalidation_header = {
		"Cache-Control": "no-cache, no-store, must-revalidate, pre-check=0, post-check=0, max-age=0, s-maxage=0"
	}
	memory_diagnostics_params = {
		"memorycachediag": "1"
	}
	cspp_plus_query_params = {
		"partner": "csppplus"
	}
	etc_hosts = """127.0.0.1       cspp-prod.officeapps.live.com
127.0.0.1       cspp-test.officeapps.live.com
127.0.0.1       cspp-fedramp-moderate.officeapps.live.com
127.0.0.1       cspp-fedramp-dod.officeapps.live.com
127.0.0.1       lgxc-onenote.dod.online.office365.us
127.0.0.1       ffc-onenote.officeapps.live.com
127.0.0.1       ppc-onenote.officeapps.live.com
127.0.0.1       gbc-onenote.officeapps.live.com
127.0.0.1       onenote.officeapps.live.com
127.0.0.1       co1-onenote.officeapps.live.com
127.0.0.1       garbage.officeapps.live.com
"""

	in_memory_cache_header = "X-FromMemoryCache"
	discovery_base_url_template = "http://{0}/hosting/discovery.ashx"
	supported_cspp_apps = set(["Word", "Excel", "PowerPoint", "WopiTest"])
	supported_cspp_attribs = set(["name", "favIconUrl", "checkLicense"])
	supported_cspp_actions = set(["view","edit","editnew","convert","getinfo",
		"mobileView","embedview","formsubmit","formedit","rest","preloadedit","preloadview"])
	supported_csppplus_actions = set(["collab", "rtc"])
	cache_control_exp = re.compile(".*max-age=([0-9]+)$")
	should_rebuild = False
	log_filehandle = None
	etc_hosts_path = "C:\\Windows\\System32\\drivers\\etc\\hosts"

	@classmethod
	def setUpClass(cls):
		cls.rebuild()
		cls.should_rebuild = False
		# Log configuration
		current_time = time.strftime("%Y%m%d-%H%M%S")
		log_name = "debug-{0}.md".format(current_time)
		cls.log_filehandle = open(log_name, "w")
		etc_hosts_fh = open(cls.etc_hosts_path, "w")
		etc_hosts_fh.write(cls.etc_hosts)
		etc_hosts_fh.close()

	@classmethod
	def tearDownClass(cls):
		cls.log_filehandle.close()
		etc_hosts_fh = open(cls.etc_hosts_path, "w")
		etc_hosts_fh.close()

	def setUp(self):
		if self.should_rebuild:
			self.rebuild()
			self.should_rebuild = False

	"""#######################################################################
	###                          CSPP smoke tests
	#######################################################################"""

	"""Smoke test for cspp-prod (should be identical to `onenote.officeapps.live.com`)
	"""
	def test_cspp_prod_parity_with_onenote_subdomain(self):
		print(f"Running test: {self.test_cspp_prod_parity_with_onenote_subdomain.__name__}")
		brs_overrides = {**self.brs_overrides_cspp_changes_base, **self.brs_overrides_static_uri_overrides}
		cspp_request_headers = {**self.cache_invalidation_header}
		self.set_brs_overrides_and_persist(brs_overrides=brs_overrides)
		cspp_resp = requests.get(self.discovery_base_url_template.format("cspp-prod.officeapps.live.com"), headers=cspp_request_headers, params=self.memory_diagnostics_params)
		self.log_response(test_name=self.test_cspp_prod_parity_with_onenote_subdomain.__name__, request_url=cspp_resp.request.url, request_headers=cspp_request_headers, brs_overrides=brs_overrides, discovery_xml=cspp_resp.text, request_query_params=self.memory_diagnostics_params)
		onenote_request_headers = {**self.cache_invalidation_header}
		onenote_resp = requests.get(self.discovery_base_url_template.format("onenote.officeapps.live.com"), headers=onenote_request_headers, params=self.memory_diagnostics_params)
		self.log_response(test_name=self.test_cspp_prod_parity_with_onenote_subdomain.__name__, request_url=onenote_resp.request.url, request_headers=onenote_request_headers, brs_overrides=brs_overrides, discovery_xml=onenote_resp.text, request_query_params=self.memory_diagnostics_params)
		self.assert_against_cache_time(headers=cspp_resp.headers)
		self.assert_against_cache_time(headers=onenote_resp.headers)
		self.assertEqual(200, cspp_resp.status_code)
		self.assertEqual(200, onenote_resp.status_code)
		self.assert_against_in_memory_cache_value(cspp_resp.headers, val="0")
		self.assert_against_in_memory_cache_value(onenote_resp.headers, val="0")
		cspp_discovery = self.create_dict_from_discovery_response(discovery_xml=cspp_resp.text)
		onenote_discovery = self.create_dict_from_discovery_response(discovery_xml=onenote_resp.text)
		self.sanity_check_cspp_response(cspp_response=cspp_discovery)
		self.sanity_check_cspp_and_onenote_parity(cspp_response=cspp_discovery, onenote_response=onenote_discovery)

	"""Smoke test for cspp-test (should be identical to `ppc-onenote.officeapps.live.com`)
	"""
	def test_cspp_test_parity_with_ppc(self):
		print(f"Running test: {self.test_cspp_test_parity_with_ppc.__name__}")
		# Note that RegionBoundary will give PPC with the defaults
		brs_overrides = {**self.brs_overrides_cspp_changes_base, **self.brs_overrides_static_uri_overrides}
		cspp_request_headers = {**self.cache_invalidation_header}
		self.set_brs_overrides_and_persist(brs_overrides=brs_overrides)
		cspp_resp = requests.get(self.discovery_base_url_template.format("cspp-test.officeapps.live.com"), headers=cspp_request_headers, params=self.memory_diagnostics_params)
		self.log_response(test_name=self.test_cspp_test_parity_with_ppc.__name__, request_url=cspp_resp.request.url, request_headers=cspp_request_headers, brs_overrides=brs_overrides, discovery_xml=cspp_resp.text, request_query_params=self.memory_diagnostics_params)
		onenote_request_headers = {**self.cache_invalidation_header}
		onenote_resp = requests.get(self.discovery_base_url_template.format("ppc-onenote.officeapps.live.com"), headers=onenote_request_headers, params=self.memory_diagnostics_params)
		self.log_response(test_name=self.test_cspp_test_parity_with_ppc.__name__, request_url=onenote_resp.request.url, request_headers=onenote_request_headers, brs_overrides=brs_overrides, discovery_xml=onenote_resp.text, request_query_params=self.memory_diagnostics_params)
		self.assert_against_cache_time(headers=cspp_resp.headers)
		self.assert_against_cache_time(headers=onenote_resp.headers)
		self.assertEqual(200, cspp_resp.status_code)
		self.assertEqual(200, onenote_resp.status_code)
		self.assert_against_in_memory_cache_value(cspp_resp.headers, val="0")
		self.assert_against_in_memory_cache_value(onenote_resp.headers, val="0")
		cspp_discovery = self.create_dict_from_discovery_response(discovery_xml=cspp_resp.text)
		onenote_discovery = self.create_dict_from_discovery_response(discovery_xml=onenote_resp.text)
		self.sanity_check_cspp_response(cspp_response=cspp_discovery)
		self.sanity_check_cspp_and_onenote_parity(cspp_response=cspp_discovery, onenote_response=onenote_discovery)
		self.sanity_check_url_prefix(response=cspp_discovery, expected_url_regex="^http\\://PPC-.*",
			attribs_to_check=set(["urlsrc"]))

	"""Smoke test for cspp-fedramp-moderate (should be identical to `gbc-onenote.officeapps.live.com`)
	"""
	def test_cspp_fedramp_moderate_parity_with_gbc(self):
		print(f"Running test: {self.test_cspp_fedramp_moderate_parity_with_gbc.__name__}")
		# Note that RegionBoundary will give PPC with the defaults
		brs_overrides = {**self.brs_overrides_cspp_changes_base, **self.brs_overrides_static_uri_overrides}
		brs_overrides["RegionBoundary"] = "(System.String)GBC"
		brs_overrides["StaticContentHost"] = "(System.String)s1-{0}"
		cspp_request_headers = {**self.cache_invalidation_header}
		self.set_brs_overrides_and_persist(brs_overrides=brs_overrides)
		cspp_resp = requests.get(self.discovery_base_url_template.format("cspp-fedramp-moderate.officeapps.live.com"), headers=cspp_request_headers, params=self.memory_diagnostics_params)
		self.log_response(test_name=self.test_cspp_fedramp_moderate_parity_with_gbc.__name__, request_url=cspp_resp.request.url, request_headers=cspp_request_headers, brs_overrides=brs_overrides, discovery_xml=cspp_resp.text, request_query_params=self.memory_diagnostics_params)
		onenote_request_headers = {**self.cache_invalidation_header}
		onenote_resp = requests.get(self.discovery_base_url_template.format("gbc-onenote.officeapps.live.com"), headers=onenote_request_headers, params=self.memory_diagnostics_params)
		self.log_response(test_name=self.test_cspp_fedramp_moderate_parity_with_gbc.__name__, request_url=onenote_resp.request.url, request_headers=onenote_request_headers, brs_overrides=brs_overrides, discovery_xml=onenote_resp.text, request_query_params=self.memory_diagnostics_params)
		self.assert_against_cache_time(headers=cspp_resp.headers)
		self.assert_against_cache_time(headers=onenote_resp.headers)
		self.assertEqual(200, cspp_resp.status_code)
		self.assertEqual(200, onenote_resp.status_code)
		self.assert_against_in_memory_cache_value(cspp_resp.headers, val="0")
		self.assert_against_in_memory_cache_value(onenote_resp.headers, val="0")
		cspp_discovery = self.create_dict_from_discovery_response(discovery_xml=cspp_resp.text)
		onenote_discovery = self.create_dict_from_discovery_response(discovery_xml=onenote_resp.text)
		self.sanity_check_cspp_response(cspp_response=cspp_discovery)
		self.sanity_check_cspp_and_onenote_parity(cspp_response=cspp_discovery, onenote_response=onenote_discovery)
		self.sanity_check_url_prefix(response=cspp_discovery, expected_url_regex="http\\://GBC-.*",
			attribs_to_check=set(["urlsrc"]))
		# Note the URL regex here: it might be the case that 1CDN is enabled for some hosts, but that isn't applicable here since we are
		# ignoring the endpoint query parameter per the request. So, we get this instead.
		self.sanity_check_url_prefix(response=cspp_discovery, expected_url_regex="http\\://s1-.*",
			attribs_to_check=set(["favIconUrl"]), apps_to_skip=set(["WopiTest"]))

	"""Smoke test for cspp-fedramp-dod (should be identical to `lgxc-onenote.dod.online.office365.us`)
	"""
	def test_cspp_fedramp_dod_parity_with_lgxc(self):
		print(f"Running test: {self.test_cspp_fedramp_dod_parity_with_lgxc.__name__}")
		# Note that RegionBoundary will give PPC with the defaults
		brs_overrides = {**self.brs_overrides_cspp_changes_base, **self.brs_overrides_static_uri_overrides, **self.brs_overrides_sovereign_environment}
		brs_overrides["RegionBoundary"] = "(System.String)LGXC"
		# Prove that this gets overridden by declaring it anyways
		brs_overrides["StaticContentHost"] = "(System.String)s1-{0}"
		cspp_request_headers = {**self.cache_invalidation_header}
		self.set_brs_overrides_and_persist(brs_overrides=brs_overrides)
		cspp_resp = requests.get(self.discovery_base_url_template.format("cspp-fedramp-dod.officeapps.live.com"), headers=cspp_request_headers, params=self.memory_diagnostics_params)
		self.log_response(test_name=self.test_cspp_fedramp_dod_parity_with_lgxc.__name__, request_url=cspp_resp.request.url, request_headers=cspp_request_headers, brs_overrides=brs_overrides, discovery_xml=cspp_resp.text, request_query_params=self.memory_diagnostics_params)
		onenote_request_headers = {**self.cache_invalidation_header}
		onenote_resp = requests.get(self.discovery_base_url_template.format("lgxc-onenote.dod.online.office365.us"), headers=onenote_request_headers, params=self.memory_diagnostics_params)
		self.log_response(test_name=self.test_cspp_fedramp_dod_parity_with_lgxc.__name__, request_url=onenote_resp.request.url, request_headers=onenote_request_headers, brs_overrides=brs_overrides, discovery_xml=onenote_resp.text, request_query_params=self.memory_diagnostics_params)
		self.assert_against_cache_time(headers=cspp_resp.headers)
		self.assert_against_cache_time(headers=onenote_resp.headers)
		self.assertEqual(200, cspp_resp.status_code)
		self.assertEqual(200, onenote_resp.status_code)
		self.assert_against_in_memory_cache_value(cspp_resp.headers, val="0")
		self.assert_against_in_memory_cache_value(onenote_resp.headers, val="0")
		cspp_discovery = self.create_dict_from_discovery_response(discovery_xml=cspp_resp.text)
		onenote_discovery = self.create_dict_from_discovery_response(discovery_xml=onenote_resp.text)
		self.sanity_check_cspp_response(cspp_response=cspp_discovery)
		self.sanity_check_cspp_and_onenote_parity(cspp_response=cspp_discovery, onenote_response=onenote_discovery)
		self.sanity_check_url_prefix(response=cspp_discovery, expected_url_regex="http\\://LGXC-[a-z-]+\\.dod\\.online\\.office365\\.us.*",
			attribs_to_check=set(["urlsrc"]))
		# Note the URL regex here: it might be the case that 1CDN is enabled for some hosts, but that isn't applicable here since we are
		# ignoring the endpoint query parameter per the request. So, we get this instead.
		self.sanity_check_url_prefix(response=cspp_discovery, expected_url_regex="http\\://[a-z-]+\\.dod\\.cdn\\.office365\\.us\\.*",
			attribs_to_check=set(["favIconUrl"]), apps_to_skip=set(["WopiTest"]))

	"""#######################################################################
	###                      CSPP+ (plus) smoke tests
	#######################################################################"""
	"""Same as above but with some slight modifications in expectations
	"""
	def test_csppplus_prod_parity_with_onenote_subdomain(self):
		print(f"Running test: {self.test_csppplus_prod_parity_with_onenote_subdomain.__name__}")
		brs_overrides = {**self.brs_overrides_cspp_changes_base, **self.brs_overrides_static_uri_overrides}
		cspp_request_headers = {**self.cache_invalidation_header}
		self.set_brs_overrides_and_persist(brs_overrides=brs_overrides)
		cspp_resp = requests.get(self.discovery_base_url_template.format("cspp-prod.officeapps.live.com"), headers=cspp_request_headers, params={**self.cspp_plus_query_params, **self.memory_diagnostics_params})
		self.log_response(test_name=self.test_csppplus_prod_parity_with_onenote_subdomain.__name__, request_url=cspp_resp.request.url, request_headers=cspp_request_headers,
			brs_overrides=brs_overrides, discovery_xml=cspp_resp.text, request_query_params={**self.cspp_plus_query_params, **self.memory_diagnostics_params})
		onenote_request_headers = {**self.cache_invalidation_header}
		onenote_resp = requests.get(self.discovery_base_url_template.format("onenote.officeapps.live.com"), headers=onenote_request_headers, params=self.memory_diagnostics_params)
		self.assert_against_cache_time(headers=cspp_resp.headers)
		self.assert_against_cache_time(headers=onenote_resp.headers)
		self.assertEqual(200, cspp_resp.status_code)
		self.assertEqual(200, onenote_resp.status_code)
		self.assert_against_in_memory_cache_value(cspp_resp.headers, val="0")
		self.assert_against_in_memory_cache_value(onenote_resp.headers, val="0")
		cspp_discovery = self.create_dict_from_discovery_response(discovery_xml=cspp_resp.text)
		onenote_discovery = self.create_dict_from_discovery_response(discovery_xml=onenote_resp.text)
		self.sanity_check_cspp_response(cspp_response=cspp_discovery, is_cspp_plus=True)
		self.sanity_check_cspp_and_onenote_parity(cspp_response=cspp_discovery, onenote_response=onenote_discovery)

	def test_csppplus_test_parity_with_ppc(self):
		print(f"Running test: {self.test_csppplus_test_parity_with_ppc.__name__}")
		# Note that RegionBoundary will give PPC with the defaults
		brs_overrides = {**self.brs_overrides_cspp_changes_base, **self.brs_overrides_static_uri_overrides}
		cspp_request_headers = {**self.cache_invalidation_header}
		self.set_brs_overrides_and_persist(brs_overrides=brs_overrides)
		cspp_resp = requests.get(self.discovery_base_url_template.format("cspp-test.officeapps.live.com"), headers=cspp_request_headers, params={**self.cspp_plus_query_params, **self.memory_diagnostics_params})
		self.log_response(test_name=self.test_csppplus_test_parity_with_ppc.__name__, request_url=cspp_resp.request.url, request_headers=cspp_request_headers,
			brs_overrides=brs_overrides, discovery_xml=cspp_resp.text, request_query_params={**self.cspp_plus_query_params, **self.memory_diagnostics_params})
		onenote_request_headers = {**self.cache_invalidation_header}
		onenote_resp = requests.get(self.discovery_base_url_template.format("ppc-onenote.officeapps.live.com"), headers=onenote_request_headers, params=self.memory_diagnostics_params)
		self.assert_against_cache_time(headers=cspp_resp.headers)
		self.assert_against_cache_time(headers=onenote_resp.headers)
		self.assertEqual(200, cspp_resp.status_code)
		self.assertEqual(200, onenote_resp.status_code)
		self.assert_against_in_memory_cache_value(cspp_resp.headers, val="0")
		self.assert_against_in_memory_cache_value(onenote_resp.headers, val="0")
		cspp_discovery = self.create_dict_from_discovery_response(discovery_xml=cspp_resp.text)
		onenote_discovery = self.create_dict_from_discovery_response(discovery_xml=onenote_resp.text)
		self.sanity_check_cspp_response(cspp_response=cspp_discovery, is_cspp_plus=True)
		self.sanity_check_cspp_and_onenote_parity(cspp_response=cspp_discovery, onenote_response=onenote_discovery)
		self.sanity_check_url_prefix(response=cspp_discovery, expected_url_regex="^http\\://PPC-.*",
			attribs_to_check=set(["urlsrc"]))

	def test_csppplus_fedramp_moderate_parity_with_gbc(self):
		print(f"Running test: {self.test_csppplus_fedramp_moderate_parity_with_gbc.__name__}")
		# Note that RegionBoundary will give PPC with the defaults
		brs_overrides = {**self.brs_overrides_cspp_changes_base, **self.brs_overrides_static_uri_overrides}
		brs_overrides["RegionBoundary"] = "(System.String)GBC"
		brs_overrides["StaticContentHost"] = "(System.String)s1-{0}"
		cspp_request_headers = {**self.cache_invalidation_header}
		self.set_brs_overrides_and_persist(brs_overrides=brs_overrides)
		cspp_resp = requests.get(self.discovery_base_url_template.format("cspp-fedramp-moderate.officeapps.live.com"), headers=cspp_request_headers, params={**self.cspp_plus_query_params, **self.memory_diagnostics_params})
		self.log_response(test_name=self.test_csppplus_fedramp_moderate_parity_with_gbc.__name__, request_url=cspp_resp.request.url, request_headers=cspp_request_headers, 
			brs_overrides=brs_overrides, discovery_xml=cspp_resp.text, request_query_params={**self.cspp_plus_query_params, **self.memory_diagnostics_params})
		onenote_request_headers = {**self.cache_invalidation_header}
		onenote_resp = requests.get(self.discovery_base_url_template.format("gbc-onenote.officeapps.live.com"), headers=onenote_request_headers, params=self.memory_diagnostics_params)
		self.assert_against_cache_time(headers=cspp_resp.headers)
		self.assert_against_cache_time(headers=onenote_resp.headers)
		self.assertEqual(200, cspp_resp.status_code)
		self.assertEqual(200, onenote_resp.status_code)
		self.assert_against_in_memory_cache_value(cspp_resp.headers, val="0")
		self.assert_against_in_memory_cache_value(onenote_resp.headers, val="0")
		cspp_discovery = self.create_dict_from_discovery_response(discovery_xml=cspp_resp.text)
		onenote_discovery = self.create_dict_from_discovery_response(discovery_xml=onenote_resp.text)
		self.sanity_check_cspp_response(cspp_response=cspp_discovery, is_cspp_plus=True)
		self.sanity_check_cspp_and_onenote_parity(cspp_response=cspp_discovery, onenote_response=onenote_discovery)
		self.sanity_check_url_prefix(response=cspp_discovery, expected_url_regex="http\\://GBC-.*",
			attribs_to_check=set(["urlsrc"]))
		# Note the URL regex here: it might be the case that 1CDN is enabled for some hosts, but that isn't applicable here since we are
		# ignoring the endpoint query parameter per the request. So, we get this instead.
		self.sanity_check_url_prefix(response=cspp_discovery, expected_url_regex="http\\://s1-.*",
			attribs_to_check=set(["favIconUrl"]), apps_to_skip=set(["WopiTest"]))

	def test_csppplus_fedramp_dod_parity_with_lgxc(self):
		print(f"Running test: {self.test_csppplus_fedramp_dod_parity_with_lgxc.__name__}")
		# Note that RegionBoundary will give PPC with the defaults
		brs_overrides = {**self.brs_overrides_cspp_changes_base, **self.brs_overrides_static_uri_overrides, **self.brs_overrides_sovereign_environment}
		brs_overrides["RegionBoundary"] = "(System.String)LGXC"
		# Prove that this gets overridden by declaring it anyways
		brs_overrides["StaticContentHost"] = "(System.String)s1-{0}"
		cspp_request_headers = {**self.cache_invalidation_header}
		self.set_brs_overrides_and_persist(brs_overrides=brs_overrides)
		cspp_resp = requests.get(self.discovery_base_url_template.format("cspp-fedramp-dod.officeapps.live.com"), headers=cspp_request_headers, params={**self.cspp_plus_query_params, **self.memory_diagnostics_params})
		self.log_response(test_name=self.test_csppplus_fedramp_dod_parity_with_lgxc.__name__, request_url=cspp_resp.request.url, request_headers=cspp_request_headers,
			brs_overrides=brs_overrides, discovery_xml=cspp_resp.text, request_query_params={**self.cspp_plus_query_params, **self.memory_diagnostics_params})
		onenote_request_headers = {**self.cache_invalidation_header}
		onenote_resp = requests.get(self.discovery_base_url_template.format("lgxc-onenote.dod.online.office365.us"), headers=onenote_request_headers, params=self.memory_diagnostics_params)
		self.assert_against_cache_time(headers=cspp_resp.headers)
		self.assert_against_cache_time(headers=onenote_resp.headers)
		self.assertEqual(200, cspp_resp.status_code)
		self.assertEqual(200, onenote_resp.status_code)
		self.assert_against_in_memory_cache_value(cspp_resp.headers, val="0")
		self.assert_against_in_memory_cache_value(onenote_resp.headers, val="0")
		cspp_discovery = self.create_dict_from_discovery_response(discovery_xml=cspp_resp.text)
		onenote_discovery = self.create_dict_from_discovery_response(discovery_xml=onenote_resp.text)
		self.sanity_check_cspp_response(cspp_response=cspp_discovery, is_cspp_plus=True)
		self.sanity_check_cspp_and_onenote_parity(cspp_response=cspp_discovery, onenote_response=onenote_discovery)
		self.sanity_check_url_prefix(response=cspp_discovery, expected_url_regex="http\\://LGXC-[a-z-]+\\.dod\\.online\\.office365\\.us.*",
			attribs_to_check=set(["urlsrc"]))
		# Note the URL regex here: it might be the case that 1CDN is enabled for some hosts, but that isn't applicable here since we are
		# ignoring the endpoint query parameter per the request. So, we get this instead.
		self.sanity_check_url_prefix(response=cspp_discovery, expected_url_regex="http\\://[a-z-]+\\.dod\\.cdn\\.office365\\.us\\.*",
			attribs_to_check=set(["favIconUrl"]), apps_to_skip=set(["WopiTest"]))

	"""#######################################################################
	###                      Edge cases
	#######################################################################"""

	def test_edge_case_in_memory_caching_works_arbitrary_times_for_all_cspp_subdomains_and_csppplus_counterparts(self):
		print(f"Running test: {self.test_edge_case_in_memory_caching_works_arbitrary_times_for_all_cspp_subdomains_and_csppplus_counterparts.__name__}")
		brs_overrides = {**self.brs_overrides_cspp_changes_base, **self.brs_overrides_static_uri_overrides}
		self.set_brs_overrides_and_persist(brs_overrides=brs_overrides)
		# Completely arbitrary
		upper_bound = 5
		cspp_only_subdomains = ["cspp-test", "cspp-prod"]
		subdomains_to_test = ["ffc-onenote", "ppc-onenote", "onenote", "gbc-onenote"] + cspp_only_subdomains
		for subdomain in subdomains_to_test:
			domain = self.discovery_base_url_template.format(f"{subdomain}.officeapps.live.com")
			resp = requests.get(domain, headers=self.cache_invalidation_header, params=self.memory_diagnostics_params)
			self.assertEqual(200, resp.status_code)
			self.assert_against_in_memory_cache_value(resp.headers, val="0")
			for i in range(0, upper_bound):
				resp = requests.get(domain, headers=self.cache_invalidation_header, params=self.memory_diagnostics_params)
				self.assertEqual(200, resp.status_code)
				self.assert_against_cache_time(headers=resp.headers)
				self.assert_against_in_memory_cache_value(resp.headers, val="1")
		# Now, try CSPP+
		for subdomain in cspp_only_subdomains:
			cspp_domain = self.discovery_base_url_template.format(f"{subdomain}.officeapps.live.com")
			cspp_resp = requests.get(cspp_domain, headers=self.cache_invalidation_header, params={**self.cspp_plus_query_params, **self.memory_diagnostics_params})
			self.assertEqual(200, cspp_resp.status_code)
			# Important that this is now 0
			self.assert_against_in_memory_cache_value(cspp_resp.headers, val="0")
			for i in range(0, upper_bound):
				cspp_resp = requests.get(cspp_domain, headers=self.cache_invalidation_header, params={**self.cspp_plus_query_params, **self.memory_diagnostics_params})
				self.assertEqual(200, cspp_resp.status_code)
				self.assert_against_cache_time(headers=cspp_resp.headers)
				self.assert_against_in_memory_cache_value(cspp_resp.headers, val="1")

	"""Check that in memory caching hasn't been borked with the cache key modifications by sending multiple requests
	"""
	def test_edge_case_in_memory_caching_not_borked_between_1p_and_3p_hosts_with_no_asp_net_caching(self):
		print(f"Running test: {self.test_edge_case_in_memory_caching_not_borked_between_1p_and_3p_hosts_with_no_asp_net_caching.__name__}")
		brs_overrides = {**self.brs_overrides_cspp_changes_base, **self.brs_overrides_static_uri_overrides}
		cspp_request_headers = {**self.cache_invalidation_header}
		self.set_brs_overrides_and_persist(brs_overrides=brs_overrides)
		cspp_resp = requests.get(self.discovery_base_url_template.format("cspp-prod.officeapps.live.com"), headers=cspp_request_headers, params=self.memory_diagnostics_params)
		first_cspp_response = cspp_resp.text
		self.assertEqual(200, cspp_resp.status_code)
		self.assert_against_cache_time(headers=cspp_resp.headers)
		self.assert_against_in_memory_cache_value(cspp_resp.headers, val="0")
		cspp_resp = requests.get(self.discovery_base_url_template.format("cspp-prod.officeapps.live.com"), headers=cspp_request_headers, params=self.memory_diagnostics_params)
		second_cspp_response = cspp_resp.text
		self.assertEqual(200, cspp_resp.status_code)
		# This should still be 1800 seconds since we're sending cache invalidation headers
		self.assert_against_cache_time(headers=cspp_resp.headers)
		self.assert_against_in_memory_cache_value(cspp_resp.headers, val="1")
		# Minimal check, because why not?
		self.assertEqual(first_cspp_response, second_cspp_response)
		# Now, check that the below IS NOT cached. Because if it is, then we borked discovery caching (and discovery altogether). Yikes!
		onenote_request_headers = {**self.cache_invalidation_header}
		onenote_resp = requests.get(self.discovery_base_url_template.format("onenote.officeapps.live.com"), headers=onenote_request_headers, params=self.memory_diagnostics_params)
		first_onenote_response = onenote_resp.text
		self.assertEqual(200, onenote_resp.status_code)
		self.assert_against_cache_time(headers=onenote_resp.headers)
		# Important that this is 0 now...
		self.assert_against_in_memory_cache_value(onenote_resp.headers, val="0")
		onenote_resp = requests.get(self.discovery_base_url_template.format("onenote.officeapps.live.com"), headers=onenote_request_headers, params=self.memory_diagnostics_params)
		second_onenote_response = onenote_resp.text
		self.assertEqual(200, onenote_resp.status_code)
		# This should still be 1800 seconds since we're sending cache invalidation headers
		self.assert_against_cache_time(headers=onenote_resp.headers)
		self.assert_against_in_memory_cache_value(onenote_resp.headers, val="1")
		self.assertEqual(first_onenote_response, second_onenote_response)

	"""Simple test to make sure we didn't bork built-in ASP .NET server-side caching (we will be able to tell by the max-age in Cache-Control)
	"""
	def test_edge_case_asp_net_cache_not_borked(self):
		print(f"Running test: {self.test_edge_case_asp_net_cache_not_borked.__name__}")
		brs_overrides = {**self.brs_overrides_cspp_changes_base, **self.brs_overrides_static_uri_overrides}
		self.set_brs_overrides_and_persist(brs_overrides=brs_overrides)
		cspp_request_headers = {**self.cache_invalidation_header}
		cspp_resp = requests.get(self.discovery_base_url_template.format("cspp-prod.officeapps.live.com"), headers=cspp_request_headers)
		self.assertEqual(200, cspp_resp.status_code)
		self.assert_against_cache_time(headers=cspp_resp.headers)
		cspp_resp = requests.get(self.discovery_base_url_template.format("cspp-prod.officeapps.live.com"))
		self.assertEqual(200, cspp_resp.status_code)
		self.assert_against_cache_time(headers=cspp_resp.headers, expect_less_than=True)

	"""Test case that in the event that we decide to strip down *everything*, we should still be identical to onenote.*
	"""
	def test_edge_case_cspp_no_filters_should_be_identical_to_onenote(self):
		print(f"Running test: {self.test_edge_case_cspp_no_filters_should_be_identical_to_onenote.__name__}")
		# Take only one of the BRS overrides--the "main" one--and disable the rest
		brs_overrides = {"CSPPChangesEnabled": "(System.Boolean)True", "WopiDiscoveryRefactoringChangesEnabled": "(System.Boolean)True", **self.brs_overrides_static_uri_overrides}
		# Set all apps/actions to test for equivalence
		brs_overrides["CSPPOnlyWOPIApps"] = self.fetch_brs_override_for_list_types("Excel", "OneNote", "PowerPoint", "Visio", "WopiTest", "Word", "WordPdf", "WordPrague")
		brs_overrides["CSPPOnlyWOPIActions"] = self.fetch_brs_override_for_list_types("mobileView","present","presentservice","view","imagepreview","formsubmit","formedit","formpreview",
			"interactivepreview","rest","syndicate","legacywebservice","rtc","preloadedit","preloadview","getinfo", "collab","documentchat","preloadunifiedapp","open","seedopen","seedview",
			"seededit","seededitnew","editnew","embedview","embededit","embedpreview","embedconfigurator", "edit", "convert", "attend", "attendservice")
		self.set_brs_overrides_and_persist(brs_overrides=brs_overrides)
		cspp_request_headers = {**self.cache_invalidation_header}
		cspp_resp = requests.get(self.discovery_base_url_template.format("cspp-prod.officeapps.live.com"), headers=cspp_request_headers, params=self.memory_diagnostics_params)
		onenote_request_headers = {**self.cache_invalidation_header}
		onenote_resp = requests.get(self.discovery_base_url_template.format("onenote.officeapps.live.com"), headers=onenote_request_headers, params=self.memory_diagnostics_params)
		self.assert_against_cache_time(headers=cspp_resp.headers)
		self.assert_against_cache_time(headers=onenote_resp.headers)
		self.assertEqual(200, cspp_resp.status_code)
		self.assertEqual(200, onenote_resp.status_code)
		self.assert_against_in_memory_cache_value(cspp_resp.headers, val="0")
		self.assert_against_in_memory_cache_value(onenote_resp.headers, val="0")
		# No dictionaries needed, check for parity, to a tee
		self.assertEqual(cspp_resp.text, onenote_resp.text)

	"""Test case to make sure that we can recover in the event that we filter out too many apps/actions.
	"""
	def test_edge_case_some_apps_and_actions_are_pared_down_for_cspp(self):
		print(f"Running test: {self.test_edge_case_some_apps_and_actions_are_pared_down_for_cspp.__name__}")
		brs_overrides = {**self.brs_overrides_cspp_changes_base, **self.brs_overrides_static_uri_overrides}
		brs_overrides["CSPPOnlyWOPIApps"] = self.fetch_brs_override_for_list_types("Word")
		brs_overrides["CSPPOnlyWOPIActions"] = self.fetch_brs_override_for_list_types("mobileView")
		self.set_brs_overrides_and_persist(brs_overrides=brs_overrides)
		cspp_request_headers = {**self.cache_invalidation_header}
		cspp_resp = requests.get(self.discovery_base_url_template.format("cspp-prod.officeapps.live.com"), headers=cspp_request_headers, params=self.memory_diagnostics_params)
		self.log_response(test_name=self.test_edge_case_some_apps_and_actions_are_pared_down_for_cspp.__name__, request_url=cspp_resp.request.url, request_headers=cspp_request_headers, brs_overrides=brs_overrides, discovery_xml=cspp_resp.text, request_query_params=self.memory_diagnostics_params)
		self.assert_against_cache_time(headers=cspp_resp.headers)
		self.assertEqual(200, cspp_resp.status_code)
		self.assert_against_in_memory_cache_value(cspp_resp.headers, val="0")
		cspp_discovery = self.create_dict_from_discovery_response(discovery_xml=cspp_resp.text)
		self.sanity_check_cspp_response(cspp_response=cspp_discovery, supported_cspp_apps=set(["Word"]), supported_cspp_actions=set(["mobileView"]))

	"""Test case to make sure that we can recover in the event that we need the attribute "bootstrapperUrl".
	"""
	def test_edge_case_bootstrapper_url_is_brsable(self):
		print(f"Running test: {self.test_edge_case_bootstrapper_url_is_brsable.__name__}")
		brs_overrides = {**self.brs_overrides_cspp_changes_base, **self.brs_overrides_static_uri_overrides}
		del brs_overrides["CSPPLeaveOutBootstrapperUrlWOPI"]
		self.set_brs_overrides_and_persist(brs_overrides=brs_overrides)
		cspp_request_headers = {**self.cache_invalidation_header}
		cspp_resp = requests.get(self.discovery_base_url_template.format("cspp-prod.officeapps.live.com"), headers=cspp_request_headers, params=self.memory_diagnostics_params)
		self.log_response(test_name=self.test_edge_case_bootstrapper_url_is_brsable.__name__, request_url=cspp_resp.request.url, request_headers=cspp_request_headers, brs_overrides=brs_overrides, discovery_xml=cspp_resp.text, request_query_params=self.memory_diagnostics_params)
		self.assert_against_cache_time(headers=cspp_resp.headers)
		self.assertEqual(200, cspp_resp.status_code)
		self.assert_against_in_memory_cache_value(cspp_resp.headers, val="0")
		cspp_discovery = self.create_dict_from_discovery_response(discovery_xml=cspp_resp.text)
		self.sanity_check_cspp_response(cspp_response=cspp_discovery, supported_cspp_attribs=set(["name", "favIconUrl", "checkLicense", "bootstrapperUrl", "staticResourceOrigin"]))

	"""Test case to make sure that we can recover in the event that we need the attribute "applicationBaseUrl".
	"""
	def test_edge_case_application_base_url_is_brsable(self):
		print(f"Running test: {self.test_edge_case_application_base_url_is_brsable.__name__}")
		brs_overrides = {**self.brs_overrides_cspp_changes_base, **self.brs_overrides_static_uri_overrides}
		del brs_overrides["CSPPLeaveOutApplicationBaseUrlWOPI"]
		self.set_brs_overrides_and_persist(brs_overrides=brs_overrides)
		cspp_request_headers = {**self.cache_invalidation_header}
		cspp_resp = requests.get(self.discovery_base_url_template.format("cspp-prod.officeapps.live.com"), headers=cspp_request_headers, params=self.memory_diagnostics_params)
		self.log_response(test_name=self.test_edge_case_application_base_url_is_brsable.__name__, request_url=cspp_resp.request.url, request_headers=cspp_request_headers, brs_overrides=brs_overrides, discovery_xml=cspp_resp.text, request_query_params=self.memory_diagnostics_params)
		self.assert_against_cache_time(headers=cspp_resp.headers)
		self.assertEqual(200, cspp_resp.status_code)
		self.assert_against_in_memory_cache_value(cspp_resp.headers, val="0")
		cspp_discovery = self.create_dict_from_discovery_response(discovery_xml=cspp_resp.text)
		self.sanity_check_cspp_response(cspp_response=cspp_discovery, supported_cspp_attribs=set(["name", "favIconUrl", "checkLicense", "applicationBaseUrl"]))

	"""Test case to make sure that we can recover in the event that we need the attribute "appBootstrapperUrl".
	"""
	def test_edge_case_app_bootstrapper_url_is_brsable(self):
		print(f"Running test: {self.test_edge_case_app_bootstrapper_url_is_brsable.__name__}")
		brs_overrides = {**self.brs_overrides_cspp_changes_base, **self.brs_overrides_static_uri_overrides}
		del brs_overrides["CSPPLeaveOutAppBootstrapperUrlsWOPI"]
		self.set_brs_overrides_and_persist(brs_overrides=brs_overrides)
		cspp_request_headers = {**self.cache_invalidation_header}
		cspp_resp = requests.get(self.discovery_base_url_template.format("cspp-prod.officeapps.live.com"), headers=cspp_request_headers, params=self.memory_diagnostics_params)
		self.log_response(test_name=self.test_edge_case_app_bootstrapper_url_is_brsable.__name__, request_url=cspp_resp.request.url, request_headers=cspp_request_headers, brs_overrides=brs_overrides, discovery_xml=cspp_resp.text, request_query_params=self.memory_diagnostics_params)
		self.assert_against_cache_time(headers=cspp_resp.headers)
		self.assertEqual(200, cspp_resp.status_code)
		self.assert_against_in_memory_cache_value(cspp_resp.headers, val="0")
		cspp_discovery = self.create_dict_from_discovery_response(discovery_xml=cspp_resp.text)
		self.sanity_check_cspp_response(cspp_response=cspp_discovery, supported_cspp_attribs=set(["name", "favIconUrl", "checkLicense", "appBootstrapperUrl"]))

	"""In the event that RegionBoundary is not present for a request that is in production, and that request isn't a request "to the global domain", then fail fatally
	"""
	def test_edge_case_region_boundary_not_correctly_provisioned_throws_500(self):
		print(f"Running test: {self.test_edge_case_region_boundary_not_correctly_provisioned_throws_500.__name__}")
		brs_overrides = {**self.brs_overrides_cspp_changes_base, **self.brs_overrides_static_uri_overrides, **self.brs_overrides_sovereign_environment}
		del brs_overrides["RegionBoundary"]
		brs_overrides["IsProduction"] = "(System.Boolean)True"
		self.set_brs_overrides_and_persist(brs_overrides=brs_overrides)
		cspp_request_headers = {**self.cache_invalidation_header}
		cspp_resp = requests.get(self.discovery_base_url_template.format("cspp-fedramp-dod.officeapps.live.com"), headers=cspp_request_headers, params=self.memory_diagnostics_params)
		self.assertEqual(500, cspp_resp.status_code)

	"""Litmus test to make sure the following endpoints are ignored by CSPP changes:
	- dcdiscovery
	- endpoint
	- dcprefix
	"""
	def test_edge_case_onenote_specific_query_params_ignored_by_cspp(self):
		print(f"Running test: {self.test_edge_case_onenote_specific_query_params_ignored_by_cspp.__name__}")
		brs_overrides = {**self.brs_overrides_cspp_changes_base, **self.brs_overrides_static_uri_overrides}
		cspp_request_headers = {**self.cache_invalidation_header}
		self.set_brs_overrides_and_persist(brs_overrides=brs_overrides)
		cspp_resp = requests.get(self.discovery_base_url_template.format("cspp-prod.officeapps.live.com"), headers=cspp_request_headers, params=self.memory_diagnostics_params)
		self.assert_against_in_memory_cache_value(cspp_resp.headers, val="0")
		cspp_resp_with_dcdiscovery = requests.get(self.discovery_base_url_template.format("cspp-prod.officeapps.live.com"), headers=cspp_request_headers, params={"dcdiscovery": "true", **self.memory_diagnostics_params})
		self.assert_against_in_memory_cache_value(cspp_resp_with_dcdiscovery.headers, val="1")
		self.assertEqual(cspp_resp.text, cspp_resp_with_dcdiscovery.text)
		cspp_resp_with_endpoint = requests.get(self.discovery_base_url_template.format("cspp-prod.officeapps.live.com"), headers=cspp_request_headers, params={"endpoint": "randomgarbagehere", **self.memory_diagnostics_params})
		self.assert_against_in_memory_cache_value(cspp_resp_with_endpoint.headers, val="1")
		self.assertEqual(cspp_resp.text, cspp_resp_with_endpoint.text)
		cspp_resp_with_dcprefix = requests.get(self.discovery_base_url_template.format("cspp-prod.officeapps.live.com"), headers=cspp_request_headers, params={"dcprefix": "co1", **self.memory_diagnostics_params})
		self.assert_against_in_memory_cache_value(cspp_resp_with_dcprefix.headers, val="1")
		self.assertEqual(cspp_resp.text, cspp_resp_with_dcprefix.text)

	"""#######################################################################
	### OneNote parity with old logic, i.e. we should get the same for both!
	#######################################################################"""

	"""Ad hoc refactoring turned on should be identical to nothing turned on
	"""
	def test_onenote_parity_adhoc_refactoring_changes_enabled_identical_to_everything_off(self):
		print(f"Running test: {self.test_onenote_parity_adhoc_refactoring_changes_enabled_identical_to_everything_off.__name__}")
		# Requests with refactoring settings *enabled*
		brs_overrides = {**self.brs_overrides_static_uri_overrides}
		brs_overrides["WopiDiscoveryRefactoringChangesEnabled"] = "(System.Boolean)True"
		brs_overrides["WopiDiscoveryHighRiskRefactoringEnabled"] = "(System.Boolean)True"
		self.set_brs_overrides_and_persist(brs_overrides=brs_overrides)
		new_response_global_domain = self.get_onenote_response(scenario=self.onenote_parity_global_domain.__name__, should_persist_and_reset=False)
		new_response_host_dcprefix = self.get_onenote_response(
			host_prefix="co1",
			scenario=self.onenote_parity_valid_dc_prefix.__name__,
			should_persist_and_reset=False)
		new_response_dcprefix = self.get_onenote_response(
			query_params={"dcprefix": "co1"},
			scenario=self.onenote_parity_valid_dc_prefix.__name__,
			should_persist_and_reset=False)
		new_response_bad_dcprefix = self.get_onenote_response(
			query_params={"dcprefix": "BLAH"},
			should_persist_and_reset=False)
		new_response_dcdiscovery = self.get_onenote_response(
			host_prefix="co1",
			query_params={"dcdiscovery": "true"},
			scenario=self.onenote_parity_valid_dcdiscovery.__name__,
			should_persist_and_reset=False)
		new_response_garbage_domain = self.get_onenote_response(
			host_override="garbage.officeapps.live.com",
			scenario=self.onenote_parity_garbage_domain.__name__,
			should_persist_and_reset=False)
		# Requests with refactoring settings *disabled*
		del brs_overrides["WopiDiscoveryRefactoringChangesEnabled"]
		del brs_overrides["WopiDiscoveryHighRiskRefactoringEnabled"]
		self.set_brs_overrides_and_persist(brs_overrides=brs_overrides)
		old_response_global_domain = self.get_onenote_response(should_persist_and_reset=False)
		old_response_host_dcprefix = self.get_onenote_response(
			host_prefix="co1",
			should_persist_and_reset=False)
		old_response_dcprefix = self.get_onenote_response(
			query_params={"dcprefix": "co1"},
			should_persist_and_reset=False)
		old_response_bad_dcprefix = self.get_onenote_response(
			query_params={"dcprefix": "BLAH"},
			should_persist_and_reset=False)
		old_response_dcdiscovery = self.get_onenote_response(
			host_prefix="co1",
			query_params={"dcdiscovery": "true"},
			should_persist_and_reset=False)
		old_response_garbage_domain = self.get_onenote_response(
			host_override="garbage.officeapps.live.com",
			should_persist_and_reset=False)
		# Test everything
		self.onenote_parity_valid_dc_prefix(new_response_host_dcprefix, old_response_host_dcprefix)
		self.onenote_parity_valid_dc_prefix(new_response_dcprefix, old_response_dcprefix)
		self.onenote_parity_invalid_dc_prefix(new_response_bad_dcprefix, old_response_bad_dcprefix)
		self.onenote_parity_valid_dcdiscovery(new_response_dcdiscovery, old_response_dcdiscovery)
		self.onenote_parity_global_domain(new_response_global_domain, old_response_global_domain)
		self.onenote_parity_garbage_domain(new_response_garbage_domain, old_response_garbage_domain)

	def test_onenote_parity_adhoc_refactoring_changes_enabled_and_high_risk_changes_enabled_and_cspp_changes_enabled_identical_to_everything_off(self):
		print(f"Running test: {self.test_onenote_parity_adhoc_refactoring_changes_enabled_and_high_risk_changes_enabled_and_cspp_changes_enabled_identical_to_everything_off.__name__}")
		# Requests with refactoring settings *enabled*
		brs_overrides = {**self.brs_overrides_static_uri_overrides}
		brs_overrides["WopiDiscoveryRefactoringChangesEnabled"] = "(System.Boolean)True"
		brs_overrides["WopiDiscoveryHighRiskRefactoringEnabled"] = "(System.Boolean)True"
		brs_overrides["CSPPChangesEnabled"] = "(System.Boolean)True"
		self.set_brs_overrides_and_persist(brs_overrides=brs_overrides)
		new_response_global_domain = self.get_onenote_response(scenario=self.onenote_parity_global_domain.__name__, should_persist_and_reset=False)
		new_response_host_dcprefix = self.get_onenote_response(
			host_prefix="co1",
			scenario=self.onenote_parity_valid_dc_prefix.__name__,
			should_persist_and_reset=False)
		new_response_dcprefix = self.get_onenote_response(
			query_params={"dcprefix": "co1"},
			scenario=self.onenote_parity_valid_dc_prefix.__name__,
			should_persist_and_reset=False)
		new_response_bad_dcprefix = self.get_onenote_response(
			query_params={"dcprefix": "BLAH"},
			should_persist_and_reset=False)
		new_response_dcdiscovery = self.get_onenote_response(
			host_prefix="co1",
			query_params={"dcdiscovery": "true"},
			scenario=self.onenote_parity_valid_dcdiscovery.__name__,
			should_persist_and_reset=False)
		new_response_garbage_domain = self.get_onenote_response(
			host_override="garbage.officeapps.live.com",
			scenario=self.onenote_parity_garbage_domain.__name__,
			should_persist_and_reset=False)
		# Requests with refactoring settings *disabled*
		del brs_overrides["WopiDiscoveryRefactoringChangesEnabled"]
		del brs_overrides["WopiDiscoveryHighRiskRefactoringEnabled"]
		del brs_overrides["CSPPChangesEnabled"]
		self.set_brs_overrides_and_persist(brs_overrides=brs_overrides)
		old_response_global_domain = self.get_onenote_response(should_persist_and_reset=False)
		old_response_host_dcprefix = self.get_onenote_response(
			host_prefix="co1",
			should_persist_and_reset=False)
		old_response_dcprefix = self.get_onenote_response(
			query_params={"dcprefix": "co1"},
			should_persist_and_reset=False)
		old_response_bad_dcprefix = self.get_onenote_response(
			query_params={"dcprefix": "BLAH"},
			should_persist_and_reset=False)
		old_response_dcdiscovery = self.get_onenote_response(
			host_prefix="co1",
			query_params={"dcdiscovery": "true"},
			should_persist_and_reset=False)
		old_response_garbage_domain = self.get_onenote_response(
			host_override="garbage.officeapps.live.com",
			should_persist_and_reset=False)
		# Test everything
		self.onenote_parity_valid_dc_prefix(new_response_host_dcprefix, old_response_host_dcprefix)
		self.onenote_parity_valid_dc_prefix(new_response_dcprefix, old_response_dcprefix)
		self.onenote_parity_invalid_dc_prefix(new_response_bad_dcprefix, old_response_bad_dcprefix)
		self.onenote_parity_valid_dcdiscovery(new_response_dcdiscovery, old_response_dcdiscovery)
		self.onenote_parity_global_domain(new_response_global_domain, old_response_global_domain)
		self.onenote_parity_garbage_domain(new_response_garbage_domain, old_response_garbage_domain)

	def test_onenote_parity_high_risk_changes_enabled_but_ad_hoc_changes_disabled_identical_to_everything_off(self):
		print(f"Running test: {self.test_onenote_parity_high_risk_changes_enabled_but_ad_hoc_changes_disabled_identical_to_everything_off.__name__}")
		# Requests with refactoring settings *enabled*
		brs_overrides = {**self.brs_overrides_static_uri_overrides}
		brs_overrides["WopiDiscoveryHighRiskRefactoringEnabled"] = "(System.Boolean)True"
		self.set_brs_overrides_and_persist(brs_overrides=brs_overrides)
		new_response_global_domain = self.get_onenote_response(scenario=self.onenote_parity_global_domain.__name__, should_persist_and_reset=False)
		new_response_host_dcprefix = self.get_onenote_response(
			host_prefix="co1",
			scenario=self.onenote_parity_valid_dc_prefix.__name__,
			should_persist_and_reset=False)
		new_response_dcprefix = self.get_onenote_response(
			query_params={"dcprefix": "co1"},
			scenario=self.onenote_parity_valid_dc_prefix.__name__,
			should_persist_and_reset=False)
		new_response_bad_dcprefix = self.get_onenote_response(
			query_params={"dcprefix": "BLAH"},
			should_persist_and_reset=False)
		new_response_dcdiscovery = self.get_onenote_response(
			host_prefix="co1",
			query_params={"dcdiscovery": "true"},
			scenario=self.onenote_parity_valid_dcdiscovery.__name__,
			should_persist_and_reset=False)
		new_response_garbage_domain = self.get_onenote_response(
			host_override="garbage.officeapps.live.com",
			scenario=self.onenote_parity_garbage_domain.__name__,
			should_persist_and_reset=False)
		# Requests with refactoring settings *disabled*
		del brs_overrides["WopiDiscoveryHighRiskRefactoringEnabled"]
		self.set_brs_overrides_and_persist(brs_overrides=brs_overrides)
		old_response_global_domain = self.get_onenote_response(should_persist_and_reset=False)
		old_response_host_dcprefix = self.get_onenote_response(
			host_prefix="co1",
			should_persist_and_reset=False)
		old_response_dcprefix = self.get_onenote_response(
			query_params={"dcprefix": "co1"},
			should_persist_and_reset=False)
		old_response_bad_dcprefix = self.get_onenote_response(
			query_params={"dcprefix": "BLAH"},
			should_persist_and_reset=False)
		old_response_dcdiscovery = self.get_onenote_response(
			host_prefix="co1",
			query_params={"dcdiscovery": "true"},
			should_persist_and_reset=False)
		old_response_garbage_domain = self.get_onenote_response(
			host_override="garbage.officeapps.live.com",
			should_persist_and_reset=False)
		# Test everything
		self.onenote_parity_valid_dc_prefix(new_response_host_dcprefix, old_response_host_dcprefix)
		self.onenote_parity_valid_dc_prefix(new_response_dcprefix, old_response_dcprefix)
		self.onenote_parity_invalid_dc_prefix(new_response_bad_dcprefix, old_response_bad_dcprefix)
		self.onenote_parity_valid_dcdiscovery(new_response_dcdiscovery, old_response_dcdiscovery)
		self.onenote_parity_global_domain(new_response_global_domain, old_response_global_domain)
		self.onenote_parity_garbage_domain(new_response_garbage_domain, old_response_garbage_domain)

	def test_onenote_parity_cspp_changes_enabled_but_ad_hoc_changes_disabled_identical_to_everything_off(self):
		print(f"Running test: {self.test_onenote_parity_cspp_changes_enabled_but_ad_hoc_changes_disabled_identical_to_everything_off.__name__}")
		# Requests with refactoring settings *enabled*
		brs_overrides = {**self.brs_overrides_static_uri_overrides}
		brs_overrides["CSPPChangesEnabled"] = "(System.Boolean)True"
		self.set_brs_overrides_and_persist(brs_overrides=brs_overrides)
		new_response_global_domain = self.get_onenote_response(scenario=self.onenote_parity_global_domain.__name__, should_persist_and_reset=False)
		new_response_host_dcprefix = self.get_onenote_response(
			host_prefix="co1",
			scenario=self.onenote_parity_valid_dc_prefix.__name__,
			should_persist_and_reset=False)
		new_response_dcprefix = self.get_onenote_response(
			query_params={"dcprefix": "co1"},
			scenario=self.onenote_parity_valid_dc_prefix.__name__,
			should_persist_and_reset=False)
		new_response_bad_dcprefix = self.get_onenote_response(
			query_params={"dcprefix": "BLAH"},
			should_persist_and_reset=False)
		new_response_dcdiscovery = self.get_onenote_response(
			host_prefix="co1",
			query_params={"dcdiscovery": "true"},
			scenario=self.onenote_parity_valid_dcdiscovery.__name__,
			should_persist_and_reset=False)
		new_response_garbage_domain = self.get_onenote_response(
			host_override="garbage.officeapps.live.com",
			scenario=self.onenote_parity_garbage_domain.__name__,
			should_persist_and_reset=False)
		# Requests with refactoring settings *disabled*
		del brs_overrides["CSPPChangesEnabled"]
		self.set_brs_overrides_and_persist(brs_overrides=brs_overrides)
		old_response_global_domain = self.get_onenote_response(should_persist_and_reset=False)
		old_response_host_dcprefix = self.get_onenote_response(
			host_prefix="co1",
			should_persist_and_reset=False)
		old_response_dcprefix = self.get_onenote_response(
			query_params={"dcprefix": "co1"},
			should_persist_and_reset=False)
		old_response_bad_dcprefix = self.get_onenote_response(
			query_params={"dcprefix": "BLAH"},
			should_persist_and_reset=False)
		old_response_dcdiscovery = self.get_onenote_response(
			host_prefix="co1",
			query_params={"dcdiscovery": "true"},
			should_persist_and_reset=False)
		old_response_garbage_domain = self.get_onenote_response(
			host_override="garbage.officeapps.live.com",
			should_persist_and_reset=False)
		# Test everything
		self.onenote_parity_valid_dc_prefix(new_response_host_dcprefix, old_response_host_dcprefix)
		self.onenote_parity_valid_dc_prefix(new_response_dcprefix, old_response_dcprefix)
		self.onenote_parity_invalid_dc_prefix(new_response_bad_dcprefix, old_response_bad_dcprefix)
		self.onenote_parity_valid_dcdiscovery(new_response_dcdiscovery, old_response_dcdiscovery)
		self.onenote_parity_global_domain(new_response_global_domain, old_response_global_domain)
		self.onenote_parity_garbage_domain(new_response_garbage_domain, old_response_garbage_domain)

	"""Unfortunately we have to shove all of our tests in one test since the build takes painstakingly long--we don't *have* to, but this will take forever otherwise and this PR will never get done!
	"""
	@unittest.skip("Marking this as skipped by default since this takes years, but it should periodically be ran.")
	def test_onenote_parity_with_lkg_build(self):
		print(f"Running test: {self.test_onenote_parity_with_lkg_build.__name__}")
		# Requests with new changes
		new_response_global_domain = self.get_onenote_response(scenario=self.onenote_parity_global_domain.__name__)
		new_response_host_dcprefix = self.get_onenote_response(
			host_prefix="co1",
			scenario=self.onenote_parity_valid_dc_prefix.__name__)
		new_response_dcprefix = self.get_onenote_response(
			query_params={"dcprefix": "co1"},
			scenario=self.onenote_parity_valid_dc_prefix.__name__)
		new_response_bad_dcprefix = self.get_onenote_response(
			query_params={"dcprefix": "BLAH"})
		new_response_dcdiscovery = self.get_onenote_response(
			host_prefix="co1",
			query_params={"dcdiscovery": "true"},
			scenario=self.onenote_parity_valid_dcdiscovery.__name__)
		new_response_garbage_domain = self.get_onenote_response(
			host_override="garbage.officeapps.live.com",
			scenario=self.onenote_parity_garbage_domain.__name__)
		# Rebuild once
		self.rebuild(ref=self.lkg_commit)
		# Requests with LKG changes
		old_response_global_domain = self.get_onenote_response()
		old_response_host_dcprefix = self.get_onenote_response(
			host_prefix="co1")
		old_response_dcprefix = self.get_onenote_response(
			query_params={"dcprefix": "co1"})
		old_response_bad_dcprefix = self.get_onenote_response(
			query_params={"dcprefix": "BLAH"})
		old_response_dcdiscovery = self.get_onenote_response(
			host_prefix="co1",
			query_params={"dcdiscovery": "true"})
		old_response_garbage_domain = self.get_onenote_response(
			host_override="garbage.officeapps.live.com")
		# Test everything, comparing against LKG commit and no BRSs for new changes
		self.onenote_parity_valid_dc_prefix(new_response_host_dcprefix, old_response_host_dcprefix)
		self.onenote_parity_valid_dc_prefix(new_response_dcprefix, old_response_dcprefix)
		self.onenote_parity_invalid_dc_prefix(new_response_bad_dcprefix, old_response_bad_dcprefix)
		self.onenote_parity_valid_dcdiscovery(new_response_dcdiscovery, old_response_dcdiscovery)
		self.onenote_parity_global_domain(new_response_global_domain, old_response_global_domain)
		self.onenote_parity_garbage_domain(new_response_garbage_domain, old_response_garbage_domain)

	"""#######################################################################
	### OneNote parity with old logic, i.e. if the gatekeeper "WopiDiscoveryRefactoringChangesEnabled" is off,
	### then it shouldn't matter if CSPPChangesEnabled or WopiDiscoveryHighRiskRefactoringEnabled is turned on,
	### the result should always be the same--pass it along the non-production flow, i.e. "chameleon"-like
	### behavior
	#######################################################################"""

	def test_cspp_parity_high_risk_changes_enabled_but_ad_hoc_changes_disabled_identical_to_everything_off(self):
		print(f"Running test: {self.test_cspp_parity_high_risk_changes_enabled_but_ad_hoc_changes_disabled_identical_to_everything_off.__name__}")
		brs_overrides = {**self.brs_overrides_static_uri_overrides}
		brs_overrides["WopiDiscoveryHighRiskRefactoringEnabled"] = "(System.Boolean)True"
		self.set_brs_overrides_and_persist(brs_overrides=brs_overrides)
		cspp_resp_with_settings = requests.get(self.discovery_base_url_template.format("cspp-prod.officeapps.live.com"), params=self.memory_diagnostics_params)
		self.log_response(test_name=self.test_cspp_parity_high_risk_changes_enabled_but_ad_hoc_changes_disabled_identical_to_everything_off.__name__, request_url=cspp_resp_with_settings.request.url, request_headers={}, brs_overrides=brs_overrides, discovery_xml=cspp_resp_with_settings.text, request_query_params=self.memory_diagnostics_params)
		del brs_overrides["WopiDiscoveryHighRiskRefactoringEnabled"]
		self.set_brs_overrides_and_persist(brs_overrides=brs_overrides)
		cspp_resp_no_settings = requests.get(self.discovery_base_url_template.format("cspp-prod.officeapps.live.com"), params=self.memory_diagnostics_params)
		self.assertNotIn(self.in_memory_cache_header, cspp_resp_with_settings.headers)
		self.assertNotIn(self.in_memory_cache_header, cspp_resp_no_settings.headers)
		self.onenote_parity_common_assertions(cspp_resp_with_settings, cspp_resp_no_settings)

	def test_cspp_parity_cspp_changes_enabled_but_ad_hoc_changes_disabled_identical_to_everything_off(self):
		print(f"Running test: {self.test_cspp_parity_cspp_changes_enabled_but_ad_hoc_changes_disabled_identical_to_everything_off.__name__}")
		brs_overrides = {**self.brs_overrides_static_uri_overrides}
		brs_overrides["CSPPChangesEnabled"] = "(System.Boolean)True"
		self.set_brs_overrides_and_persist(brs_overrides=brs_overrides)
		cspp_resp_with_settings = requests.get(self.discovery_base_url_template.format("cspp-prod.officeapps.live.com"), params=self.memory_diagnostics_params)
		self.log_response(test_name=self.test_cspp_parity_cspp_changes_enabled_but_ad_hoc_changes_disabled_identical_to_everything_off.__name__, request_url=cspp_resp_with_settings.request.url, request_headers={}, brs_overrides=brs_overrides, discovery_xml=cspp_resp_with_settings.text, request_query_params=self.memory_diagnostics_params)
		del brs_overrides["CSPPChangesEnabled"]
		self.set_brs_overrides_and_persist(brs_overrides=brs_overrides)
		cspp_resp_no_settings = requests.get(self.discovery_base_url_template.format("cspp-prod.officeapps.live.com"), params=self.memory_diagnostics_params)
		self.assertNotIn(self.in_memory_cache_header, cspp_resp_with_settings.headers)
		self.assertNotIn(self.in_memory_cache_header, cspp_resp_no_settings.headers)
		self.onenote_parity_common_assertions(cspp_resp_with_settings, cspp_resp_no_settings)

	def test_cspp_parity_high_risk_changes_enabled_and_ad_hoc_changes_enabled_but_cspp_changes_disabled_identical_to_everything_off(self):
		print(f"Running test: {self.test_cspp_parity_high_risk_changes_enabled_and_ad_hoc_changes_enabled_but_cspp_changes_disabled_identical_to_everything_off.__name__}")
		brs_overrides = {**self.brs_overrides_static_uri_overrides}
		brs_overrides["WopiDiscoveryRefactoringChangesEnabled"] = "(System.Boolean)True"
		brs_overrides["WopiDiscoveryHighRiskRefactoringEnabled"] = "(System.Boolean)True"
		self.set_brs_overrides_and_persist(brs_overrides=brs_overrides)
		cspp_resp_with_settings = requests.get(self.discovery_base_url_template.format("cspp-prod.officeapps.live.com"), params=self.memory_diagnostics_params)
		self.log_response(test_name=self.test_cspp_parity_high_risk_changes_enabled_and_ad_hoc_changes_enabled_but_cspp_changes_disabled_identical_to_everything_off.__name__, request_url=cspp_resp_with_settings.request.url, request_headers={}, brs_overrides=brs_overrides, discovery_xml=cspp_resp_with_settings.text, request_query_params=self.memory_diagnostics_params)
		del brs_overrides["WopiDiscoveryRefactoringChangesEnabled"]
		del brs_overrides["WopiDiscoveryHighRiskRefactoringEnabled"]
		self.set_brs_overrides_and_persist(brs_overrides=brs_overrides)
		cspp_resp_no_settings = requests.get(self.discovery_base_url_template.format("cspp-prod.officeapps.live.com"), params=self.memory_diagnostics_params)
		self.assertNotIn(self.in_memory_cache_header, cspp_resp_with_settings.headers)
		self.assertNotIn(self.in_memory_cache_header, cspp_resp_no_settings.headers)
		self.onenote_parity_common_assertions(cspp_resp_with_settings, cspp_resp_no_settings)

	def onenote_parity_garbage_domain(self,
	new_response: requests.models.Response,
	old_response: requests.models.Response) -> None:
		self.onenote_parity_common_assertions(new_response, old_response)
		onenote_discovery = self.create_dict_from_discovery_response(discovery_xml=new_response.text)
		self.sanity_check_url_prefix(response=onenote_discovery, expected_url_regex="http\\://garbage.officeapps.live.com.*",
			attribs_to_check=set(["urlsrc", "favIconUrl", "applicationBaseUrl"]))

	def onenote_parity_global_domain(self,
	new_response: requests.models.Response,
	old_response: requests.models.Response) -> None:
		self.onenote_parity_common_assertions(new_response, old_response)

	def onenote_parity_invalid_dc_prefix(self,
	new_response: requests.models.Response,
	old_response: requests.models.Response) -> None:
		self.assertEqual(400, new_response.status_code)
		self.assertEqual(400, old_response.status_code)

	def onenote_parity_valid_dc_prefix(self,
	new_response: requests.models.Response,
	old_response: requests.models.Response) -> None:
		self.onenote_parity_common_assertions(new_response, old_response)
		onenote_discovery = self.create_dict_from_discovery_response(discovery_xml=new_response.text)
		self.sanity_check_url_prefix(response=onenote_discovery, expected_url_regex="http\\://(?:co1|CO1)-[A-Za-z-]+\\.officeapps.live.com.*",
			attribs_to_check=set(["urlsrc"]))

	def onenote_parity_valid_endpoint(self,
	new_response: requests.models.Response,
	old_response: requests.models.Response) -> None:
		self.onenote_parity_common_assertions(new_response, old_response)

	def onenote_parity_valid_dcdiscovery(self,
	new_response: requests.models.Response,
	old_response: requests.models.Response) -> None:
		self.onenote_parity_common_assertions(new_response, old_response)
		onenote_discovery = self.create_dict_from_discovery_response(discovery_xml=new_response.text)
		self.sanity_check_url_prefix(response=onenote_discovery, expected_url_regex="http\\://(?:dc2|DC2)-[A-Za-z-]+\\.officeapps.live.com.*",
			attribs_to_check=set(["urlsrc"]))

	def onenote_parity_common_assertions(self,
	new_response: requests.models.Response,
	old_response: requests.models.Response) -> None:
		self.assert_against_cache_time(headers=new_response.headers)
		self.assert_against_cache_time(headers=old_response.headers)
		self.assertEqual(200, new_response.status_code)
		self.assertEqual(200, old_response.status_code)
		self.assertEqual(new_response.text, old_response.text)

	def get_onenote_response(self, host_prefix: str=None,
	host_override: str=None,
	query_params: Optional[Dict[str,str]]={},
	additional_headers: Optional[Dict[str,str]]={},
	brs_overrides: Optional[Dict[str, str]]={},
	scenario: Optional[str]=None,
	should_persist_and_reset: Optional[bool]=True) -> requests.models.Response:
		if should_persist_and_reset:
			brs_overrides = {**brs_overrides, **self.brs_overrides_static_uri_overrides}
			self.set_brs_overrides_and_persist(brs_overrides=brs_overrides)
		host = f"{host_prefix}-onenote.officeapps.live.com" if host_prefix is not None else "onenote.officeapps.live.com"
		host = host_override if host_override is not None else host
		request_url = self.discovery_base_url_template.format(host)
		request_headers = {**self.cache_invalidation_header, **additional_headers}
		response = requests.get(request_url, headers=request_headers, params=query_params)
		if scenario is not None:
			self.log_response(test_name=scenario, request_url=request_url, request_headers=request_headers,
				brs_overrides=brs_overrides, discovery_xml=response.text,
				request_query_params=query_params)
		return response

	"""Output the response to a vanilla file for folks to review in PR
	"""
	def log_response(self, test_name: str, request_url: str, request_headers: Dict[str, str], brs_overrides: Dict[str, str], discovery_xml: str,
		request_query_params: Dict[str, str]=None) -> None:
		templated_entry = ""
		templated_entry += f"# Test name\n```\n{test_name}\n```\n\n"
		templated_entry += f"# Request URL\n```\n{request_url}\n```\n\n"
		templated_entry += "# Request query parameters\n```\n{0}\n```\n\n".format(pformat(request_query_params))
		templated_entry += "# Request headers\n```\n{0}\n```\n\n".format(pformat(request_headers))
		templated_entry += "# BRS overrides\n```ini\n"
		for key, value in brs_overrides.items():
			templated_entry += f"{key}={value}\n"
		templated_entry += "```\n\n"
		discovery_xml = self.generate_xml_response(discovery_xml=discovery_xml)
		templated_entry += "# Discovery response\n```xml\n{0}\n```\n\n\n---\n\n\n".format(discovery_xml)
		self.log_filehandle.write(templated_entry)

	def generate_xml_response(self, discovery_xml: str) -> str:
		dom = xml.dom.minidom.parseString(discovery_xml)
		return dom.toprettyxml()

	"""Sanity checking the URL prefixes 
	"""
	def sanity_check_url_prefix(self, response: Dict[str, Any], expected_url_regex: str, attribs_to_check: Set[str], apps_to_skip: Set[str]=set()) -> None:
		for app in response:
			if app in apps_to_skip:
				continue
			app_dict = response[app]
			for attrib_key in app_dict:
				if isinstance(attrib_key, str) and attrib_key in attribs_to_check:
					anticipated_url = app_dict[attrib_key]
					match = re.match(expected_url_regex, anticipated_url)
					self.assertIsNotNone(match)
				# Per the dictionary example below, only expect one level of nesting
				else:
					action_dict = app_dict[attrib_key]
					for key in action_dict:
						if key in attribs_to_check:
							anticipated_url = action_dict[key]
							match = re.match(expected_url_regex, anticipated_url)
							self.assertIsNotNone(match)

	"""Making sure *everything* in CSPP discovery is in onenote discovery for the DC of interest,
	or the global subdomain
	"""
	def sanity_check_cspp_and_onenote_parity(self, cspp_response: Dict[str, Any],
	onenote_response: Dict[str, Any]) -> None:
		for app in cspp_response:
			self.assertIn(app, onenote_response)
			cspp_dict = cspp_response[app]
			onenote_dict = onenote_response[app]
			for attrib_key in cspp_dict:
				self.assertIn(attrib_key, onenote_dict)
				# don't really care about the value type (dict or str), we can compare either or
				# for equality
				self.assertEqual(cspp_dict[attrib_key], onenote_dict[attrib_key])

	"""Making sure only the supported attributes are in here, with any optional overrides
	"""
	def sanity_check_cspp_response(self, cspp_response: Dict[str, Any], is_cspp_plus: Optional[bool]=False,
	supported_cspp_apps: Optional[Set[str]]=None, supported_cspp_attribs: Optional[Set[str]]=None,
	supported_cspp_actions: Optional[Set[str]]=None, supported_csppplus_actions: Optional[Set[str]]=None) -> None:
		if supported_cspp_apps is None:
			supported_cspp_apps = self.supported_cspp_apps
		if supported_cspp_attribs is None:
			supported_cspp_attribs = self.supported_cspp_attribs
		if supported_cspp_actions is None:
			supported_cspp_actions = self.supported_cspp_actions
		if supported_csppplus_actions is None:
			supported_csppplus_actions = self.supported_csppplus_actions
		for app in cspp_response:
			self.assertIn(app, supported_cspp_apps)
			app_dict = cspp_response[app]
			for attrib_key in app_dict:
				# Per the docstrings below, the WOPI actions are tuples
				if not isinstance(attrib_key, tuple):
					self.assertIn(attrib_key, supported_cspp_attribs)
				elif is_cspp_plus:
					self.assertTrue(attrib_key[0] in supported_cspp_actions or attrib_key[0] in supported_csppplus_actions)
				else:
					self.assertIn(attrib_key[0], supported_cspp_actions)

	def assert_against_in_memory_cache_value(self, headers: requests.structures.CaseInsensitiveDict, val: str) -> None:
		self.assertIn(self.in_memory_cache_header, headers)
		self.assertEqual(val, headers[self.in_memory_cache_header])

	def assert_against_cache_time(self, headers: requests.structures.CaseInsensitiveDict,
		expected_cache_time: Optional[int]=1800, expect_less_than: bool=False) -> None:
		cache_control_header = headers['Cache-Control']
		regexp_result = self.cache_control_exp.match(cache_control_header)
		if expect_less_than:
			self.assertTrue(expected_cache_time > int(regexp_result[1]))
		else:
			self.assertEqual(expected_cache_time, int(regexp_result[1]))

	"""Response example:
	{
		"Excel": {
			"name": "Excel",
			"favIconUrl": "http://c1-excel-15.cdn.office.net/x/_layouts/resources/FavIcon_Excel.ico",
			"checkLicense": "true"
			("view", "csv"): {
				"name": "view",
				"ext": "csv",
				"default": "true"
				"urlsrc": ...
			},
			("view", "ods"): {
				...
			}
		}
	}
	"""
	def create_dict_from_discovery_response(self, discovery_xml: str) -> Dict[str, Any]:
		response_dict = dict()
		root = ET.fromstring(discovery_xml)
		for app in root.iter('app'):
			app_name = app.attrib["name"]
			single_app = dict()
			single_app.update(app.attrib)
			for action in app.iter('action'):
				key_suffix = None
				if "ext" in action.attrib:
					key_suffix = action.attrib["ext"]
				else:
					key_suffix = action.attrib["progid"]
				action_key = (action.attrib["name"], key_suffix)
				single_app[action_key] = action.attrib
			response_dict[app_name] = single_app
		return response_dict

	"""BRS overrides for list types.
	CSPPOnlyWOPIActions=(System.Collections.Generic.List`1[System.String])<List><Value>edit</Value></List>
	"""
	def fetch_brs_override_for_list_types(self, *list_args) -> str:
		final_override = "(System.Collections.Generic.List`1[System.String])<List>"
		for arg in list_args:
			final_override += f"<Value>{arg}</Value>"
		final_override += "</List>"
		return final_override

	"""Can't use configparser that ships with standard lib because there are no sections in
	brs.ini, so simply overwrite it every time
	"""
	def set_brs_overrides_and_persist(self, brs_overrides: Dict[str, str]) -> None:
		templated_ini = ""
		for key, value in brs_overrides.items():
			templated_ini += f"{key}={value}\n"
		ini_filehandle = open(self.path_to_brs_ini, "w")
		ini_filehandle.write(templated_ini)
		ini_filehandle.close()
		self.iisreset()

	@classmethod
	def rebuild(self, ref: Optional[str]="user/cgonzales/cspp-discovery-drop") -> None:
		if ref != "user/cgonzales/cspp-discovery-drop":
			self.should_rebuild = True
		exit_code = os.system(f"git checkout {ref}")
		if exit_code != 0:
			raise AssertionError()
		exit_code = os.system("ohome build inc debug failfast")
		if exit_code != 0:
			raise AssertionError()
		# I think "wac stop all" is implicit if "wac clean" is invoked"
		exit_code = os.system("wac clean")
		if exit_code != 0:
			raise AssertionError()
		exit_code = os.system("wac start all")
		if exit_code != 0:
			raise AssertionError()

	"""This might not budge on the first time, so continue to do it until it does (usually just
	twice)
	"""
	def iisreset(self) -> None:
		exit_code = -1
		while exit_code != 0:
			exit_code = os.system("iisreset")

if __name__ == '__main__':
    unittest.main()
