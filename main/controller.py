import signal
import sys
from azure.kusto.data import KustoClient, KustoConnectionStringBuilder
from azure.kusto.data.exceptions import KustoServiceError
from azure.kusto.data.helpers import dataframe_from_result_table
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string
from flask_restful import Api, Resource
from pprint import pprint
import re
from typing import Any, Dict, List
import pandas as pd
from pandas.core.frame import DataFrame
import json
from urllib.parse import quote, unquote
from io import StringIO

app = Flask(__name__)
api = Api(app)

queryTimeWindow = r"""
let timeWindow = (subscriptionId: string, incidentTime: string) { 
    cluster('Nrp').database('mdsnrp').QosEtwEvent
    | where TIMESTAMP between(todatetime(incidentTime)-6d..todatetime(incidentTime))
    | where SubscriptionId == subscriptionId
    | where Success == '0'
    | summarize error_count = count() by SubscriptionId, bin(TIMESTAMP, 1h)
    | order by error_count desc
    | top 1 by error_count
    | project TIMESTAMP
};
"""

queryQos = r"""
let logsOfInterest = (subscriptionId: string, resourceGroup: string, incidentTime: datetime) { 
    cluster('nrp.kusto.windows.net').database('mdsnrp').QosEtwEvent
        | where TIMESTAMP between(incidentTime-1h..incidentTime+1h)
        | where SubscriptionId == subscriptionId
        //| where ResourceGroup =~ resourceGroup
        | where Success == '0'
        | where UserError == false
        | sort by TIMESTAMP asc
        | project TIMESTAMP, ErrorDetails, CorrelationRequestId, SubscriptionId, ResourceGroup, StackTrace, ErrorCode, OperationId, OperationName
        //| partition hint.strategy=Native by StackTrace(top 1 by ErrorDetails);
};
"""

# Use when you want only want to see team history, no intermediary hops
queryTeamHistory = r"""
let teamHistory = (incidentId: string) {
    cluster('https://icmcluster.kusto.windows.net').database('IcMDataWarehouse').Incidents
        | where IncidentId == incidentId
        | order by ModifiedDate asc
        | serialize Sequence = row_number()
        | summarize FirstOccurrence = min(Sequence) by OwningTeamName
        | order by FirstOccurrence asc
        | project OwningTeamName
};
"""

# Use when you want to see all the team history, back-n-forth hops included
queryTeamHistoryAll = r"""
let teamHistoryAll = (incidentId: string) {
    cluster('https://icmcluster.kusto.windows.net').database('IcMDataWarehouse').Incidents
        | where IncidentId == incidentId
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
        | where Status != 'ACTIVE'
        | where not(isempty(Summary))
        | order by ModifiedDate asc
        | extend IncidentStartTime = SourceCreateDate
        | project Summary, SubscriptionId, SupportTicketId, IncidentStartTime, IncidentId
        // other useful columns: (IncidentType == 'CustomerReported'), Status != 'ACTIVE', (IncidentId more unique than SupportTicketId)
        | take 1;
};
"""

queryFindIcms = r"""cluster('https://icmcluster.kusto.windows.net').database('IcMDataWarehouse').Incidents
    | where SourceCreateDate > ago(30d)
    | where OwningTeamName in (@'CLOUDNET\RNM', @'CLOUDNET\NRP', 'NetworkAnalytics', @'CLOUDNET\NetAnalytics', 
    @'CLOUDNET\SLB', @'CLOUDNET\ApplicationGateway', @'CLOUDNET\Gateway Manager', @'CLOUDNET\ExpressRouteSupport',
    @'CLOUDNET\Azure Bastion', @'CLOUDNET\VirtualWAN', @'CLOUDNET\DDOS', @'CLOUDNET\NRP')
    | where Status == 'RESOLVED'
    | where IncidentType == 'CustomerReported'
    | where not(isempty(SubscriptionId))
    | where not(isempty(SourceCreateDate))
    | parse kind=regex Summary with * @'^.*(?:<b>)?Problem start time:(?:<\/b>)?\s+' IncidentStartTime '<br><br>$'
    | extend IncidentStartTime=iff(IncidentStartTime == '', tostring(SourceCreateDate), IncidentStartTime)
    | distinct SubscriptionId, OwningTeamName, IncidentId, IncidentStartTime
    | take 20;
"""

