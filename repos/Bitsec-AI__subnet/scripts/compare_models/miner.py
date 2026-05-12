#!/usr/bin/env python3
"""
Script to compare different LLM models for finding vulnerabilities in Solidity code.

This script takes potentially vulnerable Solidity code and analyzes it with different models and logs the results
and costs to files with timestamps.

To run:

```
$ python scripts/compare_models/miner.py
```
It will run all the models in 
- MODELS_TO_TEST_STRUCTURED_OUTPUT, and output each model's PredictionResponse to the console
- MODELS_TO_TEST_UNSTRUCTURED_OUTPUT and output the raw response to the console

It will also create a subdirectory `model_comparisons`, then a subdirectory `miner`, and then a directory below that with date timestamp. This will contain:

- input_clean_code.sol -- Code it started with
- input_vulnerability.md -- Description of vulnerability injected
- results.json -- The results from all the models, particularly the cost and time taken for each model

Plus files to contain each models result named by the model name, eg

- gpt-4o-mini_code.sol   
- o1-2024-12-17_code.sol 
- o1-mini_code.md -- note it is .md because the model can't return structured output
- etc

Finally, it will print the total cost and time taken to the console.
"""
MODEL_TO_CREATE_VULNERABILITY = "gpt-4o-mini"
MODELS_TO_TEST_STRUCTURED_OUTPUT = [
    "gpt-4o-mini",
    "gpt-4o",
    "o1",
    "o3-mini",
    # "gpt-4.5-preview",
]
MODELS_TO_TEST_UNSTRUCTURED_OUTPUT = [
    "o1-mini",
]
SCREEN_WIDTH = 120


import os
import sys
import json
from typing import Dict, Any
import time
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

# Configure paths
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(os.path.dirname(CURRENT_DIR))  # Go up two levels

# Add project root to Python path
sys.path.insert(0, ROOT_DIR)

from bitsec.protocol import PredictionResponse
from bitsec.utils.data import create_challenge_with_inputs, verify_solidity_compilation
from bitsec.utils.llm import get_total_spend_cents, get_total_spend_cents_description, show_first_non_zero_digit
from bitsec.miner.prompt import analyze_code
from utils import before_all_tests, after_all_tests, format_vulnerability_info, format_duration

# Prettier output
console = Console()


def run_model_comparison(
    output_dir: str,
    vulnerable_code: str,
) -> Dict[str, Any]:
    """
    Analyze vulnerable code with different models and collect results, including detected vulnerabilities and fixed code.
    
    Args:
        output_dir (str): Directory to save results
        vulnerable_code (str): The vulnerable code to analyze
        
    Returns:
        Dict[str, Any]: Dictionary containing results and costs for each model
    """
    results = {}
    
    for model in list(set(MODELS_TO_TEST_STRUCTURED_OUTPUT + MODELS_TO_TEST_UNSTRUCTURED_OUTPUT)):
        fixed_code = ""

        console.print(f"\nCalling {model} ...")
        initial_spend = get_total_spend_cents()
        start_time = time.time()
        
        try:
            # Analyze vulnerable code with current model
            is_unstructured = model in MODELS_TO_TEST_UNSTRUCTURED_OUTPUT
            response = analyze_code(
                code=vulnerable_code,
                model=model,
                respond_as_str=is_unstructured
            )
            
            # Calculate metrics
            duration = time.time() - start_time
            cost = get_total_spend_cents() - initial_spend
            cost_pretty = show_first_non_zero_digit(cost)
            cost_description = get_total_spend_cents_description()

            # Print detailed info with pretty formatting
            title = Text(justify="left")
            title.append(f"{model}, Cost: {cost_pretty}, {cost_description}, Time: {format_duration(duration)} ")

            if is_unstructured:
                output_filename = f"{model}.md"
                output_path = os.path.join(output_dir, output_filename)
                with open(output_path, 'w') as f:
                    f.write(response)

                content = f"Model returned unstructured output\nSaved to: {output_filename}"
                title.append("? Unstructured output", style="yellow")
            else:
                content = f"Prediction, vulnerable? {response.prediction}\n\n"

                # Save generated code to file
                if "rewritten_code_to_fix_vulnerability" in response:
                    fixed_code = response.rewritten_code_to_fix_vulnerability
                    code_filename = f"{model}.sol"
                    code_path = os.path.join(output_dir, code_filename)
                    with open(code_path, 'w') as f:
                        f.write(fixed_code)
                    
                    # test compilation
                    if verify_solidity_compilation(fixed_code):
                        title.append("✓ Code compiled", style="green")
                    else:
                        content += f"\n\nModel returned code that did not compile!"
                        title.append("✗ did not compile!", style="red")
                
                # Output vulnerabilities
                vulnerabilities_filename = f"{model}_vulnerabilities.md"
                vulnerabilities_path = os.path.join(output_dir, vulnerabilities_filename)
                with open(vulnerabilities_path, 'w') as f:
                    f.write(format_vulnerability_info(response.vulnerabilities))

                content += format_vulnerability_info(response.vulnerabilities)

            subtitle = title.copy() if len(content) > 1000 else None
            console.print(Panel(content, title=title, subtitle=subtitle, expand=False, width=SCREEN_WIDTH))

            results[model] = {
                "success": True,
                "cost_cents": cost_pretty,
                "cost_description": cost_description,
                "duration_seconds": duration,
                "prediction_response": response,
            }
        except Exception as e:
            duration = time.time() - start_time
            results[model] = {
                "success": False,
                "duration_seconds": duration,
                "error": str(e)
            }
            console.print(Panel(f"Error: {str(e)}", title=f"[red]✗ {model} ({format_duration(duration)})[/red]", expand=False, width=SCREEN_WIDTH))
    
    return results

def main():
    """Main function to run model comparison."""
    output_dir, clean_code, vulnerability_description, start_time = before_all_tests('miner')

    # Make vulnerable code with the vulnerability injected
    print(f"Creating vulnerable code with {MODEL_TO_CREATE_VULNERABILITY}...")
    vulnerable_code, vulnerability_info, cost, cost_description = create_challenge_with_inputs(
        clean_code=clean_code,
        vulnerability_description=vulnerability_description,
        model=MODEL_TO_CREATE_VULNERABILITY,
    )
    print("Done")
   
    # Run comparison
    results = run_model_comparison(output_dir, vulnerable_code)

    # Save results
    after_all_tests(output_dir, start_time, results)

if __name__ == "__main__":
    main() 