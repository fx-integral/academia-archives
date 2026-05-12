#!/usr/bin/env python3
"""
Shared utils for compare_models scripts
"""

import os
import sys
from datetime import datetime
import json
from typing import Dict, Any, List
from textwrap import dedent
import time
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from bitsec.protocol import PredictionResponse, Vulnerability
from bitsec.utils.data import get_random_secure_filename, get_random_vulnerability_filename
from bitsec.utils.llm import get_total_spend_cents, show_first_non_zero_digit


def setup_output_dir(output_dir: str) -> str:
    """
    Create output directory with timestamp.
    
    Returns:
        str: Path to the created output directory
    """
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    output_dir = os.path.join("model_comparisons", output_dir, timestamp)
    os.makedirs(output_dir, exist_ok=True)
    return output_dir

def format_vulnerability_info(vulnerability_info: Dict | List[Vulnerability] | Vulnerability | None) -> str:
    """
    Format vulnerability information for display.
    
    Args:
        vulnerability_info (Dict | List[Vulnerability] | Vulnerability | None): Dictionary containing vulnerability information,
            a list of vulnerabilities directly, a single Vulnerability, or None for unstructured output
        
    Returns:
        str: Formatted string for display
    """
    if vulnerability_info is None:
        return "Model returned unstructured output, no vulnerability information available"
    
    if isinstance(vulnerability_info, Vulnerability):
        # Handle case where input is just one Vulnerability
        vulnerabilities = [vulnerability_info]
    elif isinstance(vulnerability_info, list):
        # Handle case where input is a list of Vulnerabilities
        vulnerabilities = vulnerability_info
    else:
        return "Invalid vulnerability information format"
        
    if not vulnerabilities:
        return "No vulnerabilities added!!!! :("
    
    output = []
    for vuln in vulnerabilities:
        try:
            # Handle multiline descriptions by proper indentation
            if isinstance(vuln, Vulnerability):
                description = dedent(vuln.description).strip() if vuln.description else ""
                description_lines = description.split("\n")
                indented_description = "\n      ".join(description_lines)
                
                output.append(f"  • Type: {vuln.category}")
                if "severity" in vuln:
                    output.append(f"    Severity: {vuln.severity}")
                output.append(f"    Description:\n      {indented_description}")
                if "line_ranges" in vuln and vuln.line_ranges:
                    output.append(f"    Line Numbers: {', '.join(map(str, vuln.line_ranges))}")
            else:
                # Fallback for dict-like objects
                description = dedent(vuln.get("description", "")).strip()
                description_lines = description.split("\n")
                indented_description = "\n      ".join(description_lines)
                
                output.append(f"  • Type: {vuln.get('category', 'Unknown')}")
                if vuln.get("severity", None):
                    output.append(f"    Severity: {vuln.get('severity', 'Unknown')}")
                output.append(f"    Description:\n      {indented_description}")
                if vuln.get("line_ranges", None):
                    line_ranges = vuln.get("line_ranges", None)
                    output.append(f"    Line Numbers: {', '.join(map(str, line_ranges))}")
        except Exception as e:
            output.append(f"  • Error formatting vulnerability: {str(e)}\nVulnerability: {vuln}")
            output.append("")

        output.append("")  # Add blank line between vulnerabilities
    
    return "\n".join(output)

def format_duration(seconds: float) -> str:
    """
    Format duration in seconds to a human readable string.
    
    Args:
        seconds (float): Duration in seconds
        
    Returns:
        str: Formatted duration string
    """
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    seconds = seconds % 60
    return f"{minutes}m {seconds:.1f}s"



def before_all_tests(destination: str):
    # Create output directory
    output_dir = setup_output_dir(destination)
    print(f"Saving results to: {output_dir}")
    
    # Get random sample files
    secure_filename = get_random_secure_filename()
    vulnerability_filename = get_random_vulnerability_filename()
    
    # Read input files
    clean_code = open(secure_filename, 'r').read()
    vulnerability_description = open(vulnerability_filename, 'r').read()

    # print first line of vulnerability description
    vulnerability_description_first_line = vulnerability_description.split('\n')[0]
    print(f"vulnerability_description: {vulnerability_description_first_line}")
    
    # Save input files for reference
    with open(os.path.join(output_dir, 'input_clean_code.sol'), 'w') as f:
        f.write(clean_code)
    with open(os.path.join(output_dir, 'input_vulnerability.md'), 'w') as f:
        f.write(vulnerability_description)

    start_time = time.time()

    return output_dir, clean_code, vulnerability_description, start_time

def after_all_tests(output_dir: str, start_time: float, results: Dict[str, Any]):
    """
    Save final results and print summary statistics.
    
    Args:
        output_dir (str): Directory to save results
        start_time (float): Start time of the test run
        results (Dict[str, Any]): Results from all model runs
        
    Returns:
        tuple[float, float]: Total duration and total cost
    """
    # Calculate total duration
    total_duration = time.time() - start_time
    total_cost = get_total_spend_cents()
    
    # Convert results to JSON serializable format
    json_results = {}
    for model, result in results.items():
        json_result = dict(result)  # Make a copy

        # Convert PredictionResponse to dict
        if "prediction_response" in json_result and isinstance(json_result["prediction_response"], PredictionResponse):
            json_result["prediction_response"] = json_result["prediction_response"].model_dump()
        json_results[model] = json_result
    
    # Save results
    results_file = os.path.join(output_dir, 'results.json')
    final_results = {
        "total_duration_seconds": total_duration,
        "total_cost_cents": total_cost,
        "models": json_results
    }
    
    with open(results_file, 'w') as f:
        json.dump(final_results, f, indent=2)

    print(f"\nTotal cost: {show_first_non_zero_digit(total_cost)}")
    print(f"Total time: {format_duration(total_duration)}")
    print(f"Results saved to: {output_dir}")

    return total_duration, total_cost