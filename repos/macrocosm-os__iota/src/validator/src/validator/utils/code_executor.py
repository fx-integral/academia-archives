import ast
import hashlib
from pathlib import Path
import inspect
from typing import Any, Dict


def execute_packaged_function(packaged_code: str, inputs: Dict[str, Any]) -> Any:
    """
    Execute a packaged function with given arguments.
    Assumes the target function is named 'main'.

    Args:
        packaged_code: The packaged code string from package_function
        inputs: Dictionary of arguments to pass to the function

    Returns:
        The result of executing the function

    Raises:
        ValueError: If no 'main' function is found or inputs are invalid
        TypeError: If the function signature doesn't match the provided inputs
        RuntimeError: If execution fails
        SecurityError: If the code hash doesn't match any approved hash
    """
    if not packaged_code or not packaged_code.strip():
        raise ValueError("Packaged code cannot be empty")

    if not isinstance(inputs, dict):
        raise TypeError("Inputs must be a dictionary")

    # Verify the code hash against approved hashes
    code_hash = hashlib.sha256(packaged_code.encode("utf-8")).hexdigest()

    # Read the approved hashes from the validation_functions_hashes.txt file
    hashes_file_path = Path(__file__).parent / "validation_functions_hashes.txt"

    if not hashes_file_path.exists():
        raise FileNotFoundError(f"Validation functions hashes file not found: {hashes_file_path}")

    approved_hashes = set()
    with open(hashes_file_path, "r", encoding="utf-8") as f:
        for line in f:
            hash_value = line.strip()
            if hash_value:  # Skip empty lines
                approved_hashes.add(hash_value)

    if code_hash not in approved_hashes:
        raise ValueError(f"Code hash {code_hash} is not in the approved list. Execution denied for security reasons.")

    # Validate the packaged code syntax before execution
    try:
        ast.parse(packaged_code)
    except SyntaxError as e:
        raise ValueError(f"Invalid Python syntax in packaged code: {e}")

    # Create a restricted namespace for security
    namespace: Dict[str, Any] = {
        "__builtins__": __builtins__,
    }

    try:
        exec(packaged_code, namespace)
    except Exception as e:
        raise RuntimeError(f"Failed to execute packaged code: {e}")

    # Get the execute_packaged function and call it to get the local scope
    if "execute_packaged" not in namespace:
        raise ValueError("Packaged code does not contain 'execute_packaged' function")

    execute_func = namespace["execute_packaged"]
    if not callable(execute_func):
        raise ValueError("'execute_packaged' is not callable")

    try:
        local_scope = execute_func()
    except Exception as e:
        raise RuntimeError(f"Failed to execute wrapper function: {e}")

    if not isinstance(local_scope, dict):
        raise ValueError("execute_packaged did not return a dictionary")

    # Look for the 'main' function
    if "main" not in local_scope:
        raise ValueError("No 'main' function found in packaged code")

    target_func = local_scope["main"]
    if not callable(target_func):
        raise ValueError("'main' is not callable")

    # Validate that the function signature matches the provided inputs
    try:
        sig = inspect.signature(target_func)
        # Check if all required parameters are provided
        bound_args = sig.bind(**inputs)
        bound_args.apply_defaults()
    except TypeError as e:
        raise TypeError(f"Function signature mismatch: {e}")

    # Execute the target function with the provided inputs
    try:
        result = target_func(**inputs)
    except Exception as e:
        raise RuntimeError(f"Function execution failed: {e}")

    return result
