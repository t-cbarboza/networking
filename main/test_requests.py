import requests
import json
import os

# Define the base URL for your Flask app
base_url = 'http://127.0.0.1:5000/api/resource'

# Function to save JSON to a file
def save_json_to_file(data, filename):
    with open(filename, 'w') as outfile:
        json.dump(data, outfile, indent=4)

# Example GET request
def test_get_request(input_list: list, output_filename: str):
    params = {'incident_id': input_list}
    response = requests.get(base_url, params=params)
    print("GET Response:")
    try:
        response_json = response.json()
        save_json_to_file(response_json, output_filename)
        print(f"Response saved to {output_filename}")
    except requests.exceptions.JSONDecodeError:
        print("Response is not in JSON format. Raw response:")
        with open(output_filename, 'w') as outfile:
            outfile.write(response.text)
        print(f"Raw response saved to {output_filename}")

if __name__ == '__main__':
    # Create output directory if it doesn't exist
    output_dir = 'output'
    os.makedirs(output_dir, exist_ok=True)

    # # Test with multiple incident IDs
    # print("Testing GET with multiple incident IDs")
    # test_get_request([511101094, 519639582, 526186661, 525907329], os.path.join(output_dir, 'get_multiple_incidents.json'))
    
    # Test with a single incident ID
    print("Testing GET with a single incident ID")
    test_get_request([511101094], os.path.join(output_dir, 'get_single_incident.json'))
    
    #  # Test with a single incident ID
    # print("Testing GET with no incident ID, query for ICMs")
    # test_get_request([], os.path.join(output_dir, 'get_incidents_from_query.json'))
