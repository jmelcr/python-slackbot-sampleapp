import os
import re
import logging
import threading
from flask import Flask
from flask import request
from slack import WebClient
from slackeventsapi import SlackEventAdapter
from randombot import RandomBot
import openai
from openai import OpenAI

# Initialize a Flask app to host the events adapter
app = Flask(__name__)
# Create an events adapter and register it to an endpoint in the slack app for event injestion.
slack_events_adapter = SlackEventAdapter(os.environ.get("SLACK_EVENTS_TOKEN"), "/slack/events", app)

# Initialize a Web API client
slack_web_client = WebClient(token=os.environ.get("SLACKBOT_TOKEN"))

# OpenAI API key to use and model +parameters
openai.api_key = os.environ.get("OPENAI_API_KEY")
chat_max_tokens = int(os.environ.get("CHAT_MAX_TOKENS"))
chat_request_timeout = float(os.environ.get("CHAT_REQUEST_TIMEOUT"))
openai_llm_model_type = str(os.environ.get("OPENAI_LLM_MODEL_TYPE"))
openai_image_gen_model_type = str(os.environ.get("OPENAI_IMG_GEN_MODEL_TYPE"))
openai_image_size = str(os.environ.get("OPENAI_IMG_SIZE"))

def random_action(channel, action=None, **kwargs):
    """Determine which action to perform based on parameter. For roll die if 
    a kwarg of sides is passed in and it's a valid integer roll a dSIDES die
    """
    # Create a new CoinBot
    random_bot = RandomBot(channel)

    if action == "coin":
        message = random_bot.flip_coin()
    elif action == "die":
        sides = kwargs.get("sides", None)
        if sides is None or isinstance(sides, int) is False:
            message = random_bot.roll_die()
        else:
            print(f"We got here. Sides: {sides}")
            message = random_bot.roll_die(sides)
    elif action == "card":
        message = random_bot.random_card()

    # Post the onboarding message in Slack
    slack_web_client.chat_postMessage(**message)


# When a 'message' event is detected by the events adapter, forward that payload
# to this function.
@slack_events_adapter.on("message")
def message(payload):
    """Parse the message event, and if the activation string is in the text,
    simulate a coin flip and send the result.
    If neither of the >random actions< is triggered, 
    treat the text as prompt for chatGPT to complete. 
    """

    if request.method == 'POST':
        # Get the event data from the payload
        event = payload.get("event", {})

        # Get the text from the event that came through
        text = event.get("text")

        # Check and see if the activation phrase was in the text of the message.
        # If so, execute the code to flip a coin.
        if "flip a coin" in text.lower():
            # Since the activation phrase was met, get the channel ID that the event
            # was executed on
            channel_id = event.get("channel")
            # Execute the random action as a coin flip
            return random_action(channel_id, action="coin")
        elif "roll a die" in text.lower() or "roll a dice" in text.lower():
            # Since the activation phrase was met, get the channel ID that the event
            # was executed on
            channel_id = event.get("channel")
            # Execute the random action as a coin flip
            return random_action(channel_id, action="die")
        elif "pick a card" in text.lower() or "choose a card" in text.lower():
            # Since the activation phrase was met, get the channel ID that the event
            # was executed on
            channel_id = event.get("channel")
            # Execute the random action as a coin flip
            return random_action(channel_id, action="card")
        elif "roll a d" in text.lower():
            # Since the activation phrase was met, get the channel ID that the event
            # was executed on
            channel_id = event.get("channel")

            # Strip out the number from the command
            droll = text.split("roll a")[1].strip().split()[0]
            try:
                int(droll[1:])
            except ValueError:
                pass
            else:
                return random_action(channel_id, action="die", sides=int(droll[1:]))
        elif text.lower().startswith(("q ","q:")):
            # it is crucial that the bot does not respond to anything 
            # as then it would start talking to itself.
            # Having a requirement to start the prompt with something (here "q " or "q:")
            # makes it rather unprobable that the bot will make prompts to itself. 
            # Then send the prompt to openAI API for reply
            # code inspired by https://www.pragnakalp.com/build-an-automated-ai-powered-slack-chatbot-with-chatgpt-using-flask/
            # 
            # this code used to have troubles as described (and solved) at: 
            # https://stackoverflow.com/questions/57418116/how-to-send-a-http-200-for-an-event-request-for-slack-api-in-python-request#57420023

            prompt = text[2:]
            
            # starting a new thread for doing the actual openAI API calling
            x = threading.Thread(
                    target=chat_completion,
                    args=(event, prompt)
                )
            x.start()
            return None
        elif text.lower().startswith(("qi ","qi:")):
            prompt = text[3:]
            
            # starting a new thread for doing the actual openAI API calling
            x = threading.Thread(
                    target=img_generation,
                    args=(event, prompt)
                )
            x.start()
            return None



def chat_completion(event, prompt):
    """
    generate a response to the given prompt using GPT-based completion API
    """
    channel_id = event.get('channel')
    user_id = event.get('user')
     
    openai_client = OpenAI()

    try:
        # use openAI API to respond to the prompt using chat-completion method
        completion = openai_client.client.chat.completions.create(
            model=openai_llm_model_type, 
            max_tokens=chat_max_tokens,
            user=user_id,
            n=1,
            request_timeout=chat_request_timeout,
            messages=[
               {"role": "system", "content": "You are a helpful assistant that provides concise replies to the point."}, 
               {"role": "user", "content": prompt}
            ]
            )
        response = completion['choices'][0]['message']['content']
    except:
        response = "(connection to chatGPT probably timed out)"
	
    # include the response in a standard message block
    message_block = {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": response
        },
    }
    # post the message to Slack
    slack_web_client.chat_postMessage(channel=channel_id,blocks=[message_block,])
    return response


def img_generation(event, prompt):
    """
    generate image for the given prompt 
    and return link to the image as a message
    """
    channel_id = event.get('channel')
    user_id = event.get('user')
     
    openai_client = OpenAI()

    try:
        # use openAI API to respond to the prompt using image generation
        generated_image = openai_client.images.generate(
          model=openai_image_gen_model_type, 
          prompt=prompt,
          n=1,
          size=openai_image_size
          )
        image_url = generated_image.data[0].url
        response = "link to image: {}".format(image_url) 
    except:
        response = "(connection to chatGPT probably timed out)"
	
    # include the response in a standard message block
    message_block = {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": response
        },
    }
    # post the message to Slack
    slack_web_client.chat_postMessage(channel=channel_id,blocks=[message_block,])
    return response
            

if __name__ == "__main__":
    # Create the logging object
    logger = logging.getLogger()

    # Set the log level to DEBUG. This will increase verbosity of logging messages
    logger.setLevel(logging.DEBUG)

    # Add the StreamHandler as a logging handler
    logger.addHandler(logging.StreamHandler())

    # Run our app on our externally facing IP address on port 3000 instead of
    # running it on localhost, which is traditional for development.
    app.run(host='0.0.0.0', port=8080, debug=False)
