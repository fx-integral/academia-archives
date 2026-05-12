import random
import re


def add_comment_noise_simple(code: str) -> str:
    """Add a simple fake comment before the code."""
    return "// TODO: Fix security vulnerability" + "\n" + code
# Utility functions
def remove_comments(code: str) -> str:
    """Remove single line (except for SPDX license) and multiline comments from the code."""
    lines = code.splitlines()
    
    # Remove lines that contain only a comment (preserving SPDX)
    lines = [line for line in lines if not re.match(r"^\s*//(?!\s*SPDX).*", line)]
    
    code = normalize_whitespace('\n'.join(lines))

    return code

def normalize_whitespace(code: str) -> str:
    """
    Normalize whitespace while preserving indentation.
    
    Args:
        code: The source code string to normalize.
        
    Returns:
        str: Normalized code with consistent whitespace.
    """
    # Split into lines
    lines = code.splitlines()
    
    # Remove trailing whitespace on each line while preserving indentation
    lines = [line.rstrip() for line in lines]
    
    # Remove empty lines at start/end while preserving empty lines between code
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
        
    # Collapse multiple empty lines into one
    result = []
    prev_empty = False
    for line in lines:
        is_empty = not line.strip()
        if not (is_empty and prev_empty):
            result.append(line)
        prev_empty = is_empty
            
    return '\n'.join(result)
