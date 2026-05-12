import os
import random

from openai import OpenAI


def simple_base_model_response(prompt: str, model: str = "gpt-3.5-turbo") -> str:
    """
    Only use this for testing.

    Returns a response from the base model for the given prompt.

    Args:
        prompt (str): The prompt to generate a response for.
        model (str): The model to use for the response.

    Returns:
        str: The response from the base model.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable not set.")

    client = OpenAI(api_key=api_key)
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a helpful therapist."},
            {"role": "user", "content": prompt}
        ]
    )
    content = completion.choices[0].message.content
    if content is not None:
        return content.strip()
    else:
        return ""

def generate_synthetic_samples():
    """
    Returns a list with a single synthetic prompt for evaluation of miners.
    """
    # TODO: Get prompts from a file or a database or a web service.
    prompts = [
        "How can I manage my anxiety?",
        "What should I do if I feel overwhelmed at work?",
        "How do I improve my sleep quality?",
        "I'm feeling sad lately, what can help?",
        "How can I build better relationships?",
        "What are some tips for handling stress?",
        "How do I set healthy boundaries?",
        "What can I do to boost my self-esteem?",
        "How do I cope with loneliness?",
        "What are effective ways to relax?",
    ]
    prompt = random.choice(prompts)

    return [{"input": prompt}]
