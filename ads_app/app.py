from flask import Flask, request, jsonify, render_template
import os
from dotenv import load_dotenv
import requests
from google import genai
from google.genai.types import Tool, FunctionDeclaration, GenerateContentConfig
from google.cloud import bigquery

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configuration from environment
PROJECT_ID = os.getenv('GCP_PROJECT_ID', 'YOUR-PROJECT-ID')
LOCATION = os.getenv('GCP_LOCATION', 'us-central1')
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY', 'YOUR-API-KEY')
MODEL = os.getenv('MODEL_NAME', 'gemini-2.5-flash')
DATASET = os.getenv('DATASET_NAME', 'alaska_dept_faq_db')
TABLE = f"{PROJECT_ID}.{DATASET}.faqs_table"
SQL_MODEL = f"{PROJECT_ID}.{DATASET}.sql_connected_model"
EMBEDDING_TABLE = f"{PROJECT_ID}.{DATASET}.withEmbedding"

# Global clients
genai_client = None
bq_client = None
chat = None

def initialize_clients():
    """Initialize GenAI and BigQuery clients"""
    global genai_client, bq_client, chat

    print("Initializing clients...")

    # Init GenAI SDK client
    genai_client = genai.Client(
        vertexai=True,
        project=PROJECT_ID,
        location=LOCATION
    )

    # Init BigQuery client
    bq_client = bigquery.Client(project=PROJECT_ID)

    # Setup tools and config
    rag_tool = Tool(functionDeclarations=[rag_query_info])
    forecast_tool = Tool(functionDeclarations=[get_forecast_info])

    sys_msg = """
    * You are the chat bot for Alaska's Department of Snow (ADS).
    * You are friendly, but brief.
    * You answer questions related to the department and weather in Alaska, if a
    client asks a question about something else remind them that you are "only the
    agent for ADS, and can not speak for topics outside of that.
    * Reference Rag tool when answering FAQ about the department, there may be
    information related to the topic that can be mentioned as well.
    """

    config = GenerateContentConfig(
        tools=[rag_tool, forecast_tool],
        system_instruction=[sys_msg]
    )

    # Create chat session
    chat = genai_client.chats.create(
        model=MODEL,
        config=config
    )

    print("Clients initialized successfully!")

# Function Declarations
rag_query_info = FunctionDeclaration(
    name="rag_query",
    description="VectorSearch's user prompt to faq database and returns related content.",
    parameters={
        "type": "OBJECT",
        "properties": {
            "query": {
                "type": "STRING",
                "description": "The user's question or prompt to search for in the FAQ database."
            }
        },
        "required": ["query"]
    },
)

get_forecast_info = FunctionDeclaration(
    name="get_forcast",
    description="Given a city name returns a json about upcoming weather patterns",
    parameters={
        "type": "OBJECT",
        "properties": {
            "city": {
                "type": "STRING",
                "description": "A city in Alaska"
            }
        },
        "required": ["city"]
    },
)

# API Functions
def rag_query(user_input):
    """Takes user input and return context from faq doc using rag"""
    instructions = (f"""
    SELECT base.answer, base.question
    FROM VECTOR_SEARCH(
      TABLE `{EMBEDDING_TABLE}`,
      'ml_generate_embedding_result',
      (
        SELECT ml_generate_embedding_result, content AS query
        FROM ML.GENERATE_EMBEDDING(
          MODEL `{SQL_MODEL}`,
            (SELECT '{user_input}' AS content))
      ),
    top_k => 5,""" +
    """options => '{"fraction_lists_to_search": 0.01}'
    )
    """
    )

    # Query BQ
    res = bq_client.query(instructions)
    if res == None:
        print("No results from RAG query")
        return "No relevant information found."

    # Build context
    context = ""
    for row in res:
        context += row['question'] + "\n" + row['answer'] + ("-" * 20)

    return context

def get_latlong(city):
    """Return lat/long given a city in Alaska"""
    state = "alaska"
    address = f"{city}, {state}"

    geocode_url = f"https://maps.googleapis.com/maps/api/geocode/json?address={address}&key={GOOGLE_MAPS_API_KEY}"

    try:
        response = requests.get(geocode_url)
        response.raise_for_status()
        data = response.json()

        if data['status'] == 'OK' and data['results']:
            location = data['results'][0]['geometry']['location']
            lat = location['lat']
            long = location['lng']
            return lat, long
        else:
            print(f"Could not find coordinates for {city}, {state}. Status: {data['status']}")
            return None, None
    except requests.exceptions.RequestException as e:
        print(f"Error making Geocoding API call: {e}")
        return None, None

def get_points_metadata(lat, long):
    """Given lat/long coordinates return metadata wfo and x,y coordinate for forecast api call"""
    url = f"https://api.weather.gov/points/{lat},{long}"

    try:
        response = requests.get(url, headers={'User-Agent': 'ADS Chat App (demo@example.com)'})
        response.raise_for_status()
        data = response.json()

        properties = data.get('properties', {})
        wfo = properties.get('gridId')
        x = properties.get('gridX')
        y = properties.get('gridY')

        if wfo and x is not None and y is not None:
            return wfo, x, y
        else:
            print(f"Could not find WFO, gridX, or gridY for {lat},{long}")
            return None, None, None
    except requests.exceptions.RequestException as e:
        print(f"Error making NWS /points API call: {e}")
        return None, None, None

def get_forecast(city):
    """Given a city return a forecast json"""
    lat, long = get_latlong(city)
    print(f"Coordinates: {lat} {long}")

    if lat is None or long is None:
        return None

    wfo, grid_x, grid_y = get_points_metadata(lat=lat, long=long)

    if not all([wfo, grid_x, grid_y]):
        return None

    forecast_url = f"https://api.weather.gov/gridpoints/{wfo}/{grid_x},{grid_y}/forecast"

    try:
        response = requests.get(forecast_url, headers={'User-Agent': 'ADS Chat App (demo@example.com)'})
        response.raise_for_status()
        forecast_data = response.json()
        return forecast_data['properties']['periods']
    except requests.exceptions.RequestException as e:
        print(f"Error making NWS forecast API call: {e}")
        return None

def generate_response(user_prompt):
    """Generate response from chat with function calling"""
    print(f"User: {user_prompt}")

    response = chat.send_message(user_prompt)

    # Check if function call is needed
    if response.candidates[0].content.parts[0].function_call:
        function_name = response.candidates[0].content.parts[0].function_call.name
        args = response.candidates[0].content.parts[0].function_call.args

        print(f"Function call: {function_name} with args: {args}")

        # Which function do we call?
        if function_name == "rag_query":
            context = rag_query(args["query"])
        elif function_name == "get_forcast":
            context = get_forecast(args["city"])
        else:
            context = "Unknown function call"

        # Get final response with context
        final_prompt = f"{user_prompt}\nContext: {context}"
        response = chat.send_message(final_prompt)

    response_text = response.text
    print(f"AI: {response_text}")
    return response_text

# Flask Routes
@app.route('/')
def index():
    """Serve the chat interface"""
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def chat_endpoint():
    """Handle chat messages"""
    try:
        data = request.json
        user_message = data.get('message', '')

        if not user_message:
            return jsonify({'error': 'No message provided'}), 400

        # Generate response
        bot_response = generate_response(user_message)

        return jsonify({
            'response': bot_response
        })

    except Exception as e:
        print(f"Error in chat endpoint: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    # Initialize clients on startup
    initialize_clients()

    # Run Flask app
    print("Starting Flask app on http://localhost:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)