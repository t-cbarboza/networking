from azure.kusto.data import KustoClient, KustoConnectionStringBuilder, ClientRequestProperties
from azure.kusto.data.exceptions import KustoServiceError
from azure.kusto.data.helpers import dataframe_from_result_table
from azure.kusto.data.response import KustoStreamingResponseDataSet
from datetime import datetime
from datetime import timedelta
from flask import Flask, request, jsonify
from flask_restful import reqparse, abort, Api, Resource
from pprint import pprint
import re
import threading
from typing import Any
from typing import Dict
from typing import List
import pandas
from pandas.core.frame import DataFrame
from pandas.core.series import Series
from sklearn.neighbors import KNeighborsClassifier
from sklearn.model_selection import train_test_split


app = Flask(__name__)
api = Api(app)

matcher = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{7}Z$")

icm_cluster = "https://icmcluster.kusto.windows.net"
nrp_cluster = "https://nrp.kusto.windows.net"

# TODO: Replace all print statements with logging
# TODO: Make the date range parameterable
query_for_all_exceptions_for_one_incident = r"""
let CreateTopNFromDateRange = (subscription_id: string, incident_time: datetime) {
    let incident_start = datetime_add('day',-1, incident_time);
    let incident_end = datetime_add('day', 1, incident_time);
    let QosExceptionsData = 
        cluster('Nrp').database("mdsnrp").QosExceptions
        | where timepoint between(incident_start..incident_end)
        | project timepoint, OperationName, ErrorCode, full_em, classmethod_set;
    let QosEtwEventData = 
        cluster('Nrp').database("mdsnrp").QosEtwEvent
        | where TIMESTAMP between(incident_start..incident_end)
        | where SubscriptionId == subscription_id
        | where Success == "0"
        | project TIMESTAMP, OperationName, SubscriptionId, CorrelationRequestId, ResourceType, ResourceGroup, ErrorCode, ErrorDetails;
    QosExceptionsData
    | join kind=inner hint.strategy=broadcast (QosEtwEventData) on OperationName 
    | extend methods = split(classmethod_set, '|')
    | extend top_method = tostring(methods[0]) // top of stack
    | project PreciseTimeStamp=timepoint, SubscriptionId, CorrelationRequestId, ResourceType, ResourceGroup, ErrorDetails, full_em, top_method
    | summarize count() by top_method
    | order by count_
    | take 100
};
"""

# TODO: Make the date parameterable
query_for_all_incidents = r"""cluster('icmcluster.kusto.windows.net').database('IcMDataWarehouse').Incidents
| where SourceCreateDate > ago(30d)
| where OwningTeamName in (@"CLOUDNET\RNM", @"CLOUDNET\NRP", "NetworkAnalytics", @"CLOUDNET\NetAnalytics", // 
    @"CLOUDNET\SLB", @"CLOUDNET\ApplicationGateway", @"CLOUDNET\Gateway Manager", @"CLOUDNET\ExpressRouteSupport",
    @"CLOUDNET\Azure Bastion", @"CLOUDNET\VirtualWAN", @"CLOUDNET\DDOS", @"CLOUDNET\NRP")
| join kind=inner IncidentDescriptions on $left.IncidentId == $right.IncidentId
| where Text contains "AZURE SUPPORT CENTER"
// TODO: Make this regular expression more resilient
| parse kind=regex Summary with * @"Subscription Id\:<\/b>\s+<a\s+href=[""''](?:[^""'']*)[""''][^>]*>" AzSubscriptionId @"</a><br><br><b>Resource Group:.*"
| extend AzSubscriptionId=iff(AzSubscriptionId != "", AzSubscriptionId, "NULL")
| parse kind=regex Summary with * @"^.*(?:<b>)?Problem start time:(?:<\/b>)?\s+" IncidentStartTime "<br><br>$"
| extend IncidentStartTime=iff(IncidentStartTime == "", tostring(SourceCreateDate), IncidentStartTime)
| distinct OwningTeamName, IncidentStartTime, AzSubscriptionId
"""
icm_kusto_conn_str_builder = KustoConnectionStringBuilder.with_az_cli_authentication(icm_cluster)
nrp_kusto_conn_str_builder = KustoConnectionStringBuilder.with_az_cli_authentication(nrp_cluster)
	
# TODO: Shove all these dependencies in a constructor somewhere
icm_client = KustoClient(icm_kusto_conn_str_builder)
nrp_client = KustoClient(nrp_kusto_conn_str_builder)
knn = KNeighborsClassifier(n_neighbors=3)
all_exceptions = set()

in_memory_backing_store = dict()
lock = threading.Lock()

