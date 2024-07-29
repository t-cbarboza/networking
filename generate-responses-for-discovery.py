import os
from pprint import pprint
import re
import requests
from requests.models import Response
from typing import Any
from typing import Set
import xml.etree.ElementTree as ET
import yaml

"""Quick and dirty script - intended to be ran from the root directory of this repository:
https://office.visualstudio.com/DefaultCollection/OC/_git/Officeonline.GenevaSynthetics

This is extraordinarily ugly and inefficient - "quick and dirty"
"""

max_retries = 10

def return_config(is_prod: bool=True) -> dict[Any, Any]:
	file_suffix = "Prod"
	if not is_prod:
		file_suffix = "Test"
	config = None
	with open(f"ConfigGenerator/Configs/Config-{file_suffix}.yaml", "r") as stream:
		config = yaml.safe_load(stream)
	config = config['DcGroups']
	del config['blackforestDC']
	del config['globalExcelTelemetryDC']
	del config['globalPowerpointTelemetryDC']
	del config['globalWordTelemetryDC']
	del config['noARRFastfoodDcs']
	return config

def return_compliance_regex_config(is_prod: bool=True) -> dict[Any, Any]:
	compliance_dict = dict()
	file_suffix = "Prod"
	if not is_prod:
		file_suffix = "Test"
	config = None
	with open(f"ConfigGenerator/Configs/Config-{file_suffix}.yaml", "r") as stream:
		config = yaml.safe_load(stream)
	config = config["Compliance"]["ComplianceDatacenterPairs"]
	for pair in config:
		region = pair["RequestedDc"]
		regex = pair["ResponseDc"].replace("$", "")
		compliance_dict[region] = regex
	return compliance_dict

def fetch_response(request_uri: str) -> Response:
	print(f"Generating response for {request_uri}")
	i = 0
	r = None
	while i < max_retries and (r is None or r.status_code != 200):
		i += 1
		try:
			r = requests.get(request_uri, timeout=10)
			if r.status_code != 200:
				print(f"Could not fetch response for {request_uri}, status code {r.status_code}. Retries left: {str(max_retries - i)}")
		except Exception as e:
			print(f"Exception observed when fetching {request_uri}: {str(e)}. Retries left: {str(max_retries - i)}")
	return r

def populate_state_with_urls(config: dict[Any, Any], all_urls: Set[str], domain_to_dc_mapping: dict[str, Set[str]], compliance_regexes: dict[str, str]) -> None:
	for dc_group in config:
		domain = config[dc_group]['Domain']
		fq_url = f"https://onenote.{domain}/hosting/discovery"
		all_urls.add(fq_url)
		all_dcs = config[dc_group]['DcNames']
		if fq_url in domain_to_dc_mapping:
			set_of_dcs_for_specialcasing = domain_to_dc_mapping[fq_url]
			set_of_dcs_for_specialcasing.update(all_dcs)
		else:
			set_of_dcs_for_specialcasing = set(all_dcs)
			domain_to_dc_mapping[fq_url] = set_of_dcs_for_specialcasing
		for dc in all_dcs:
			fq_url = f"https://{dc}-onenote.{domain}/hosting/discovery"
			if fq_url in domain_to_dc_mapping:
				set_of_dcs_for_specialcasing = domain_to_dc_mapping[fq_url]
				set_of_dcs_for_specialcasing.update(all_dcs)
			else:
				set_of_dcs_for_specialcasing = set(all_dcs)
				domain_to_dc_mapping[fq_url] = set_of_dcs_for_specialcasing
			# Special casing for compliance regions: the regexes might not be accurate, so try our best and blindly add all production DCs?
			if dc_group == "complianceDC":
				all_prod_dcs = config["productionDC"]['DcNames']
				set_of_dcs_for_specialcasing = domain_to_dc_mapping[fq_url]
				set_of_dcs_for_specialcasing.update(all_prod_dcs)
				compliance_regexes[fq_url] = compliance_regexes[dc]
			all_urls.add(fq_url)

def transform_url_to_regex(original_url: str, dc_str: str) -> str:
		original_url = original_url.replace("?", "\\?").replace(".", "\\.")
		original_url = re.sub(r'^https://[A-Za-z0-9]+', f"https://({dc_str})", original_url)
		original_url = f"^{original_url}$"
		return original_url

def special_case_domain_dcdiscovery(request_uri: str, all_dcs_for_this_domain: Set[str], compliance_regex: str=None) -> None:
	r = fetch_response(request_uri)
	if r is None or r.status_code != 200:
		print(f"Could not fetch response for {request_uri}.")
		return
	dc_str = "|".join(all_dcs_for_this_domain)
	dc_str = f"{dc_str}|{dc_str.lower()}"
	if compliance_regex is not None:
		dc_str = f"{compliance_regex}|{compliance_regex.lower()}|{dc_str}"
	root = ET.fromstring(r.text)
	apps = root.findall(".//app")
	for app in apps:
		if "applicationBaseUrl" in app.attrib:
			original_url = app.attrib["applicationBaseUrl"]
			app.attrib["applicationBaseUrl"] = transform_url_to_regex(original_url, dc_str)
	actions = root.findall(".//action")
	for action in actions:
		original_url = action.attrib["urlsrc"]
		action.attrib["urlsrc"] = transform_url_to_regex(original_url, dc_str)
	tree = ET.ElementTree(root)
	file_name = request_uri.replace("https://", "").replace("/hosting/discovery", "").replace(".", "-").replace("?", ".").replace("&", ".").replace("=", "_").lower()
	file_name = f"{dirname}/{file_name}"
	tree.write(file_name)

def create_file(request_uri: str) -> None:
	r = fetch_response(request_uri)
	if r is None or r.status_code != 200:
		print(f"Could not fetch response for {request_uri}.")
		return
	file_name = request_uri.replace("https://", "").replace("/hosting/discovery", "").replace(".", "-").replace("?", ".").replace("&", ".").replace("=", "_").lower()
	file_name = f"{dirname}/{file_name}"
	fhandle = open(file_name, "w")
	fhandle.write(r.text)
	fhandle.close()

domain_to_dc_mapping = dict()
all_urls = set()
dirname = f"{os.getcwd()}/WAC/Discovery"
os.makedirs(dirname, exist_ok=True)

prod_compliance_regexes = return_compliance_regex_config()
prod_config = return_config()
populate_state_with_urls(prod_config, all_urls, domain_to_dc_mapping, prod_compliance_regexes)

endpoint = "fffffff"

for url in domain_to_dc_mapping:
	compliance_regex = prod_compliance_regexes[url] if url in prod_compliance_regexes else None
	special_case_domain_dcdiscovery(f"{url}?dcDiscovery=true", domain_to_dc_mapping[url], compliance_regex)
	special_case_domain_dcdiscovery(f"{url}?dcDiscovery=true&endpoint={endpoint}", domain_to_dc_mapping[url], compliance_regex)

for url in all_urls:
	create_file(url)
	create_file(f"{url}?dcPrefix=ffc")
	create_file(f"{url}?endpoint={endpoint}")
	create_file(f"{url}?dcPrefix=ffc&dcDiscovery=true&endpoint={endpoint}")
