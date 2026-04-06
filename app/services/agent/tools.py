import os
import subprocess
from typing import Dict, Any, Callable

def read_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {str(e)}"

def write_to_file(path: str, content: str) -> str:
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote to {path}"
    except Exception as e:
        return f"Error writing file: {str(e)}"

def run_bash_command(command: str) -> str:
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120  # Limit to 2 minutes
        )
        return f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}\nEXIT CODE: {result.returncode}"
    except subprocess.TimeoutExpired:
        return "Error: Command timed out after 120 seconds."
    except Exception as e:
        return f"Error executing command: {str(e)}"

# The OpenAI JSON Schema for these tools
AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the text contents of a file at a specific absolute path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "The absolute path of the file to read."}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_to_file",
            "description": "Create or overwrite a file with exact string contents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "The absolute path to the file."},
                    "content": {"type": "string", "description": "The complete text content to write."}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_bash_command",
            "description": "Execute a bash shell command and return stdout/stderr. Do NOT run interactive commands.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The bash command to execute."}
                },
                "required": ["command"]
            }
        }
    }
]

# Registry to map tool names from LLM to actual python functions
TOOL_REGISTRY: Dict[str, Callable] = {
    "read_file": read_file,
    "write_to_file": write_to_file,
    "run_bash_command": run_bash_command,
}

def execute_tool(tool_name: str, arguments: Dict[str, Any]) -> str:
    if tool_name not in TOOL_REGISTRY:
        return f"Error: Tool '{tool_name}' not found."
    
    try:
        func = TOOL_REGISTRY[tool_name]
        return func(**arguments)
    except Exception as e:
        return f"Error executing internal tool: {str(e)}"
