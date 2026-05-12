import os
import requests
from dotenv import load_dotenv
load_dotenv()


def invoke_chute():
    api_token = os.getenv("CHUTES_API_KEY", "")

    headers = {
        "Authorization": "Bearer " + api_token,
        "Content-Type": "application/json"
    }
    
    body = {
        "input_args": {
            "input": "example-string",
            "model": None,
            #"dimensions": 768
        }
    }

    response = requests.post(
        "https://chutes-qwen-qwen3-embedding-8b.chutes.ai/v1/embeddings",
        headers=headers,
        json=body
    )
    
    # Print status code and response
    print(f"Status code: {response.status_code}")
    print(f"Response: {response.json()}")
    
    thing = response.json()
    if 'data' not in thing or len(thing['data']) == 0:
        raise ValueError("No embedding data returned")
    
    embeddings = thing['data'][0]['embedding']
    print(f"Embedding length: {len(embeddings)}")   
    return embeddings


if __name__ == "__main__":
    invoke_chute()

