import os
import json
from json.decoder import JSONDecodeError
import subprocess
from subprocess import CalledProcessError
from pprint import pprint

"""Quick and dirty script - intended to be ran from the root directory of this repository:
https://office.visualstudio.com/DefaultCollection/OC/_git/Officeonline.GenevaSynthetics
"""

# RunSynthetics -a .\Wac\bin\x64\Release -c .\ConfigGenerator\bin\Release\Output\Prod\DatacenterCompliance-Prod.json -j DatacenterCompliance -i View-AE3 -r JapanEast
for relative_file_path in ["ConfigGenerator/bin/Release/Output/Prod/Prod/WopiDiscovery-Prod.json", "ConfigGenerator/bin/Release/Output/Test/Prod/WopiDiscovery-Test.json"]:
	with open(relative_file_path, 'r') as stream:
		file_contents = json.loads(stream.read())
		file_contents = file_contents["SyntheticJobGroup"]["SyntheticJobs"]
		for job in file_contents:
			job_name = job["JobName"]
			for region in job["Regions"]:
				for job_instance in job["SyntheticJobInstances"]:
					instance_name_prefix = job_instance["InstanceNamePrefix"]
					fq_command = f"RunSynthetics -a WAC/bin/x64/Debug -c {relative_file_path} -j {job_name} -i {instance_name_prefix} -r {region}"
					print(fq_command)
					fq_command = f"powershell.exe -Command {fq_command}"
					endpoint = job_instance["Parameters"]["endpoint"]
					try:
						output = subprocess.check_output(fq_command.split(" "))
						output_str = output.decode('utf-8')
						is_success = False
						logs = list()
						for line in output_str.split("\n"):
							if line.startswith("{"):
								try:
									synthetic_result = json.loads(line)
									logs.append(synthetic_result)
									base_type = synthetic_result['data']['baseType']
									if base_type == "MetricData":
										synthetic_result = synthetic_result['data']['baseData']['properties']['Result']
										is_success = synthetic_result == "Healthy"
								except JSONDecodeError as e:
									pass
						if not is_success:
							pprint(logs)
					except CalledProcessError as e:
						print(e.output)
