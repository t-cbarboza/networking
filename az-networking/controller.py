import signal
import sys
from azure.kusto.data import KustoClient, KustoConnectionStringBuilder, ClientRequestProperties
from azure.kusto.data.exceptions import KustoServiceError
from azure.kusto.data.helpers import dataframe_from_result_table
from azure.kusto.data.response import KustoStreamingResponseDataSet
from datetime import datetime
from datetime import timedelta
from flask import Flask, request, jsonify, render_template_string
from flask_restful import reqparse, abort, Api, Resource
from pprint import pprint
import re
from typing import Any, Dict, List
import pandas as pd
from pandas.core.frame import DataFrame
from tabulate import tabulate


app = Flask(__name__)
api = Api(app)

queryGrabIcm = r"""
let grabICM = (SRN: int) { 
    cluster('icmcluster.kusto.windows.net').database('IcMDataWarehouse').Incidents
        | where SupportTicketId == 2407230030010477
        | where IncidentType == "CustomerReported"
        | where Status != "ACTIVE"
        | order by ModifiedDate asc
        | project Summary
        | take 1;
};
"""

queryQos = r"""
let logs_of_interest = (subscription_id: string, resource_group: string, incident_time: datetime) { 
    let incidentStart = datetime_add('day',-1, incident_time);
    let incidentEnd = datetime_add('day', 1, incident_time);
    cluster('nrp.kusto.windows.net').database('mdsnrp').QosEtwEvent
        | where TIMESTAMP between(incidentStart..incidentEnd)
        | where SubscriptionId == subscription_id
        //| where ResourceGroup =~ resource_group
        | where Success == "0"
        | where UserError == false
        // | where ErrorDetails contains "Facade" 
        | sort by TIMESTAMP asc
        | project TIMESTAMP,StackTrace, ErrorDetails, ErrorCode, CorrelationRequestId, OperationId, OperationName, ResourceGroup
        | partition hint.strategy=Native by StackTrace(top 1 by ErrorDetails);
};
"""

teamMap = {
    "rnm": "CLOUDNET/RNM",
    "nrpinternal": "CLOUDNET/NRP",
    "networkanalytics": "CLOUDNET/NetAnalytics",
    "slb": "CLOUDNET/SLB",
    "virtualwan": "CLOUDNET/VirtualWAN",
    "networkservice": "CLOUDNET/Network Manager",
    "nrp": "CLOUDNET/NRP",
    "pubsub": "CLOUDNET/SdnPubSub",
    # "frontend" : "CLOUDNET/temp"  test
}

icmCluster = "https://icmcluster.kusto.windows.net"
nrpCluster = "https://nrp.kusto.windows.net"

icmKustoConnStrBuilder = KustoConnectionStringBuilder.with_az_cli_authentication(icmCluster)
nrpKustoConnStrBuilder = KustoConnectionStringBuilder.with_az_cli_authentication(nrpCluster)
# TODO: Shove all these dependencies in a constructor somewhere
icmClient = KustoClient(icmKustoConnStrBuilder)
nrpClient = KustoClient(nrpKustoConnStrBuilder)

class Helper:
    @staticmethod
    def formattedDatetime(inputDatetime: str) -> str:
        matcher = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{7}Z$")
        if matcher.match(inputDatetime):
            return inputDatetime
        datetimeObj = datetime.strptime(inputDatetime, "%m/%d/%Y %I:%M:%S %p UTC")
        outputDatetimeStr = datetimeObj.strftime("%Y-%m-%dT%H:%M:%S")
        return outputDatetimeStr
    
    @staticmethod
    def dataframe_to_html(df: pd.DataFrame) -> str:
        return df.to_html()

