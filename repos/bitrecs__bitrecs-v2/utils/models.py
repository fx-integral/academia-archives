

def normalize_model_name(model_name: str, should_lower: bool = False) -> str:
    if not model_name:
        return model_name
    model_name = model_name.split('/')[-1] if '/' in model_name else model_name
    model_name = model_name.split(':')[0] if ':' in model_name else model_name
    return model_name.lower() if should_lower else model_name