class Exceptions(Resource):

	def return_formatted_query_for_specific_incident(self, az_subscription_id: str, input_datetime:str) -> str:
		query_str = f"{query_for_all_exceptions_for_one_incident}CreateTopNFromDateRange(\"{az_subscription_id}\", datetime({input_datetime}))"
		return query_str

	def execute_nrp_query(self, owning_team_name: str, az_subscription_id: str, incident_start_time: str, final_list: List[Dict[str, Any]],\
	hashcode: str, backing_store: Dict[str, Dict[str, Any]]) -> None:
		try:
			incident_query = self.return_formatted_query_for_specific_incident(az_subscription_id, incident_start_time)
			results = nrp_client.execute_streaming_query("mdsnrp", incident_query)
			tables_iter = results.iter_primary_results()
			first_table = next(tables_iter)
			dictionary_for_incident = {"team": owning_team_name}
			for row in first_table:
				exception = row["top_method"]
				count = int(row["count_"])
				if (exception == None):
					print(f"Exception is none for {owning_team_name}")
					continue
				dictionary_for_incident[exception] = count
			with lock:
				final_list.append(dictionary_for_incident)
				backing_store[hashcode] = dictionary_for_incident
		except Exception as e:
			print(e)

	def return_correct_datetime(self, input_datetime:str) -> str:
		if matcher.match(input_datetime):
			return input_datetime
		datetime_obj = datetime.strptime(input_datetime, "%m/%d/%Y %I:%M:%S %p UTC")
		output_datetime_str = datetime_obj.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "000Z"
		return output_datetime_str

	def get_hashcode(self, owning_team_name: str, incident_start_time: str, az_subscription_id: str) -> str:
		return hash(f"{owning_team_name}{incident_start_time}{az_subscription_id}")

	def get(self):
		final_list = list()
		results = icm_client.execute_streaming_query("IcMDataWarehouse", query_for_all_incidents)
		tables_iter = results.iter_primary_results()
		first_table = next(tables_iter)
		all_threads = list()
		# Will block until each row arrives
		for row in first_table:
			owning_team_name = row["OwningTeamName"]
			incident_start_time = self.return_correct_datetime(row["IncidentStartTime"])
			az_subscription_id = row["AzSubscriptionId"]
			if (az_subscription_id == "NULL"):
				print("az_subscription_id is null.")
				continue
			hashcode = self.get_hashcode(owning_team_name, incident_start_time, az_subscription_id)
			if hashcode not in in_memory_backing_store:
				print("Cache miss.")
				t1 = threading.Thread(target=self.execute_nrp_query, args=(owning_team_name, az_subscription_id, incident_start_time, \
				final_list, hashcode, in_memory_backing_store,))
				t1.start()
				all_threads.append(t1)
			else:
				print("Cache hit.")
				with lock:
					final_list.append(in_memory_backing_store[hashcode])
		for t1 in all_threads:
			t1.join()
		return final_list