teamMap = { 
    # teams appear in kusto icm incidents table as CLOUDNET\\<team-name> and in icm portal as Cloudnet/<team-name>
    'rnm': 'CLOUDNET\\RNM',
    'nrpinternal': 'CLOUDNET\\NRP',
    'networkanalytics': 'CLOUDNET\\NetAnalytics',
    'slb': 'CLOUDNET\\SLB',
    'virtualwan': 'CLOUDNET\\VirtualWAN',
    'networkservice': 'CLOUDNET\\Network Manager',
    'nrp': 'CLOUDNET\\NRP',
    'pubsub': 'CLOUDNET\\SdnPubSub',
    'applicationgateway': 'CLOUDNET\\ApplicationGateway'
    # 'frontend' : 'CLOUDNET\\temp'  test
}

icmCluster = 'https://icmcluster.kusto.windows.net'
nrpCluster = 'https://nrp.kusto.windows.net'

icmKustoConnStrBuilder = KustoConnectionStringBuilder.with_az_cli_authentication(icmCluster)
nrpKustoConnStrBuilder = KustoConnectionStringBuilder.with_az_cli_authentication(nrpCluster)
# TODO: Shove all these dependencies in a constructor somewhere
icmClient = KustoClient(icmKustoConnStrBuilder)
nrpClient = KustoClient(nrpKustoConnStrBuilder)

class Helper:
    @staticmethod
    def formattedDatetime(inputDatetime) -> str:
        if isinstance(inputDatetime, datetime):
            return inputDatetime.strftime('%Y-%m-%dT%H:%M:%S')
        
        # This pattern matches a datetime string in the format YYYY-MM-DDTHH:MM:SS.sssssssZ
        if re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{7}Z$', inputDatetime):
            return inputDatetime
        
        # From common time with slashes to 24-time with hyphens
        return datetime.strptime(inputDatetime, '%m/%d/%Y %I:%M:%S %p UTC').strftime('%Y-%m-%dT%H:%M:%S')


