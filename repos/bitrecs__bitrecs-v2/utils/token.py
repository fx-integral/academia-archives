import tiktoken

def get_token_count(prompt: str, encoding_name: str="o200k_base") -> int:
    encoding = tiktoken.get_encoding(encoding_name)
    tokens = encoding.encode(prompt)
    return len(tokens)
    