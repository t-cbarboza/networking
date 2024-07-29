import email.utils
from datetime import datetime
from datetime import timedelta
import os
from pprint import pformat
import queue
import re
import requests
import sys
import threading
import time
import traceback
from typing import Any
from typing import Dict
from typing import Set
from typing import Optional
import unittest

r"""Must be ran in current enlistment shell. Aside from the suggested workflow below, you must also be on the feature branch in question and have already built it.
	To use your python installment out of the box, simply enter the following (see more here: https://docs.python.org/3/library/venv.html#creating-virtual-environments):
	python -m venv c:\path\to\myenv
	c:\path\to\myenv\Scripts\activate.bat
	c:\path\to\myenv\Scripts\pip3.exe install requests
	c:\path\to\myenv\Scripts\python.exe c:\path\to\this\script\ocdi-arr-testing.py

	OR to run an individual unit test,
	c:\path\to\myenv\Scripts\python.exe -m unittest c:\path\to\this\script\discovery-tests.py -k <name-of-test>
"""
class OcdiArrUrlRewriteTests(unittest.TestCase):
	path_to_brs_ini = "C:\\hosted\\Data\\Local\\brs.ini"
	brs_overrides_base = {
		"MachineFunctionsEnabledForOCDIRouting": "(System.String)SingleBox",
		"OCDIAppHomeStaticContentServiceIsEnabled": "(System.Boolean)True",
		"OCDIAppHomeStaticContentCachingIsEnabled": "(System.Boolean)True",
		"WacCloudPortalIsDotNetCoreRunning": "(System.Boolean)True",
		"WacCloudPortalProofOfConceptIsEnabled": "(System.Boolean)True",
		"OCDIAppHomeStaticContentCorrelationIdFixEnabled": "(System.Boolean)True",
		"OCDIAppHomeStaticContentShouldLogImportant": "(System.Boolean)True",
		"EncryptionInTransit_ShouldUseCustomCertValidator_HttpClient_WacCloudPortal": "(System.Boolean)True",
		"EncryptionInTransit_ServiceEncryption_AllowList": "(System.Collections.Generic.List`1[System.String])<List><Value>ApplicationFeatureHelperService</Value><Value>WacCloudPortal</Value><Value>WacCloudPortal_DotNetFramework</Value></List>"
	}

	etc_hosts = """127.0.0.1 word-view.devpr.officeapps.live-int.com 
127.0.0.1 word-edit.devpr.officeapps.live-int.com 
127.0.0.1 testhost.devpr.officeapps.live-int.com 
127.0.0.1 excel.devpr.officeapps.live-int.com 
127.0.0.1 onenote.devpr.officeapps.live-int.com 
127.0.0.1 powerpoint.devpr.officeapps.live-int.com 
127.0.0.1 onenote.devpr.officeapps.live-int.com 
127.0.0.1 visio.devpr.officeapps.live-int.com   
127.0.0.1 word-view-devpr.officeapps-int.live-ppe.net 
127.0.0.1 word-edit-devpr.officeapps-int.live-ppe.net 
127.0.0.1 officeapps-devpr.officeapps-int.live-ppe.net 
127.0.0.1 powerpoint-devpr.officeapps-int.live-ppe.net 
127.0.0.1 excel-devpr.officeapps-int.live-ppe.net 
127.0.0.1 onenote-devpr.officeapps-int.live-ppe.net 
127.0.0.1 visio-devpr.officeapps-int.live-ppe.net
127.0.0.1 devpr.officeapps.live-int.com
127.0.0.1 devpr.officeapps-int.live-ppe.net
127.0.0.1 testhost-devpr.officeapps-int.live-ppe.net 
127.0.0.1 oauth.devpr.officeapps.live-int.com
127.0.0.1 oauth-devpr.officeapps-int.live-ppe.net

127.0.0.1       word.cloud.microsoft
127.0.0.1       excel.cloud.microsoft
127.0.0.1       powerpoint.cloud.microsoft
127.0.0.1       df.word.cloud.microsoft
127.0.0.1       df.excel.cloud.microsoft
127.0.0.1       df.powerpoint.cloud.microsoft
127.0.0.1       word.cloud-dev.microsoft
127.0.0.1       excel.cloud-dev.microsoft
127.0.0.1       powerpoint.cloud-dev.microsoft
127.0.0.1       bogus.cloud-dev.microsoft
"""
	etc_hosts_path = "C:\\Windows\\System32\\drivers\\etc\\hosts"
	allowed_assets = set(["config.js", "auth.html"])
	fqdn_to_resource_name_mapping = {
			"word.cloud-dev.microsoft": "wordindex.html",
			"df.word.cloud.microsoft": "wordindex.html",
			"excel.cloud-dev.microsoft": "excelindex.html",
			"df.excel.cloud.microsoft": "excelindex.html",
			"powerpoint.cloud-dev.microsoft": "powerpointindex.html",
			"df.powerpoint.cloud.microsoft": "powerpointindex.html",
			"word.cloud.microsoft": "wordindex.html",
			"excel.cloud.microsoft": "excelindex.html",
			"powerpoint.cloud.microsoft": "powerpointindex.html"
	}
	fqdn_to_cdn_host_mapping = {
			"word.cloud-dev.microsoft": "res-dev.cdn.officeppe.net",
			"df.word.cloud.microsoft": "res-sdf.cdn.office.net",
			"word.cloud.microsoft": "res.cdn.office.net",
			"excel.cloud-dev.microsoft": "res-dev.cdn.officeppe.net",
			"df.excel.cloud.microsoft": "res-sdf.cdn.office.net",
			"excel.cloud.microsoft": "res.cdn.office.net",
			"powerpoint.cloud-dev.microsoft": "res-dev.cdn.officeppe.net",
			"df.powerpoint.cloud.microsoft": "res-sdf.cdn.office.net",
			"powerpoint.cloud.microsoft": "res.cdn.office.net"
	}

	config_js_regex = re.compile(r'window\.configuration={environmentName:"(?:dogfood|production|fastfood)",buildVersion:"[0-9\.]+"};')
	cache_control_exp = re.compile(".*max-age=([0-9]+).*")

	stubbed_headers = {
		"X-FD-Ref": "Ref A: C0DCF8AD66014CD28F8B621AD77D8FBE Ref B: MRS211050618011 Ref C: 2024-06-27T18:29:37Z",
	}

	stubbed_query_params = {
		"wdOrigin": "MARKETING.EXCEL.SIGNIN"
	}

	should_reset_brs = False
	succeeded_for_multithreaded_test = True

	@classmethod
	def setUpClass(cls):
		cls.set_brs_overrides_and_persist(brs_overrides=cls.brs_overrides_base)
		etc_hosts_fh = open(cls.etc_hosts_path, "w")
		etc_hosts_fh.write(cls.etc_hosts)
		etc_hosts_fh.close()

	@classmethod
	def tearDownClass(cls):
		etc_hosts_fh = open(cls.etc_hosts_path, "w")
		etc_hosts_fh.close()

	def setUp(self):
		self.succeeded_for_multithreaded_test = True
		if self.should_reset_brs:
			self.set_brs_overrides_and_persist(brs_overrides=self.brs_overrides_base)
			self.should_reset_brs = False

	def test_canonical_case_for_seo(self):
		print(f"Running test: {self.test_canonical_case_for_seo.__name__}")
		self.ping()
		for cloud_microsoft_host in self.fqdn_to_cdn_host_mapping:
			cdn_host = self.fqdn_to_cdn_host_mapping[cloud_microsoft_host]
			# TODO: Delete this condition once this is provisioned in PPE environments
			if cdn_host != "res.cdn.office.net":
				continue
			# TODO: Uncomment me once this works
			#for asset in ["robots.txt", "sitemap.xml"]:
			for asset in ["sitemap.xml"]:
				app_prefix = "word"
				if "excel" in cloud_microsoft_host:
					app_prefix = "excel"
				elif "powerpoint" in cloud_microsoft_host:
					app_prefix = "powerpoint"
				fq_cdn_url = "https://{0}/apphome/{1}{2}".format(cdn_host, app_prefix, asset)
				fq_wac_url = "https://{0}:82/{1}".format(cloud_microsoft_host, asset)
				cdn_response = requests.get(fq_cdn_url)
				wac_response = requests.get(fq_wac_url, verify=False, headers=self.stubbed_headers, params=self.stubbed_query_params)
				self.cdn_and_wacsrv_request_parity(cdn_response=cdn_response, wac_response=wac_response)

	def test_canonical_case_rules_and_service_lit_up(self):
		print(f"Running test: {self.test_canonical_case_rules_and_service_lit_up.__name__}")
		self.ping()
		for cloud_microsoft_host in self.fqdn_to_cdn_host_mapping:
			cdn_host = self.fqdn_to_cdn_host_mapping[cloud_microsoft_host]
			resource_in_question = self.fqdn_to_resource_name_mapping[cloud_microsoft_host]
			fq_cdn_url = "https://{0}/apphome/{1}".format(cdn_host, resource_in_question)
			fq_wac_url = "https://{0}:82/".format(cloud_microsoft_host)
			cdn_response = requests.get(fq_cdn_url)
			wac_response = requests.get(fq_wac_url, verify=False, headers=self.stubbed_headers, params=self.stubbed_query_params)
			self.cdn_and_wacsrv_request_parity(cdn_response=cdn_response, wac_response=wac_response)
			for asset in self.allowed_assets:
				fq_cdn_url = "https://{0}/apphome/{1}".format(cdn_host, asset)
				fq_wac_url = "https://{0}:82/{1}".format(cloud_microsoft_host, asset)
				cdn_response = requests.get(fq_cdn_url)
				wac_response = requests.get(fq_wac_url, verify=False, headers=self.stubbed_headers, params=self.stubbed_query_params)
				self.cdn_and_wacsrv_request_parity(cdn_response=cdn_response, wac_response=wac_response)

	@unittest.skip("TODO: Skip me until this change gets checked in.")
	def test_diagnostics_netfx_works_as_expected(self):
		print(f"Running test: {self.test_diagnostics_netfx_works_as_expected.__name__}")
		self.ping()
		for cloud_microsoft_host in self.fqdn_to_cdn_host_mapping:
			cdn_host = self.fqdn_to_cdn_host_mapping[cloud_microsoft_host]
			resource_in_question = self.fqdn_to_resource_name_mapping[cloud_microsoft_host]
			fq_wac_url = "https://{0}:82/".format(cloud_microsoft_host)
			wac_response = requests.get(fq_wac_url, verify=False, headers=self.stubbed_headers, params=self.stubbed_query_params)
			self.assertEqual(wac_response.status_code, 200)
			for asset in self.allowed_assets:
				fq_wac_url = "https://{0}:82/{1}".format(cloud_microsoft_host, asset)
				wac_response = requests.get(fq_wac_url, verify=False, headers=self.stubbed_headers, params=self.stubbed_query_params)
				self.assertEqual(wac_response.status_code, 200)
		# Same box, should be the same amount here
		query_params_for_diag = { **self.stubbed_query_params, "diag": "1" }
		wac_response = requests.get("https://word.cloud.microsoft:82/", verify=False, params=query_params_for_diag)
		diag = wac_response.json()
		self.assertEqual(diag["TotalCacheEntries"], 15)

	@unittest.skip("TODO: Skip me until this change gets checked in.")
	def test_diagnostics_dotnet_works_as_expected(self):
		print(f"Running test: {self.test_diagnostics_dotnet_works_as_expected.__name__}")
		self.ping()
		for cloud_microsoft_host in self.fqdn_to_cdn_host_mapping:
			cdn_host = self.fqdn_to_cdn_host_mapping[cloud_microsoft_host]
			resource_in_question = self.fqdn_to_resource_name_mapping[cloud_microsoft_host]
			fq_wac_url = "https://{0}:7012/wcp/AppHomeStaticContentHandler.ashx".format(cloud_microsoft_host)
			wac_response = requests.get(fq_wac_url, verify=False, headers=self.stubbed_headers, params=self.stubbed_query_params)
			self.assertEqual(wac_response.status_code, 200)
			for asset in self.allowed_assets:
				fq_wac_url = "https://{0}:7012/wcp/AppHomeStaticContentHandler.ashx?resource={1}".format(cloud_microsoft_host, asset)
				wac_response = requests.get(fq_wac_url, verify=False, headers=self.stubbed_headers, params=self.stubbed_query_params)
				self.assertEqual(wac_response.status_code, 200)
		# Same box, should be the same amount here
		query_params_for_diag = { **self.stubbed_query_params, "diag": "1" }
		wac_response = requests.get("https://word.cloud.microsoft:7012/wcp/AppHomeStaticContentHandler.ashx", verify=False, params=query_params_for_diag)
		diag = wac_response.json()
		self.assertEqual(diag["TotalCacheEntries"], 15)

	def test_routing_not_borked_for_arbitrary_wachosts_service(self):
		print(f"Running test: {self.test_routing_not_borked_for_arbitrary_wachosts_service.__name__}")
		self.ping("http://localhost:80/suite/WebLoader.aspx?health=1")
		arbitrary_url_template = "http://{0}:80/suite/WebLoader.aspx?env=FASTFOOD&filetype=Excel&hostorigin=http://excel.cloud-dev.microsoft"
		response_evaluated_normally = requests.get(arbitrary_url_template.format("localhost"))
		response_evaluated_new_url_rewrite_rule = requests.get(arbitrary_url_template.format("word.cloud.microsoft"))
		self.wac_service_parity(old_response=response_evaluated_normally, new_response=response_evaluated_new_url_rewrite_rule)

	def test_rewrite_rule_not_mutating_requests_when_turned_off(self):
		print(f"Running test: {self.test_rewrite_rule_not_mutating_requests_when_turned_off.__name__}")
		self.set_brs_overrides_and_persist(brs_overrides={})
		self.ping()
		for cloud_microsoft_host in self.fqdn_to_cdn_host_mapping:
			fq_wac_url = "https://{0}:82/".format(cloud_microsoft_host)
			wac_response = requests.get(fq_wac_url, verify=False)
			self.assertEqual(wac_response.status_code, 200)
			self.assertTrue("<title>Login | Microsoft 365</title>" in wac_response.text)
			for asset in self.allowed_assets:
				fq_wac_url = "https://{0}:82/{1}".format(cloud_microsoft_host, asset)
				wac_response = requests.get(fq_wac_url, verify=False)
				self.assertEqual(wac_response.status_code, 404)
		self.should_reset_brs = True

	def test_watched_config_works_the_way_we_expect_in_rewrite_and_iis_returns_404(self):
		print(f"Running test: {self.test_watched_config_works_the_way_we_expect_in_rewrite_and_iis_returns_404.__name__}")
		brs_overrides = { **self.brs_overrides_base }
		# Don't allowlist auth.html/config.js as a sanity check - our WatchedConfigSetting should catch this
		brs_overrides["OCDIAppHomeStaticContentAllowedAssets"] = self.fetch_brs_override_for_list_types("wordindex.html", "excelindex.html", "powerpointindex.html")
		#self.set_brs_overrides_and_persist(brs_overrides, should_bounce=False)
		self.set_brs_overrides_and_persist(brs_overrides, should_bounce=True)
		self.ping()
		# Not sure why, but IIS behaves weird here and bouncing it makes it happy. So let's do an iisreset and still (sort of) prove the concept
		# with our WatchedConfigSetting in the rewrite rule
		#self.bounce_iis()
		for cloud_microsoft_host in self.fqdn_to_cdn_host_mapping:
			cdn_host = self.fqdn_to_cdn_host_mapping[cloud_microsoft_host]
			resource_in_question = self.fqdn_to_resource_name_mapping[cloud_microsoft_host]
			fq_cdn_url = "https://{0}/apphome/{1}".format(cdn_host, resource_in_question)
			fq_wac_url = "https://{0}:82/{1}".format(cloud_microsoft_host, resource_in_question)
			cdn_response = requests.get(fq_cdn_url)
			wac_response = requests.get(fq_wac_url, verify=False, headers=self.stubbed_headers, params=self.stubbed_query_params)
			self.cdn_and_wacsrv_request_parity(cdn_response=cdn_response, wac_response=wac_response)
			for asset in self.allowed_assets:
				fq_wac_url = "https://{0}:82/{1}".format(cloud_microsoft_host, asset)
				wac_response = requests.get(fq_wac_url, verify=False, headers=self.stubbed_headers, params=self.stubbed_query_params)
				self.assertEqual(404, wac_response.status_code)
		self.should_reset_brs = True

	def test_in_memory_caching_works_with_cache_timeout_override(self):
		print(f"Running test: {self.test_in_memory_caching_works_with_cache_timeout_override.__name__}")
		brs_overrides = { **self.brs_overrides_base }
		brs_overrides["OCDIAppHomeStaticContentBoundedStalenessEnabled"] = "(System.Boolean)True"
		brs_overrides["OCDIAppHomeStaticContentBoundedStalenessInSeconds"] = "(System.Int32)25"
		self.set_brs_overrides_and_persist(brs_overrides, should_bounce=False)
		self.bounce_iis()
		self.ping()
		all_threads = list()
		for base_url_host in self.fqdn_to_resource_name_mapping:
			fq_url = "https://{0}:82/".format(base_url_host)
			t1 = threading.Thread(target=self.make_http_request_for_caching, args=(fq_url,))
			t1.start()
			all_threads.append(t1)
			for asset in self.allowed_assets:
				fq_url = "https://{0}:82/{1}".format(base_url_host, asset)
				t1 = threading.Thread(target=self.make_http_request_for_caching, args=(fq_url,))
				t1.start()
				all_threads.append(t1)
		for t1 in all_threads:
			t1.join()
		self.assertTrue(self.succeeded_for_multithreaded_test)
		self.should_reset_brs = True

	def test_httpclient_timeout_works_by_timing_out_every_request(self):
		print(f"Running test: {self.test_httpclient_timeout_works_by_timing_out_every_request.__name__}")
		brs_overrides = { **self.brs_overrides_base }
		brs_overrides["OCDIAppHomeStaticContentHttpClientTimeoutInMilliseconds"] = "(System.Int32)1"
		self.set_brs_overrides_and_persist(brs_overrides, should_bounce=False)
		self.bounce_iis()
		self.ping()
		wac_response = requests.get("https://word.cloud.microsoft:82", verify=False, headers=self.stubbed_headers, params=self.stubbed_query_params)
		self.assertEqual(wac_response.status_code, 500)
		self.should_reset_brs = True

	def test_dotnet_version_smoke_test(self):
		print(f"Running test: {self.test_dotnet_version_smoke_test.__name__}")
		brs_overrides = { **self.brs_overrides_base }
		brs_overrides["OCDIAppHomeStaticContentBoundedStalenessEnabled"] = "(System.Boolean)True"
		brs_overrides["OCDIAppHomeStaticContentBoundedStalenessInSeconds"] = "(System.Int32)25"
		self.set_brs_overrides_and_persist(brs_overrides)
		all_threads = list()
		for base_url_host in self.fqdn_to_resource_name_mapping:
			fq_url = "https://{0}:7012/wcp/AppHomeStaticContentHandler.ashx".format(base_url_host)
			t1 = threading.Thread(target=self.make_http_request_for_caching, args=(fq_url,))
			t1.start()
			all_threads.append(t1)
			for asset in self.allowed_assets:
				fq_url = "https://{0}:7012/wcp/AppHomeStaticContentHandler.ashx?resource={1}".format(base_url_host, asset)
				t1 = threading.Thread(target=self.make_http_request_for_caching, args=(fq_url,))
				t1.start()
				all_threads.append(t1)
		for t1 in all_threads:
			t1.join()
		self.assertTrue(self.succeeded_for_multithreaded_test)
		self.should_reset_brs = True

	def test_dotnet_http_still_works(self):
		print(f"Running test: {self.test_dotnet_http_still_works.__name__}")
		brs_overrides = { **self.brs_overrides_base }
		brs_overrides["OCDIAppHomeStaticContentBoundedStalenessEnabled"] = "(System.Boolean)True"
		brs_overrides["OCDIAppHomeStaticContentBoundedStalenessInSeconds"] = "(System.Int32)25"
		self.set_brs_overrides_and_persist(brs_overrides)
		all_threads = list()
		for base_url_host in self.fqdn_to_resource_name_mapping:
			fq_url = "http://{0}:5012/wcp/AppHomeStaticContentHandler.ashx".format(base_url_host)
			t1 = threading.Thread(target=self.make_http_request_for_caching, args=(fq_url,))
			t1.start()
			all_threads.append(t1)
			for asset in self.allowed_assets:
				fq_url = "http://{0}:5012/wcp/AppHomeStaticContentHandler.ashx?resource={1}".format(base_url_host, asset)
				t1 = threading.Thread(target=self.make_http_request_for_caching, args=(fq_url,))
				t1.start()
				all_threads.append(t1)
		for t1 in all_threads:
			t1.join()
		self.assertTrue(self.succeeded_for_multithreaded_test)
		self.should_reset_brs = True

	def test_netfx_http_still_works(self):
		print(f"Running test: {self.test_netfx_http_still_works.__name__}")
		self.ping()
		for cloud_microsoft_host in self.fqdn_to_cdn_host_mapping:
			cdn_host = self.fqdn_to_cdn_host_mapping[cloud_microsoft_host]
			resource_in_question = self.fqdn_to_resource_name_mapping[cloud_microsoft_host]
			fq_cdn_url = "https://{0}/apphome/{1}".format(cdn_host, resource_in_question)
			fq_wac_url = "http://{0}:80/".format(cloud_microsoft_host)
			cdn_response = requests.get(fq_cdn_url)
			wac_response = requests.get(fq_wac_url, verify=False, headers=self.stubbed_headers, params=self.stubbed_query_params)
			self.cdn_and_wacsrv_request_parity(cdn_response=cdn_response, wac_response=wac_response)
			for asset in self.allowed_assets:
				fq_cdn_url = "https://{0}/apphome/{1}".format(cdn_host, asset)
				fq_wac_url = "http://{0}:80/{1}".format(cloud_microsoft_host, asset)
				cdn_response = requests.get(fq_cdn_url)
				wac_response = requests.get(fq_wac_url, verify=False, headers=self.stubbed_headers, params=self.stubbed_query_params)
				self.cdn_and_wacsrv_request_parity(cdn_response=cdn_response, wac_response=wac_response)

	@unittest.skip("This works locally but hangs in the script...")
	def test_wcp_netfx_version_smoke_test(self):
		print(f"Running test: {self.test_wcp_netfx_version_smoke_test.__name__}")
		brs_overrides = { **self.brs_overrides_base }
		brs_overrides["OCDIAppHomeStaticContentBoundedStalenessEnabled"] = "(System.Boolean)True"
		brs_overrides["OCDIAppHomeStaticContentBoundedStalenessInSeconds"] = "(System.Int32)25"
		self.set_brs_overrides_and_persist(brs_overrides, should_bounce=False)
		self.bounce_iis()
		all_threads = list()
		for base_url_host in self.fqdn_to_resource_name_mapping:
			fq_url = "https://{0}:82/wcp/AppHomeStaticContentHandler.ashx".format(base_url_host)
			t1 = threading.Thread(target=self.make_http_request_for_caching, args=(fq_url,))
			t1.start()
			all_threads.append(t1)
			for asset in self.allowed_assets:
				fq_url = "https://{0}:82/wcp/AppHomeStaticContentHandler.ashx?resource={1}".format(base_url_host, asset)
				t1 = threading.Thread(target=self.make_http_request_for_caching, args=(fq_url,))
				t1.start()
				all_threads.append(t1)
		for t1 in all_threads:
			t1.join()
		self.assertTrue(self.succeeded_for_multithreaded_test)
		self.should_reset_brs = True

	def make_http_request_for_caching(self, fq_url: str) -> None:
		try:
			wac_response = requests.get(fq_url, verify=False, headers=self.stubbed_headers, params=self.stubbed_query_params)
			now_plus_fifteen = datetime.now() + timedelta(seconds=15)
			self.assertEqual(wac_response.status_code, 200)
			last_age = 0
			if "Age" in wac_response.headers:
				last_age = int(wac_response.headers["Age"])
			while datetime.now().timestamp() < now_plus_fifteen.timestamp():
				wac_response = requests.get(fq_url, verify=False, headers=self.stubbed_headers, params=self.stubbed_query_params)
				self.assertEqual(wac_response.status_code, 200)
				if "Age" not in wac_response.headers:
					time.sleep(1)
					continue
				age = int(wac_response.headers["Age"])
				self.assertTrue(last_age <= age)
				last_age = age
				time.sleep(1)
			time.sleep(15)
			wac_response = requests.get(fq_url, verify=False, headers=self.stubbed_headers, params=self.stubbed_query_params)
			self.assertEqual(wac_response.status_code, 200)
			if "Age" in wac_response.headers:
				age = int(wac_response.headers["Age"])
				self.assertTrue(age < last_age)
		except Exception:
			lock = threading.Lock()
			with lock:
				extype, exc, tb = sys.exc_info()
				traceback.print_exception(extype, exc, tb)
				del extype, exc, tb
				self.succeeded_for_multithreaded_test = False

	def fetch_max_age_from_header(self, headers: requests.structures.CaseInsensitiveDict) -> int:
		cache_control_header = headers["Cache-Control"]
		regexp_result = self.cache_control_exp.match(cache_control_header)
		max_age = int(regexp_result[1])
		return max_age

	def wac_service_parity(self,
	old_response: requests.models.Response,
	new_response: requests.models.Response) -> None:
		self.assertEqual(old_response.status_code, 200)
		self.assertEqual(old_response.status_code, new_response.status_code)
		for header_name in old_response.headers:
			self.assertIn(header_name, new_response.headers)

	"""
	Very crude and ugly :(
	Could potentially be flaky 1% of the time
	"""
	def cdn_and_wacsrv_request_parity(self,
	cdn_response: requests.models.Response,
	wac_response: requests.models.Response) -> None:
		if "robots.txt" in cdn_response.text \
		or wac_response.url.endswith("robots.txt") \
		or wac_response.url.endswith("sitemap.xml"):
			self.assertEqual(cdn_response.text, wac_response.text)
		elif cdn_response.headers["Content-Type"] == "application/javascript":
			cdn_match = self.config_js_regex.match(cdn_response.text)
			wac_match = self.config_js_regex.match(wac_response.text)
			self.assertIsNotNone(cdn_match)
			self.assertIsNotNone(wac_match)
		self.assertEqual(cdn_response.status_code, 200)
		self.assertEqual(cdn_response.status_code, wac_response.status_code)
		for header_name in cdn_response.headers:
			#self.assertIn(header_name, wac_response.headers)
			if header_name not in wac_response.headers:
				print("Header {0} not found in the response from WAC".format(header_name))

	"""BRS overrides for list types.
	CSPPOnlyWOPIActions=(System.Collections.Generic.List`1[System.String])<List><Value>edit</Value></List>
	"""
	def fetch_brs_override_for_list_types(self, *list_args) -> str:
		final_override = "(System.Collections.Generic.List`1[System.String])<List>"
		for arg in list_args:
			final_override += f"<Value>{arg}</Value>"
		final_override += "</List>"
		return final_override

	"""For some odd reason, we need an initial ping for IIS when using the HTTPS port. We get transient errors with IIS locally (it struggles sometimes). See more here:
	https://stackoverflow.com/a/2972662
	"""
	def ping(self, url: str="https://word.cloud.microsoft:82?health=1") -> None:
		retries_attempted = 0
		max_retries = 10
		time_to_sleep = 1
		succeeded = False
		last_exception_observed = Exception("Ping failed!")
		while not succeeded and retries_attempted < max_retries:
			try:
				print("Pinging...")
				response = requests.get(url, verify=False)
				succeeded = response.status_code == 200
			except Exception as e:
				last_exception_observed = e
			retries_attempted += 1
			time.sleep(time_to_sleep)
			time_to_sleep *= 2
		if not succeeded:
			raise last_exception_observed

	"""Can't use configparser that ships with standard lib because there are no sections in
	brs.ini, so simply overwrite it every time
	"""
	@classmethod
	def set_brs_overrides_and_persist(self, brs_overrides: Dict[str, str], should_bounce: bool=True) -> None:
		templated_ini = ""
		for key, value in brs_overrides.items():
			templated_ini += f"{key}={value}\n"
		ini_filehandle = open(self.path_to_brs_ini, "w")
		ini_filehandle.write(templated_ini)
		ini_filehandle.close()
		if should_bounce:
			#self.iisreset()
			self.bounce_wac()

	@classmethod
	def bounce_wac(self) -> None:
		exit_code = os.system(f"wac stop")
		if exit_code != 0:
			raise AssertionError()
		exit_code = os.system(f"wac start all")
		if exit_code != 0:
			raise AssertionError()

	def bounce_iis(self) -> None:
		exit_code = -1
		while exit_code != 0:
			exit_code = os.system("iisreset")

if __name__ == '__main__':
    unittest.main()