class Processing():
    ####### ICM -- find incidents that match our criteria #######
    def executeFindIcmsQuery(self) -> pd.DataFrame:
        try:
            resultDf = dataframe_from_result_table(icmClient.execute('IcMDataWarehouse', queryFindIcms).primary_results[0])

            if not resultDf.empty:
                return list(resultDf['IncidentId'].tolist())
            else:
                return pd.DataFrame({'status': ['no_data'], 'message': [f'No ErrorDetails found in Incidents table']})
        except KustoServiceError as e:
            return pd.DataFrame({'status': ['error'], 'message': [str(e)]})
        except Exception as e:
            return pd.DataFrame({'status': ['error'], 'message': [str(e)]})

    ####### ICM -- grab info for specific incident #######
    def executeIcmQuery(self, incidentId: str) -> pd.DataFrame:
        queryStrIncident = f'{queryGrabIcm}grabICM({incidentId})'
        queryStrTeams = f'{queryTeamHistoryAll}teamHistoryAll({incidentId})'
        try:
            resultIncidentDf = dataframe_from_result_table(icmClient.execute('IcMDataWarehouse', queryStrIncident).primary_results[0])
            resultTeamsDf = dataframe_from_result_table(icmClient.execute('IcMDataWarehouse', queryStrTeams).primary_results[0])

            # Merge df with icm info and the icm's team history
            if not resultIncidentDf.empty and not resultTeamsDf.empty:
                combined_result = pd.merge(resultIncidentDf, resultTeamsDf, on='IncidentId', how='left', suffixes=('', '_TeamHistory'))
                return self.parseSummary(combined_result)
            else:
                return pd.DataFrame({'status': ['no_data'], 'message': [f'executeIcmQuery: Unable to combine ICM with team history on incident: {incidentId}']})
        except KustoServiceError as e:
            return pd.DataFrame({'error': [str(e)]})
        except Exception as e:
            return pd.DataFrame({'error': [str(e)]})
    
    def parseSummary(self, resultDf: pd.DataFrame) -> pd.DataFrame:
        # Parse icm summary to find the resourceURI associated with subscription, grab other identifying info from it
        resourceUriPattern = rf'/subscriptions/{resultDf['SubscriptionId'].iat[0]}/resource[Gg]roups/([0-9a-zA-Z-_]+)/providers/Microsoft\.Network/([0-9a-zA-Z-_]+)/([0-9a-zA-Z-_]+)'
        # Find customer reported problem start time in MM/DD/YYY II:HH:MM AM/PM UTC format
        datetimePattern = r'(\d{1,2}/\d{1,2}/\d{4}\s\d{1,2}:\d{2}:\d{2}\s[AP]M\sUTC)'

        def extract_match(pattern, text, group_index, default='not_found'):
            match = re.search(pattern, text)
            return match.group(group_index) if match else default
        resultDf['IncidentStartTime'] = resultDf['Summary'].apply(lambda x: Helper.formattedDatetime(extract_match(datetimePattern, x, 1, resultDf['IncidentStartTime'].iloc[0])))
        resultDf['IcmLink'] = resultDf.apply(lambda row: f'https://portal.microsofticm.com/imp/v5/incidents/details/{row['IncidentId']}/summary', axis=1)
        resultDf['ResourceGroup'] = resultDf['Summary'].apply(lambda x: extract_match(resourceUriPattern, x, 1))
        resultDf['Provider'] = resultDf['Summary'].apply(lambda x: extract_match(resourceUriPattern, x, 2))
        resultDf['ProviderName'] = resultDf['Summary'].apply(lambda x: extract_match(resourceUriPattern, x, 3))
        resultDf = resultDf.drop(columns=['Summary'])
        return resultDf

    ####### Time Window of most error logs #######
    def executeTimeQuery(self, subscriptionId: str, incidentTime: str) -> str:
        queryStrTime = f'{queryTimeWindow}timeWindow(\'{subscriptionId}\', \'{incidentTime}\')'
        try:
            response = nrpClient.execute('IcMDataWarehouse', queryStrTime)
            result = dataframe_from_result_table(response.primary_results[0])
            
            if not result.empty:
                return result.iat[0]
            else:
                return incidentTime
        except KustoServiceError as e:
            return incidentTime
        except Exception as e:
            return incidentTime
        
    ####### NRP #######
    def executeNrpQuery(self, subscriptionId: str, incidentTime: str, incidentId:int, resourceGroup: str = 'temp') -> pd.DataFrame:
        queryStr = f'{queryQos}logsOfInterest(\'{subscriptionId}\', \'{resourceGroup}\', datetime(\'{incidentTime}\'))'
        try:
            resultDf = dataframe_from_result_table(nrpClient.execute('mdsnrp', queryStr).primary_results[0])
            if not resultDf.empty:
                resultDf = self.parseErrorDetails(resultDf)
                resultDf = self.mapToTeams(resultDf)
                resultDf = self.getPredictedOwningTeam(resultDf)
                resultDf['TIMESTAMP'] = resultDf['TIMESTAMP'].apply(Helper.formattedDatetime)
                
                # A check to see if it's empty after removing rows in previous functions
                if resultDf.empty:
                    return pd.DataFrame({'status': ['no_data'], 'message': [f'executeNrpQuery/others: Unable to match ErrorDetails to a team for incident: {incidentId}']})
                return resultDf
            else:
                return pd.DataFrame({'status': ['no_data'], 'message': [f'executeNrpQuery: No ErrorDetails found in NRP table for incident: {incidentId}']})
        except KustoServiceError as e:
            return pd.DataFrame({'status': ['error'], 'message': [str(e)]})
        except Exception as e:
            return pd.DataFrame({'status': ['error'], 'message': [str(e)]})

    # Break up errorDetails by the class paths, gets rid of a lot of extraneous info and NRP mention overload - depended on class path not changing
    def parseErrorDetails(self, errorLogs: pd.DataFrame) -> pd.DataFrame:
        def cleanLines(lines: List[str]) -> List[str]:
            cleanedLines = []
            for line in lines:
                # Identify class paths by form X:\\class\path\here
                match = re.search(r'bt\\[0-9]+\\repo\\src\\sources\\([a-zA-Z\\]+)', line)
                if match:
                    path = match.group(1)
                    cleanedPath = re.sub(r'[0-9]+', '', path).replace('\\', ' ')
                    cleanedLines.append(cleanedPath)
            return cleanedLines
        
        # Remove any rows where there are no class paths in ExceptionCallStack
        errorLogs['ExceptionCallStack'] = errorLogs['ErrorDetails'].str.split('\n').apply(cleanLines)
        errorLogs = errorLogs[errorLogs['ExceptionCallStack'].map(len) > 0]
        return errorLogs

    def mapToTeams(self, errorLogs: pd.DataFrame) -> pd.DataFrame:        
        def mapLineToTeam(classPaths: List[str]) -> List[Dict[str, Any]]:
            teamMatchInfo = {}
            for classPathIndex, classPath in enumerate(classPaths):
                for nrpTeamName, icmPortalTeamName in teamMap.items():
                    matches = list(re.finditer(nrpTeamName.lower(), classPath.lower()))
                    numMatches = len(matches)
                    if matches:
                        # The match that is furthest down the class path is the most relevant
                        deepestMatch = matches[-1]
                        # Find how many words came before (for index ranking system)
                        classesBeforeFoundTeam = classPath[:deepestMatch.start()]
                        numClassesBeforeFoundTeam = len(classesBeforeFoundTeam.split())

                        if nrpTeamName in teamMatchInfo:
                            teamMatchInfo[nrpTeamName]['matchCount'] += numMatches
                            # if match for same team is found further down the same classPath
                            if classPathIndex <= teamMatchInfo[nrpTeamName]['exceptionMethodIdx'][0]:
                                teamMatchInfo[nrpTeamName]['exceptionMethodIdx'] = [classPathIndex, numClassesBeforeFoundTeam]
                        else:
                            teamMatchInfo[nrpTeamName] = teamMatchInfo[nrpTeamName] = {
                                'nrpTeamName': nrpTeamName,
                                'icmPortalTeamName': icmPortalTeamName,
                                'matchCount': numMatches,
                                'exceptionMethodIdx' : [classPathIndex, numClassesBeforeFoundTeam]
                            }
            return list(teamMatchInfo.values())
        
        # Remove any rows where its not able to map the log to a team
        errorLogs['MappedTeams'] = errorLogs['ExceptionCallStack'].apply(mapLineToTeam)
        errorLogs = errorLogs[errorLogs['MappedTeams'].map(len) > 0]
        return errorLogs

    def getPredictedOwningTeam(self, errorLogs: pd.DataFrame) -> pd.DataFrame:
        def sortingCriteria(team: Dict[str, Any]) -> tuple:
            # Sort by highest match count, if tie then lowest classPath, if tie then deepest class
            return (-team['matchCount'], team['exceptionMethodIdx'][0], -team['exceptionMethodIdx'][1])

        def getTeam(MappedTeams: List[Dict[str, Any]]) -> str:
            sorted_teams = sorted(MappedTeams, key=sortingCriteria)
            if sorted_teams:
                # Return the ICM portal equivalent of the teamName
                return sorted_teams[0]['icmPortalTeamName']
            return ''

        errorLogs['PredictedOwningTeam'] = errorLogs['MappedTeams'].apply(getTeam)
        return errorLogs 

    ####### Shared Processing #######
    # Condense multiple logs from nrp table to get one predicted owning team
    def combineNrpLogs(self, nrpDf: pd.DataFrame) -> pd.DataFrame:
        # Check if all PredictedOwningTeam values are the same
        if nrpDf['PredictedOwningTeam'].nunique() == 1:
            # Get the log with the most mentions of that team
            mostMentionsLog = nrpDf.loc[nrpDf['MappedTeams'].apply(lambda teams: sum(team['icmPortalTeamName'] == nrpDf['PredictedOwningTeam'].iloc[0] for team in teams)).idxmax()]
            newDf = pd.DataFrame([mostMentionsLog])
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
        
        # remove columns for icm and nrp tables that aren't valuable in the final output
        mergedDf = mergedDf.drop(columns=['ErrorDetails','StackTrace', 'Provider', 'ProviderName', 'CorrelationRequestId', 'ErrorCode', 'ResourceGroup', 'OperationId', 'OperationName', 'MappedTeams', 'SupportTicketId'], errors='ignore')
        
        # Add bool value for if the PredictedOwningTeam is mentioned in the found team history - only useful for resolved ICMs
        mergedDf['PredictedTeamInHistory'] = mergedDf.apply(
            lambda row: any(team['OwningTeamName'].lower() == row['PredictedOwningTeam'].lower() for team in row['TeamHistory']),
            axis=1
        )
        return mergedDf

    # Run all queries and parsing for a single icm
    def runBody(self, incidentId: str) -> pd.DataFrame:
        if not incidentId:
            return pd.DataFrame({'status': ['error'], 'message': ['incident_id is required']})
    
        icmResult = self.executeIcmQuery(incidentId)
        if 'error' in icmResult.columns:
            return icmResult
        #print({'icmResult': icmResult.to_dict(orient='records')})
    
        subscriptionId = icmResult.iloc[0]['SubscriptionId']
        incidentTime = self.executeTimeQuery(subscriptionId, icmResult.iloc[0]['IncidentStartTime'])
    
        nrpResult = self.executeNrpQuery(subscriptionId, incidentTime, incidentId)
        if 'status' in nrpResult.columns:
            return nrpResult
        #print({'nrpResult': nrpResult.to_dict(orient='records')})
    
        logTLDR = self.combineNrpIcm(nrpResult, icmResult)
        if 'status' in logTLDR.columns:
            return logTLDR
    
        return logTLDR


