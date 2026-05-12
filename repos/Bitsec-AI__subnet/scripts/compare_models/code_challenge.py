#!/usr/bin/env python3
"""
Script to compare different LLM models for challenge generation.

This script generates challenges using different models and logs the results
and costs to files with timestamps.

To run:

```
$ python scripts/compare_models/code_challenge.py
```
It will run all the models in 
- MODELS_TO_TEST_STRUCTURED_OUTPUT, and output each model's PredictionResponse to the console
- MODELS_TO_TEST_UNSTRUCTURED_OUTPUT and output the raw response to the console

It will also create a subdirectory `model_comparison_generation_results` and then a directory below that with date timestamp. This will contain:

- input_clean_code.sol -- Code it started with
- input_vulnerability.md -- Description of vulnerability injected
- results.json -- The results from all the models, particularly the cost and time taken for each model

Plus files to contain each models result named by the model name, eg

- gpt-4o-mini_generated_code.sol   
- o1-2024-12-17_generated_code.sol 
- o1-mini_output.md -- note it is .md because the model can't return structured output
- etc

Finally, it will print the total cost and time taken to the console.
"""
MODELS_TO_TEST_STRUCTURED_OUTPUT = [
    "gpt-4o-mini",
    "gpt-4o",
    "o1",
    "o3-mini",
]
MODELS_TO_TEST_UNSTRUCTURED_OUTPUT = [
    "o1-mini",
]
SCREEN_WIDTH = 120


import os
import sys
from datetime import datetime
import json
from typing import Dict, Any
from textwrap import dedent
import time
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

# Configure paths
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(os.path.dirname(CURRENT_DIR))  # Go up two levels

# Add project root to Python path
sys.path.insert(0, ROOT_DIR)

from bitsec.utils.data import create_challenge_with_inputs, verify_solidity_compilation
from bitsec.utils.llm import get_total_spend_cents, show_first_non_zero_digit
from utils import before_all_tests, after_all_tests, format_vulnerability_info, format_duration

# Prettier output
console = Console()

def run_model_comparison(
    clean_code: str,
    vulnerability_description: str,
    output_dir: str
) -> Dict[str, Any]:
    """
    Run challenge generation with different models and collect results.
    
    Args:
        clean_code (str): The secure code to modify
        vulnerability_description (str): Description of vulnerability to inject
        output_dir (str): Directory to save results
        
    Returns:
        Dict[str, Any]: Dictionary containing results and costs for each model
    """
    results = {}
    
    for model in list(set(MODELS_TO_TEST_STRUCTURED_OUTPUT + MODELS_TO_TEST_UNSTRUCTURED_OUTPUT)):
        console.print(f"Calling {model} ...")
        start_time = time.time()
        
        try:
            # Generate challenge with current model
            is_unstructured = model in MODELS_TO_TEST_UNSTRUCTURED_OUTPUT
            modified_code, vulnerability_info, cost, cost_description = create_challenge_with_inputs(
                clean_code=clean_code,
                vulnerability_description=vulnerability_description,
                model=model,
                respond_as_str=is_unstructured
            )
            
            # Calculate metrics
            duration = time.time() - start_time
            cost_pretty = show_first_non_zero_digit(cost)
            
            # Print detailed info with pretty formatting
            title = Text()
            title.append(f"{model}, Cost: {cost_pretty}, {cost_description}, Time: {format_duration(duration)} ")

            # Save generated code to file
            code_filename = f"{model}_generated_code.sol" if not is_unstructured else f"{model}_output.md"
            code_path = os.path.join(output_dir, code_filename)
            with open(code_path, 'w') as f:
                f.write(modified_code)

            # Save results
            vulnerability_info_dict = None
            if vulnerability_info is None:
                content = f"Model returned unstructured output\nSaved to: {code_filename}"
                title.append("? Unstructured output", style="yellow")
            else:
                vulnerability_info_dict = vulnerability_info.model_dump()
                content = format_vulnerability_info(vulnerability_info_dict)

                # test compilation
                if verify_solidity_compilation(modified_code):
                    title.append("✓ Code compiled", style="green")
                else:
                    content += f"\n\nModel returned code that did not compile!"
                    title.append("✗ did not compile!", style="red")

            console.print(Panel(content, title=title, expand=False, width=SCREEN_WIDTH))

            results[model] = {
                "success": True,
                "cost_cents": cost_pretty,
                "cost_description": cost_description,
                "duration_seconds": duration,
                "vulnerability_info": vulnerability_info_dict,
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
    output_dir, clean_code, vulnerability_description, start_time = before_all_tests('code_challenge')
   
    # Run comparison
    results = run_model_comparison(clean_code, vulnerability_description, output_dir)
    
    total_duration, total_cost = after_all_tests(output_dir, start_time, results)

if __name__ == "__main__":
    main() 