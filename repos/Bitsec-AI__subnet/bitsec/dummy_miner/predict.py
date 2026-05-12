from bitsec.protocol import PredictionResponse
from bitsec.dummy_miner.prompt import code_to_vulns

## Predicting vulnerabilities is a multifaceted task. Here are some example improvements:
# - train custom model
# - use a more powerful foundational model
# - improve prompt
# - increase inference time compute
# - augmented static analysis output
def predict(code: str) -> PredictionResponse:
    """
    Perform prediction. You may need to modify this if you train a custom model.

    Args:
        code (str): The input str is a challenge that either has a severe code vulnerability or does not.

    Returns:
        PredictionResponse: The predicted output value and list of vulnerabilities.
    """
    

    return code_to_vulns(code=code)