@app.route('/api/resource', methods=['GET'])
def handle_resource():
    if request.method == 'GET':
        incidentIdsInput = request.args.getlist('incident_id')
    elif request.method == 'POST':
        data = request.json
        incidentIdsInput = data.get('incident_id', [])
    
    incidentIdsInput = [int(value) for value in incidentIdsInput]
    icmIdList = []
    allIcmDf = pd.DataFrame()
    processor = Processing()
        
    if incidentIdsInput:
        icmIdList = incidentIdsInput
    else:
        icmIdList = list(processor.executeFindIcmsQuery())
        
    print('Ids of the ICMs to process: ', icmIdList)
    for incidentId in icmIdList:
        logTLDR = processor.runBody(incidentId)
    
        if 'status' in logTLDR.columns:
            print(f'Incident {incidentId} failed in', logTLDR['message'].iloc[0])
            continue
        print(f'Processing incident {incidentId}')
        allIcmDf = pd.concat([allIcmDf, logTLDR], ignore_index=True)

    # Add html table to output
    # allIcmDfjson = quote(allIcmDf.to_json(orient='records'))
    # tableLink = f'http://127.0.0.1:5000/show_table?logTLDR={allIcmDfjson}'            
    # return jsonify({'TableLink' : tableLink, 'allIcm_df': allIcmDf.to_dict(orient='records')})
        
    # Json output of whole df
    return jsonify({'allIcm_df': allIcmDf.to_dict(orient='records')})
    
    # Just Team name string(s)
    # return list(allIcmDf['PredictedOwningTeam'])

@app.route('/show_table', methods=['POST'])
def show_table():
    logTLDRjson = request.args.get('logtldr')
    
    if not logTLDRjson:
        return {'error': 'logTLDR data is required'}, 400
    
    # Convert JSON string back to DataFrame
    logTLDRjson = unquote(logTLDRjson)
    logTLDRdf = pd.read_json(StringIO(logTLDRjson))
    
    # Convert DataFrame to HTML table
    htmlTable = logTLDRdf.to_html()

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
    signal.signal(signal.SIGINT, signalHandler)
    app.run(debug=True)