class Train(Resource):

	"""https://youtu.be/O2L2Uv9pdDA?feature=shared
	"""
	def train_naive_bayes(self) -> None:
		# TODO
		print("Training with Naive Bayes")

	"""https://youtu.be/0p0o5cmgLdE?feature=shared
	"""
	def train_knn(self, X_train: DataFrame, y_train: Series) -> None:
		print("Training with KNN")
		knn.fit(X_train, y_train)

	# TODO: We could probably speed this up
	def add_missing_exceptions_for_single_incident(self, single_incident: dict[str, Any]) -> None:
		# This is a deep clone
		incident_keyset = set(single_incident.keys())
		incident_keyset.remove("team")
		all_exceptions.update(incident_keyset)
		for exception in all_exceptions:
			if exception not in single_incident:
				single_incident[exception] = 0

	# TODO: We could probably speed this up
	def add_missing_exceptions(self, all_incident_data: List[dict[str, int]]) -> None:
		print(f"Number of incidents: {len(all_incident_data)}")
		for incident in all_incident_data:
			# This is a deep clone
			incident_keyset = set(incident.keys())
			incident_keyset.remove("team")
			all_exceptions.update(incident_keyset)
		for incident in all_incident_data:
			for exception in all_exceptions:
				if exception not in incident:
					incident[exception] = 0

	# TODO: This is duplicated, shove into a separate type and inject?
	def return_correct_datetime(self, input_datetime:str) -> str:
		if matcher.match(input_datetime):
			return input_datetime
		datetime_obj = datetime.strptime(input_datetime, "%m/%d/%Y %I:%M:%S %p UTC")
		output_datetime_str = datetime_obj.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "000Z"
		return output_datetime_str

	# TODO: This is duplicated, shove into a separate type and inject?
	def return_formatted_query_for_specific_incident(self, az_subscription_id: str, input_datetime:str) -> str:
		query_str = f"{query_for_all_exceptions_for_one_incident}CreateTopNFromDateRange(\"{az_subscription_id}\", datetime({input_datetime}))"
		return query_str

	def execute_nrp_query(self, owning_team_name: str, az_subscription_id: str, incident_start_time: str) -> Dict[str, Any]:
		dictionary_for_incident = {"team": owning_team_name}
		try:
			incident_query = self.return_formatted_query_for_specific_incident(az_subscription_id, incident_start_time)
			results = nrp_client.execute_streaming_query("mdsnrp", incident_query)
			tables_iter = results.iter_primary_results()
			first_table = next(tables_iter)
			for row in first_table:
				exception = row["top_method"]
				count = int(row["count_"])
				if (exception == None):
					print(f"Exception is none for {owning_team_name}")
					continue
				dictionary_for_incident[exception] = count
		except Exception as e:
			print(e)
		return dictionary_for_incident

	def get_nrp_exceptions_from_kusto(self, icm_number:int) -> Dict[str, Any]:
		query_for_single_incident = r"""cluster('icmcluster.kusto.windows.net').database('IcMDataWarehouse').Incidents
| where SourceCreateDate > ago(30d)
"""
		query_for_single_incident += f"| where IncidentId == {icm_number}"
		query_for_single_incident += r"""
| where OwningTeamName in (@"CLOUDNET\RNM", @"CLOUDNET\NRP", "NetworkAnalytics", @"CLOUDNET\NetAnalytics", // 
    @"CLOUDNET\SLB", @"CLOUDNET\ApplicationGateway", @"CLOUDNET\Gateway Manager", @"CLOUDNET\ExpressRouteSupport",
    @"CLOUDNET\Azure Bastion", @"CLOUDNET\VirtualWAN", @"CLOUDNET\DDOS", @"CLOUDNET\NRP")
| join kind=inner IncidentDescriptions on $left.IncidentId == $right.IncidentId
| where Text contains "AZURE SUPPORT CENTER"
// TODO: Make this regular expression more resilient
| parse kind=regex Summary with * @"Subscription Id\:<\/b>\s+<a\s+href=[""''](?:[^""'']*)[""''][^>]*>" AzSubscriptionId @"</a><br><br><b>Resource Group:.*"
| extend AzSubscriptionId=iff(AzSubscriptionId != "", AzSubscriptionId, "NULL")
| parse kind=regex Summary with * @"^.*(?:<b>)?Problem start time:(?:<\/b>)?\s+" IncidentStartTime "<br><br>$"
| extend IncidentStartTime=iff(IncidentStartTime == "", tostring(SourceCreateDate), IncidentStartTime)
| distinct OwningTeamName, IncidentStartTime, AzSubscriptionId
"""
		print(query_for_single_incident)
		results = icm_client.execute_streaming_query("IcMDataWarehouse", query_for_single_incident)
		tables_iter = results.iter_primary_results()
		first_table = next(tables_iter)
		all_threads = list()
		row = next(first_table)
		owning_team_name = row["OwningTeamName"]
		incident_start_time = self.return_correct_datetime(row["IncidentStartTime"])
		az_subscription_id = row["AzSubscriptionId"]
		if (az_subscription_id == "NULL"):
			raise Exception("az_subscription_id is null.")
		return self.execute_nrp_query(owning_team_name, az_subscription_id, incident_start_time)

	# TODO: Bake in KNN or Bayes
	def get(self, icm_number:int):
		exceptions_for_incident = self.get_nrp_exceptions_from_kusto(icm_number)
		self.add_missing_exceptions_for_single_incident(exceptions_for_incident)
		inbound_dataframe = pandas.DataFrame([exceptions_for_incident])
		# TODO: This does not currently work, reference the ChatGPT source code I sent you. I ripped it straight from that. Hopefully trivial
		predicted_team = knn.predict(inbound_dataframe)
		# TODO: Include statistics on accuracy when returning this to the caller, should be in the same ChatGPT source code I sent you
		return {"team": predicted_team}

	def post(self, training_model:str="naive-bayes"):
		# TODO: Figure out pagination, having the entire dictionary in memory can prove to be untenable. OK for demo.
		all_incident_data = request.get_json()
		self.add_missing_exceptions(all_incident_data)
		data_frame = pandas.DataFrame(all_incident_data)
		features = data_frame.drop('team', axis=1)
		labels = data_frame['team']
		X_train, X_test, y_train, y_test = train_test_split(features, labels, test_size=0.2, random_state=42)
		if training_model == "knn":
			self.train_knn(X_train, y_train)
		else:
			self.train_naive_bayes()
		# TODO
		pprint(all_exceptions)
		return all_incident_data

api.add_resource(Exceptions, '/exceptions', '/exceptions/fetch', '/exceptions/refresh')
api.add_resource(Train, '/train', '/train/<string:training_model>', '/train/<int:icm_number>')
if __name__ == '__main__':
	app.run(debug=True)
	# TODO: Catch the signal here for CTRL+C and close the clients properly
	icm_client.close()
	nrp_client.close()
