# -*- coding: utf-8 -*-
# ! pip install --upgrade --quiet google-cloud-aiplatform google-cloud-aiplatform[evaluation]
# ! pip install --quiet ipytest
# ! pip install --upgrade google-genai
# ! pip install google-cloud-modelarmor
# ! pip install --upgrad google-cloud-bigquery
# ! pip install requests==2.31.0

import os
import pandas as pd
from IPython.display import display, Markdown, HTML

import requests

import pytest
import ipytest
ipytest.autoconfig()

from vertexai.evaluation import (
    MetricPromptTemplateExamples,
    EvalTask,
)

from google import genai
from google.genai.types import Tool, ToolCodeExecution, GenerateContentConfig, SafetySetting, Part, FunctionDeclaration
from google.cloud import modelarmor_v1
from google.api_core.client_options import ClientOptions

import datetime
from google.cloud import bigquery


import google.cloud.logging
import logging
import time

project_id = ! gcloud config get project
project_id = project_id[0]
location = "us-central1"
MY_API_KEY="AIzaSyD1lJ1joRn5ctAKQL3BA0GdoLDYCHJHTyY"

model = "gemini-2.5-flash"


mydataset = "alaska_dept_faq_db"#
mytable = f"""{project_id}.{mydataset}.faqs_table""" 

mymodel = f"""{project_id}.{mydataset}.sql_connected_model"""
embededTable = f"""{project_id}.{mydataset}.withEmbedding"""



def init():
# init genai sdk client
  genai_client = genai.Client(
      vertexai=True,
      project=project_id,
      location=location
  )
  # init big query client
  bq_client = bigquery.Client(project=project_id)
  datasets = list(bq_client.list_datasets())


  # init the Cloud Logging client
  from google.cloud import logging as cloud_logging
  log_client = google.cloud.logging.Client()
  log_client.setup_logging()

  log_handler = log_client.get_default_handler()

  cloud_logger = logging.getLogger("cloudLogger")
  cloud_logger.setLevel(logging.INFO)
  cloud_logger.addHandler(log_handler)

  ## MODEL ARMOR

  armor_id = f"projects/{project_id}/locations/{location}/templates/ADS_model_armor"


  armoredClient = modelarmor_v1.ModelArmorClient(
      transport="rest",
      client_options=ClientOptions(
          api_endpoint=f"modelarmor.{location}.rep.googleapis.com"
      ),
  )


  """
  Finalize Tool calling and Configurations
  """

  rag_tool = Tool(functionDeclarations=[rag_query_info])
  forecast_tool = Tool(functionDeclarations=[get_forecast_info])

  sys_msg = """
  * You are the chat bot for Alaska's Department of Snow (ADS).
  * You are friendly, but breif.
  * You answer questions related to the department and weather in Alaska, if a
  client asks'a question about something else remind them that you are "only the
  agent for ADS, and can not speak for topics outside of that.
  * Refrence Rag tool when answering FAQ about the department, there may be
  information related to the topic that can be mentioned as well.
  """

  config = GenerateContentConfig(
      tools=[rag_tool, forecast_tool],
      system_instruction=[sys_msg]
      )


  chat = genai_client.chats.create(
    model=model,
    config=config
  )


"""## Functions

* https://www.weather.gov/documentation/services-web-api
* https://console.cloud.google.com/google/maps-apis/home;onboard=true?project=qwiklabs-gcp-03-29c3da30d8ab

"""

def sanatize_text(prompt):
  # Returns True (1) if is passes the sanatization test
  # Returns False (0) if it fails and needs to be disregaurded.
  user_prompt_data = modelarmor_v1.types.DataItem(text=prompt)

  ## breaks
  request = modelarmor_v1.SanitizeUserPromptRequest(
    name= armor_id,
    user_prompt_data=user_prompt_data,
  )
  response = armoredClient.sanitize_user_prompt(request=request)
  #print(response)
  #print(str(response.sanitization_result.filter_match_state))
  if response.sanitization_result.filter_match_state == 1:
    return 1
  else:
    return 0


def sanitize_response(response_text):
  # If response_text has no value, then return an error message
  if not response_text:
    return "An unknown error has occured."

  model_response_data = modelarmor_v1.DataItem(text = response_text)
  request = modelarmor_v1.SanitizeModelResponseRequest(
      name= armor_id,
      model_response_data=model_response_data,
      )

  response = genai_client.sanitize_model_response(request=request)

  # Return the Sanitized text if sensitive data was found.
  # If no sensitive data was found, just return the response text passed to the function.
  if str(response.sanitization_result.filter_match_state) == "FilterMatchState.MATCH_FOUND":
    sanitized_text = response.sanitization_result.filter_results["sdp"].sdp_filter_result.deidentify_result.data.text
    return sanitized_text
  else:
    # There was no invalid data, so just return what was sent in
    return response_text

"""### TOOL Function Decleration"""

