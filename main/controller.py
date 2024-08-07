import signal
import sys
from azure.kusto.data import KustoClient, KustoConnectionStringBuilder, ClientRequestProperties
from azure.kusto.data.exceptions import KustoServiceError
from azure.kusto.data.helpers import dataframe_from_result_table
from azure.kusto.data.response import KustoStreamingResponseDataSet
from datetime import datetime
from datetime import timedelta
from flask import Flask, request, jsonify, render_template_string, url_for, redirect
from flask_restful import reqparse, abort, Api, Resource
from pprint import pprint
import re
from typing import Any, Dict, List
import pandas as pd
from pandas.core.frame import DataFrame
from tabulate import tabulate
import json
from urllib.parse import quote, unquote
from io import StringIO


app = Flask(__name__)
api = Api(app)


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
        | sort by TIMESTAMP asc
        | project TIMESTAMP, ErrorDetails, CorrelationRequestId, SubscriptionId, ResourceGroup, StackTrace, ErrorCode, OperationId, OperationName
        //| partition hint.strategy=Native by StackTrace(top 1 by ErrorDetails);
};
"""

# Use when you want only want to see team history, no intermediary hops
queryTeamHistory = r"""
let teamHistory = (incident_id: string) {
    cluster('https://icmcluster.kusto.windows.net').database('IcMDataWarehouse').Incidents
        | where IncidentId == incident_id
        | order by ModifiedDate asc
        | serialize Sequence = row_number()
        | summarize FirstOccurrence = min(Sequence) by OwningTeamName
        | order by FirstOccurrence asc
        | project OwningTeamName
};
"""

# Use when you want to see all the team history, back-n-forth hops included
queryTeamHistoryAll = r"""
let teamHistoryAll = (incident_id: string) {
    cluster('https://icmcluster.kusto.windows.net').database('IcMDataWarehouse').Incidents
        | where IncidentId == incident_id
        | order by ModifiedDate asc
        | extend PreviousTeamName = prev(OwningTeamName)
        | where OwningTeamName != PreviousTeamName or isnull(PreviousTeamName)
        | project ModifiedDate, OwningTeamName, Status, IncidentId
        | summarize TeamHistory = make_list(pack('OwningTeamName', OwningTeamName, 'ModifiedDate', ModifiedDate)) by IncidentId
};
"""

queryGrabIcm = r"""
let grabICM = (incidentId: int) { 
    cluster('icmcluster.kusto.windows.net').database('IcMDataWarehouse').Incidents
        | where IncidentId == incidentId
        | where Status != "ACTIVE"
        | where not(isempty(Summary))
        | order by ModifiedDate asc
        | extend IncidentStartTime = SourceCreateDate
        | project Summary, SubscriptionId, SupportTicketId, IncidentStartTime, IncidentId
        // other useful columns: (IncidentType == "CustomerReported"), Status != "ACTIVE", (IncidentId more unique than SupportTicketId)
        | take 1;
};
"""

queryFindIcms = r"""cluster('https://icmcluster.kusto.windows.net').database('IcMDataWarehouse').Incidents
    | where SourceCreateDate > ago(30d)
    | where OwningTeamName in (@"CLOUDNET\RNM", @"CLOUDNET\NRP", "NetworkAnalytics", @"CLOUDNET\NetAnalytics", 
    @"CLOUDNET\SLB", @"CLOUDNET\ApplicationGateway", @"CLOUDNET\Gateway Manager", @"CLOUDNET\ExpressRouteSupport",
    @"CLOUDNET\Azure Bastion", @"CLOUDNET\VirtualWAN", @"CLOUDNET\DDOS", @"CLOUDNET\NRP")
    | where Status == "RESOLVED"
    | where IncidentType == "CustomerReported"
    | where not(isempty(SubscriptionId))
    | where not(isempty(SourceCreateDate))
    | parse kind=regex Summary with * @"^.*(?:<b>)?Problem start time:(?:<\/b>)?\s+" IncidentStartTime "<br><br>$"
    | extend IncidentStartTime=iff(IncidentStartTime == "", tostring(SourceCreateDate), IncidentStartTime)
    | distinct SubscriptionId, OwningTeamName, IncidentId, IncidentStartTime
    | take 20;
