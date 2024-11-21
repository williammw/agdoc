import os
from openai import OpenAI

XAI_API_KEY = os.getenv("XAI_API_KEY")
# print(XAI_API_KEY)
client = OpenAI(
    api_key=XAI_API_KEY,
    base_url="https://api.x.ai/v1",
)

completion = client.chat.completions.create(
    model="grok-beta",
    messages=[
        {"role": "system", "content": "You are Grok, a chatbot inspired by the Hitchhikers Guide to the Galaxy."},
        {"role": "user", "content": "What is the meaning of life, the universe, and everything?"},
    ],
)

print(completion.choices[0].message)