class Exceptions(Resource):
    ####### ICM #######
    def executeIcmQuery(self, supportRequestNumber: str) -> Dict[str, Any]:
        queryStr = f"{queryGrabIcm}grabICM({supportRequestNumber})"
        try:
            response = icmClient.execute("IcMDataWarehouse", queryStr)
            resultDf = dataframe_from_result_table(response.primary_results[0])
            if not resultDf.empty:
                summary = resultDf.iloc[0]['Summary']
                return self.parseSummary(summary)
            else:
                return "No results found."
        except KustoServiceError as e:
            return str(e)
        except Exception as e:
            return str(e)
        
    def parseSummary(self, summary: str)  -> Dict[str, str]:
        result = {}
        subscriptionIdMatch = re.search(r'href="https://azuresupportcenter\.azure\.com/resourceExplorer/subscription/([a-f0-9\-]+)\?', summary)
   
        if subscriptionIdMatch:
            subscriptionId = subscriptionIdMatch.group(1)
            result['subscriptionId'] = subscriptionId
            resourceUriMatch = re.search(rf'/subscriptions/{subscriptionId}/resource[Gg]roups/([0-9a-zA-Z-_]+)/providers/Microsoft\.Network/([0-9a-zA-Z-_]+)/([0-9a-zA-Z-_]+)', summary)
            if resourceUriMatch:
                result['resourceGroup'] = resourceUriMatch.group(1)
                result['provider'] = resourceUriMatch.group(2)
                result['providerName'] = resourceUriMatch.group(3)
                result['resourceUri'] = resourceUriMatch.group(0)
            criTimeMatch = re.search(r'(\d{1,2}/\d{1,2}/\d{4}\s\d{1,2}:\d{2}:\d{2}\s[AP]M\sUTC)', summary)
            if criTimeMatch:
                result['criTime'] = Helper.formattedDatetime(criTimeMatch.group(1))
        if 'subscriptionId' not in result:
            result['error'] = "No subscriptionId found."
        return result
    
    ####### NRP #######
    def executeNrpQuery(self, subscriptionId: str, resourceGroup: str, incidentTime: str) -> Dict[str, Any]:
        print(f"entered executeNRP: subscription {subscriptionId}&resourceGroup={resourceGroup}&incidentTime={incidentTime}, time: {type(incidentTime)}")
        queryStr = f"{queryQos}logs_of_interest(\"{subscriptionId}\", \"{resourceGroup}\", datetime(\"{incidentTime}\"))"
        try:
            response = nrpClient.execute("mdsnrp", queryStr)
            resultDf = dataframe_from_result_table(response.primary_results[0])
            if not resultDf.empty:
                self.parseErrorDetails(resultDf)
                self.mapToTeams(resultDf)
                self.get_predicted_owning_team(resultDf)
                html_table = Helper.dataframe_to_html(resultDf)
                resultDict = resultDf.to_dict(orient='records')
                formatted_link = f"http://127.0.0.1:5000/show_table?subscriptionId={subscriptionId}&resourceGroup={resourceGroup}&incidentTime={incidentTime}"
                print(f"Generated URL: {formatted_link}, time: {type(incidentTime)}")  # Debugging
                return {"status": "success", "a_formatted_link": formatted_link, "data": resultDict, "html_table": html_table}
            else:
                return {"status": "no_data", "message": "No ErrorDetails found."}
        except KustoServiceError as e:
            return {"status": "error", "message": str(e)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def parseErrorDetails(self, errorLogs: pd.DataFrame) -> pd.DataFrame:
        def cleanLines(lines: List[str]) -> List[str]:
            cleanedLines = []
            for line in lines:
                match = re.search(r"bt\\[0-9]+\\repo\\src\\sources\\([a-zA-Z\\]+)", line)
                if match:
                    path = match.group(1)
                    cleanedPath = re.sub(r'[0-9]+', '', path).replace('\\', ' ')#.split()
                    cleanedLines.append(cleanedPath)
            return cleanedLines
        
        errorLogs['exceptionCallStack'] = errorLogs['ErrorDetails'].str.split('\n').apply(cleanLines)
       # Remove rows without matches TODO: test this
        errorLogs = errorLogs[errorLogs['exceptionCallStack'].map(len) > 0]
        return errorLogs
    
    def mapToTeams(self, errorLogs: pd.DataFrame) -> pd.DataFrame:        
        def mapLineToTeam(cleanedLines: List[str]) -> List[Dict[str, Any]]:
            teamCounts = {}
            for lineIndex, line in enumerate(cleanedLines):
                for key, team in teamMap.items():
                    matches = list(re.finditer(key, line.lower()))
                    num_matches = len(matches)
                    if matches:
                        last_match = matches[-1]
                        before_key = line[:last_match.start()]
                        words_before_key = len(before_key.split())

                        if key in teamCounts:
                            teamCounts[key]['match_count'] += num_matches
                            if lineIndex <= teamCounts[key]['exception_method_idx'][0]:
                                teamCounts[key]['exception_method_idx'] = [lineIndex, words_before_key]
                        else:
                            teamCounts[key] = teamCounts[key] = {
                                'team_key': key,
                                'team_value': team,
                                'match_count': num_matches,
                                'exception_method_idx' : [lineIndex, words_before_key] # smallest exception (line), largest method (word)
                            }
            return list(teamCounts.values())
        
        errorLogs['mappedTeams'] = errorLogs['exceptionCallStack'].apply(mapLineToTeam)
        # Remove rows without matches TODO: test this
        errorLogs = errorLogs[errorLogs['mappedTeams'].map(len) > 0]
        return errorLogs

    def get_predicted_owning_team(self, errorLogs: pd.DataFrame) -> pd.DataFrame:
        def sorting_criteria(team: Dict[str, Any]) -> tuple:
            return (-team['match_count'], team['exception_method_idx'][0], -team['exception_method_idx'][1])

        def get_team(mappedTeams: List[Dict[str, Any]]) -> str:
            sorted_teams = sorted(mappedTeams, key=sorting_criteria)
            if sorted_teams:
                return sorted_teams[0]['team_value']
            return ""

        errorLogs['predictedOwningTeam'] = errorLogs['mappedTeams'].apply(get_team)
        return errorLogs                        
    

    ####### executing #######
    def get(self):
        supportRequestNumber = request.args.get('support_request_number')
        if not supportRequestNumber:
            return {"error": "supportRequestNumber is required"}, 400
        
        icmResult = self.executeIcmQuery(supportRequestNumber)
        if 'error' in icmResult:
            return jsonify({"result": icmResult})
        
        subscriptionId = icmResult['subscriptionId']
        resourceGroup = icmResult['resourceGroup']
        incidentTime = icmResult['criTime']
        
        nrpResult = self.executeNrpQuery(subscriptionId, resourceGroup, incidentTime)
        return jsonify({"icmResult": icmResult, "j_nrpTableHtml" : "formatted_link", "nrpResult": nrpResult})

@app.route('/show_table')
def show_table():
    # Example of getting query parameters from the request
    print(f"test")
    subscriptionId = request.args.get('subscriptionId')
    resourceGroup = request.args.get('resourceGroup')
    incidentTime = request.args.get('incidentTime')

    if not subscriptionId or not resourceGroup or not incidentTime:
        return {"error": "All parameters (subscriptionId, resourceGroup, incidentTime) are required"}, 400
   
    exceptions_instance = Exceptions()
    nrpResult = exceptions_instance.executeNrpQuery(subscriptionId, resourceGroup, incidentTime)

    if 'status' in nrpResult and nrpResult['status'] == 'error':
        return jsonify({"result": nrpResult})
    
    html_table = nrpResult.get("html_table", "No data available")
    formatted_link = nrpResult.get("formatted_link", "")


    # Render the HTML table in an HTML template
    return render_template_string('''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>DataFrame as HTML Table</title>
    </head>
    <body>
        <h1>Data Table</h1>
        {{ table|safe }}
    </body>
    </html>
    ''', table=html_table)  


def signalHandler(signal, frame):
    print('Shutting down gracefully...')
    icmClient.close()
    nrpClient.close()
    sys.exit(0)
 
if __name__ == '__main__':
    api.add_resource(Exceptions, '/exceptions', '/exceptions/fetch', '/exceptions/refresh')
    signal.signal(signal.SIGINT, signalHandler)
    app.run(debug=True)