"""

teamMap = { 
    # teams appear in kusto icm incidents table as CLOUDNET\\<team-name> and in icm portal as Cloudnet/<team-name>
    "rnm": "CLOUDNET\\RNM",
    "nrpinternal": "CLOUDNET\\NRP",
    "networkanalytics": "CLOUDNET\\NetAnalytics",
    "slb": "CLOUDNET\\SLB",
    "virtualwan": "CLOUDNET\\VirtualWAN",
    "networkservice": "CLOUDNET\\Network Manager",
    "nrp": "CLOUDNET\\NRP",
    "pubsub": "CLOUDNET\\SdnPubSub",
    "applicationgateway": "CLOUDNET\\ApplicationGateway"
    # "frontend" : "CLOUDNET\\temp"  test
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
    def formattedDatetime(inputDatetime) -> str:
        if isinstance(inputDatetime, datetime):
            return inputDatetime.strftime("%Y-%m-%dT%H:%M:%S")
        
        matcher = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{7}Z$")
        if matcher.match(inputDatetime):
            return inputDatetime
        
        datetimeObj = datetime.strptime(inputDatetime, "%m/%d/%Y %I:%M:%S %p UTC")
        outputDatetimeStr = datetimeObj.strftime("%Y-%m-%dT%H:%M:%S")
        return outputDatetimeStr

class Exceptions(Resource):
    ####### ICM -- find incidents that match our criteria #######
    def executeFindIcmsQuery(self) -> pd.DataFrame:
        try:
            response = icmClient.execute("IcMDataWarehouse", queryFindIcms)
            resultDf = dataframe_from_result_table(response.primary_results[0])
            print('after icm query find icms')
            if not resultDf.empty:
                incidentIds = list(resultDf['IncidentId'].tolist())
                return incidentIds
            else:
                return pd.DataFrame({'status': ['no_data'], 'message': [f'No ErrorDetails found in Incidents table']})
        except KustoServiceError as e:
            return pd.DataFrame({'status': ['error'], 'message': [str(e)]})
        except Exception as e:
            return pd.DataFrame({'status': ['error'], 'message': [str(e)]})

    ####### ICM -- grab info for specific incident #######
    def executeIcmQuery(self, incidentId: str) -> pd.DataFrame:
        queryStrIncident = f"{queryGrabIcm}grabICM({incidentId})"
        queryStrTeams = f"{queryTeamHistoryAll}teamHistoryAll({incidentId})"
        try:
            responseIncident = icmClient.execute("IcMDataWarehouse", queryStrIncident)
            resultIncident = dataframe_from_result_table(responseIncident.primary_results[0])
            
            responseTeams = icmClient.execute("IcMDataWarehouse", queryStrTeams)
            resultTeams = dataframe_from_result_table(responseTeams.primary_results[0])
            print('in executeIcmQuery')
            if not resultIncident.empty and not resultTeams.empty:
                combined_result = pd.merge(resultIncident, resultTeams, on='IncidentId', how='left', suffixes=('', '_TeamHistory'))
                return self.parseSummary(combined_result)
            else:
                return pd.DataFrame({'status': ['no_data'], 'message': [f'executeIcmQuery: Unable to combine ICM with team history on incident: {incidentId}']})
        except KustoServiceError as e:
            return pd.DataFrame({'error': [str(e)]})
        except Exception as e:
            return pd.DataFrame({'error': [str(e)]})
    
    def parseSummary(self, resultDf: pd.DataFrame) -> pd.DataFrame:
        resourceUriPattern = rf'/subscriptions/{resultDf["SubscriptionId"].iat[0]}/resource[Gg]roups/([0-9a-zA-Z-_]+)/providers/Microsoft\.Network/([0-9a-zA-Z-_]+)/([0-9a-zA-Z-_]+)'
        datetimePattern = r'(\d{1,2}/\d{1,2}/\d{4}\s\d{1,2}:\d{2}:\d{2}\s[AP]M\sUTC)'

        def extract_match(pattern, text, group_index, default='not_found'):
            match = re.search(pattern, text)
            return match.group(group_index) if match else default
        resultDf['IncidentStartTime'] = resultDf['Summary'].apply(lambda x: Helper.formattedDatetime(extract_match(datetimePattern, x, 1, resultDf['IncidentStartTime'].iloc[0])))
        resultDf['IcmLink'] = resultDf.apply(lambda row: f"https://portal.microsofticm.com/imp/v5/incidents/details/{row['IncidentId']}/summary", axis=1)
        # resultDf['ResourceGroup'] = resultDf['Summary'].apply(lambda x: extract_match(resourceUriPattern, x, 1, 'not_Found'))
        # resultDf['Provider'] = resultDf['Summary'].apply(lambda x: extract_match(resourceUriPattern, x, 2))
        # resultDf['ProviderName'] = resultDf['Summary'].apply(lambda x: extract_match(resourceUriPattern, x, 3))
        resultDf = resultDf.drop(columns=['Summary'])
        return resultDf

    
    ####### NRP #######
    def executeNrpQuery(self, subscriptionId: str, incidentTime: str, incidentId:int, resourceGroup: str = 'temp') -> pd.DataFrame:
        queryStr = f"{queryQos}logs_of_interest(\"{subscriptionId}\", \"{resourceGroup}\", datetime(\"{incidentTime}\"))"
        try:
            response = nrpClient.execute("mdsnrp", queryStr)
            resultDf = dataframe_from_result_table(response.primary_results[0])
            if not resultDf.empty:
                resultDf = self.parseErrorDetails(resultDf)
                resultDf = self.mapToTeams(resultDf)
                resultDf = self.get_predicted_owning_team(resultDf)
                resultDf['TIMESTAMP'] = resultDf['TIMESTAMP'].apply(Helper.formattedDatetime)
                
                # Need if check if its empty now after removing rows in previous functions
                if resultDf.empty:
                    return pd.DataFrame({'status': ['no_data'], 'message': [f'executeNrpQuery/others: Unable to match ErrorDetails to a team for incident: {incidentId}']})
                return resultDf
            else:
                return pd.DataFrame({'status': ['no_data'], 'message': [f'executeNrpQuery: No ErrorDetails found in NRP table for incident: {incidentId}']})
        except KustoServiceError as e:
            return pd.DataFrame({'status': ['error'], 'message': [str(e)]})
        except Exception as e:
            return pd.DataFrame({'status': ['error'], 'message': [str(e)]})

    def parseErrorDetails(self, errorLogs: pd.DataFrame) -> pd.DataFrame:
        def cleanLines(lines: List[str]) -> List[str]:
            cleanedLines = []
            for line in lines:
                match = re.search(r"bt\\[0-9]+\\repo\\src\\sources\\([a-zA-Z\\]+)", line)
                if match:
                    path = match.group(1)
                    cleanedPath = re.sub(r'[0-9]+', '', path).replace('\\', ' ')
                    cleanedLines.append(cleanedPath)
            return cleanedLines
        
        # Remove any rows where there are no values in ExceptionCallStack
        errorLogs['ExceptionCallStack'] = errorLogs['ErrorDetails'].str.split('\n').apply(cleanLines)
        errorLogs = errorLogs[errorLogs['ExceptionCallStack'].map(len) > 0]
        return errorLogs

    def mapToTeams(self, errorLogs: pd.DataFrame) -> pd.DataFrame:        
        def mapLineToTeam(cleanedLines: List[str]) -> List[Dict[str, Any]]:
            teamCounts = {}
            for lineIndex, line in enumerate(cleanedLines):
                for key, team in teamMap.items():
                    matches = list(re.finditer(key.lower(), line.lower()))
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
                                'exception_method_idx' : [lineIndex, words_before_key]
                            }
            return list(teamCounts.values())
        
        # Remove any rows where its not able to map the log to a team
        errorLogs['MappedTeams'] = errorLogs['ExceptionCallStack'].apply(mapLineToTeam)
        errorLogs = errorLogs[errorLogs['MappedTeams'].map(len) > 0]
        return errorLogs

    def get_predicted_owning_team(self, errorLogs: pd.DataFrame) -> pd.DataFrame:
        def sorting_criteria(team: Dict[str, Any]) -> tuple:
            return (-team['match_count'], team['exception_method_idx'][0], -team['exception_method_idx'][1])

        def get_team(MappedTeams: List[Dict[str, Any]]) -> str:
            sorted_teams = sorted(MappedTeams, key=sorting_criteria)
            if sorted_teams:
                return sorted_teams[0]['team_value']
            return ""

        errorLogs['PredictedOwningTeam'] = errorLogs['MappedTeams'].apply(get_team)
        return errorLogs 

    ####### Shared Processing #######
    def combineNrpLogs(self, nrpDf: pd.DataFrame) -> pd.DataFrame:
        # Check if all PredictedOwningTeam values are the same
        if nrpDf['PredictedOwningTeam'].nunique() == 1:
            # Get the log with the most mentions of that team
            most_mentions_log = nrpDf.loc[nrpDf['MappedTeams'].apply(lambda teams: sum(team['team_value'] == nrpDf['PredictedOwningTeam'].iloc[0] for team in teams)).idxmax()]
            newDf = pd.DataFrame([most_mentions_log])
        else:
            # Get the first occurrence of each log that has a different PredictedOwningTeam
            newDf = nrpDf.drop_duplicates(subset=['PredictedOwningTeam'], keep='first')
        
        if newDf.empty:
            return pd.DataFrame({'status': ['no_data'], 'message': ['combineNrpLogs: Table empty after combining all errorDetail logs']})
        return newDf
    
    def combineNrpIcm(self, nrpDf: pd.DataFrame, icmDf: pd.DataFrame) -> pd.DataFrame:
        nrpCombinedDf = self.combineNrpLogs(nrpDf)
        if 'status' in nrpCombinedDf.columns:
            return nrpCombinedDf

        # TODO: If there are two predicted teams for the same subscription + time combo, need to test that icm info will apply to both
        mergedDf = pd.merge(nrpCombinedDf, icmDf, on='SubscriptionId', how='inner', suffixes=('_nrp', '_icm'))
        if mergedDf.empty:
            return pd.DataFrame({'status': ['no_data'], 'message': ['combineNrpIcm: Table empty after combining nrpDf and icmDf']})
        
        mergedDf = mergedDf.drop(columns=['ErrorDetails','StackTrace', 'CorrelationRequestId', 'ErrorCode', 'ResourceGroup', 'OperationId', 'OperationName', 'MappedTeams', 'SupportTicketId'])
        
        # Add 'PredictedTeamInHistory' column
        mergedDf['PredictedTeamInHistory'] = mergedDf.apply(
            lambda row: any(team['OwningTeamName'] == row['PredictedOwningTeam'] for team in row['TeamHistory']),
            axis=1
        )
        return mergedDf

    def runBody(self, incidentId: str) -> pd.DataFrame:
        if not incidentId:
            return pd.DataFrame({'status': ['error'], 'message': ['incident_id is required']})
    
        icmResult = self.executeIcmQuery(incidentId)
        if 'error' in icmResult.columns:
            return icmResult
        #print({"icmResult": icmResult.to_dict(orient='records')})
    
        subscriptionId = icmResult.iloc[0]['SubscriptionId']
        incidentTime = icmResult.iloc[0]['IncidentStartTime']
    
        nrpResult = self.executeNrpQuery(subscriptionId, incidentTime, incidentId)
        if 'status' in nrpResult.columns:
            return nrpResult
        #print({"nrpResult": nrpResult.to_dict(orient='records')})
    
        logTLDR = self.combineNrpIcm(nrpResult, icmResult)
        if 'status' in logTLDR.columns:
            return logTLDR
    
        return logTLDR

    # Use when you want to grab info for one icm
    def get(self):
        incidentId = request.args.get('incident_id')
        logTLDR = self.runBody(incidentId)
    
        if 'status' in logTLDR.columns:
            return jsonify({"result": logTLDR['message'].iloc[0]})
        
        logTLDRjson = quote(logTLDR.to_json(orient='records'))
        tableLink = f"http://127.0.0.1:5000/show_table?logtldr={logTLDRjson}"
        
        return jsonify({"TableLink" : tableLink, "logTLDR": logTLDR.to_dict(orient='records')}) 

    # Use when you want to find the ICMs
    def get(self):
        icmIdList = self.executeFindIcmsQuery()
        print(icmIdList)
        allIcmDf = pd.DataFrame()
        # icmIdList = pd.DataFrame([511101094, 519639582, 526186661, 525907329])
        # allIcm_df = pd.DataFrame()
        
        for incidentId in icmIdList:
            logTLDR = self.runBody(incidentId)
    
            if 'status' in logTLDR.columns:
                print(f'Incident {incidentId} failed in', logTLDR['message'].iloc[0])
                continue
            print(f'Processing incident {incidentId}')
            allIcmDf = pd.concat([allIcmDf, logTLDR], ignore_index=True)

        # Add html table to output
        allIcmDfjson = quote(allIcmDf.to_json(orient='records'))
        tableLink = f"http://127.0.0.1:5000/show_table?logTLDR={allIcmDfjson}"            

        return jsonify({"TableLink" : tableLink, "allIcm_df": allIcmDf.to_dict(orient='records')})

@app.route('/show_table', methods=['POST'])
def show_table():
    logTLDRjson = request.args.get('logtldr')
    
    if not logTLDRjson:
        return {"error": "logTLDR data is required"}, 400
    
    # Convert JSON string back to DataFrame
    # logTLDRjson = unquote(logTLDRjson)
    logTLDR_df = pd.read_json(StringIO(logTLDRjson))
    
    # Convert DataFrame to HTML table
    htmlTable = logTLDR_df.to_html()

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
    ''', table=htmlTable)

def signalHandler(signal, frame):
    print('Shutting down gracefully...')
    icmClient.close()
    nrpClient.close()
    sys.exit(0)
 
if __name__ == '__main__':
    api.add_resource(Exceptions, '/exceptions', '/exceptions/fetch', '/exceptions/refresh')
    signal.signal(signal.SIGINT, signalHandler)
    app.run(debug=True)