rag_query_info = FunctionDeclaration(
    name="rag_query",
    description="VectorSearch's user prompt to faq database and returns related content.",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
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
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "A city in Alaska"
            }
        },
        "required": ["city"]
    },
)

"""### API Functions"""

# Takes user input and return context from faq doc using rag
def rag_query(user_input):

  ## Embed user query and find closest neighbors
  instructions = (f"""
    SELECT base.answer,	base.question
    FROM VECTOR_SEARCH(
      TABLE `{embededTable}`,
      'ml_generate_embedding_result',
      (
        SELECT ml_generate_embedding_result, content AS query
        FROM ML.GENERATE_EMBEDDING(
          MODEL `{mymodel}`,
            (SELECT '{user_input}' AS content))
      ),
    top_k => 5,""" +
    """options => '{"fraction_lists_to_search": 0.01}'
    )
    """
  )
  #print(instructions)

  ## Query BQ
  res = bq_client.query(instructions)
  if res == None:
    print(":( sorry no luck")

  ## Build context
  context = ""
  for row in res:
    context += row['question']+ "\n"+ row['answer'] + ("-" * 20)

  return context

# Using geolocation api from gcp and the api key MY_API_KEY
# return lat long given a city in alaska
# if the city does not exsist return none.
def get_latlong(city):
  state = "alaska"
  address = f"{city}, {state}"

  geocode_url = f"https://maps.googleapis.com/maps/api/geocode/json?address={address}&key={MY_API_KEY}"

  try:
    response = requests.get(geocode_url)
    response.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)
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

# helper function
# Given lat long coordinates return metadata wfo and x,y coordinate for forcast api call
# https://api.weather.gov/points/{lat},{long}
def get_points_metadata(lat, long):
  url = f"https://api.weather.gov/points/{lat},{long}"

  try:
    response = requests.get(url, headers={'User-Agent': 'Google Colab Weather App (your_email@example.com)'})
    response.raise_for_status()  # Raise an HTTPError for bad responses (4xx or 5xx)
    data = response.json()

    # Extracting the required information
    properties = data.get('properties', {})
    wfo = properties.get('gridId')
    x = properties.get('gridX')
    y = properties.get('gridY')

    if wfo and x is not None and y is not None:
      return wfo, x, y
    else:
      print(f"Could not find WFO, gridX, or gridY for {lat},{long}. Response properties: {properties}")
      return None, None, None
  except requests.exceptions.RequestException as e:
    print(f"Error making NWS /points API call: {e}")
    return None, None, None
  y=""
  url = f"https://api.weather.gov/points/{lat},{long}"

  return wfo, x, y


# Given a city return a forcast json
# It is a list of items for different times
# "name" = tonight
# "shortForecast": "Slight Chance Light Rain",
# "detailedForecast": "A slight chance of rain. Cloudy, with a high near 34. Northeast wind ...
def get_forecast(city):

  lat_anchorage, long_anchorage = get_latlong(city)
  print (f"{lat_anchorage} {long_anchorage}")

  wfo,grid_x,grid_y = get_points_metadata(lat=lat_anchorage, long=long_anchorage)

  # Construct the forecast URL
  forecast_url = f"https://api.weather.gov/gridpoints/{wfo}/{grid_x},{grid_y}/forecast"

  # Make the API call to get the forecast
  try:
    # NWS API recommends a User-Agent header
    response = requests.get(forecast_url, headers={'User-Agent': 'Google Colab Weather App (your_email@example.com)'})
    response.raise_for_status()  # Raise an HTTPError for bad responses (4xx or 5xx)
    forecast_data = response.json()
    return forecast_data['properties']['periods']
  except requests.exceptions.RequestException as e:
    print(f"Error making NWS forecast API call: {e}")
    return None


"""## GENERATE response function

I don't know why, but sometimes it doesn't run the first time? But I havn't been able to trigger it consistantly
"""

# function calling isn't automatic. This function checks if the AI determins there needs to be
# a tool call made and makes it.
def generate(user_prompt) -> str:

  # Check if User input is safe
  if sanatize_text(user_prompt) == False:
    return "I'm sorry this prompt has flagged the security system, please ask something else."
  else:
    # log user input if safe
    cloud_logger.info(f"User Message: {user_prompt}")

  response = chat.send_message(user_prompt)

  # Do we need to make a function
  if response.candidates[0].content.parts[0].function_call:
    function_name = response.candidates[0].content.parts[0].function_call.name
    args = response.candidates[0].content.parts[0].function_call.args

    # Which function do we call?
    if function_name == "rag_query":
      context = rag_query(args["query"])
    elif function_name == "get_forcast":
      context = get_forecast(args["city"])
    else:
      context = "Unknown function call"

    # Get final prompt with proper context
    final_prompt = f"{user_prompt}\nContext: {context}"
    response = chat.send_message(final_prompt)

    # Sanatize AI response
    response = sanitize_response(response)

  # Log safe AI response and return
  cloud_logger.info(f"AI Response: {response.text}")
  return response.text
