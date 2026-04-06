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

def search_files(pattern: str, root_dir: str = ".") -> str:
    try:
        cmd = f"grep -rnI '{pattern}' {root_dir} | head -n 100"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return result.stdout if result.stdout else "No matches found."
    except Exception as e:
        return f"Error searching files: {str(e)}"

def list_project_structure(root_dir: str = ".") -> str:
    try:
        cmd = f"find {root_dir} -maxdepth 3 -not -path '*/\\.*' | head -n 100"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return result.stdout if result.stdout else "Empty or could not read."
    except Exception as e:
        return f"Error listing structure: {str(e)}"

def replace_file_lines(path: str, start_line: int, end_line: int, replacement_content: str) -> str:
    try:
        if not os.path.exists(path):
            return f"Error: File '{path}' does not exist."
            
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        if start_line < 1 or start_line > len(lines):
            return f"Error: start_line {start_line} is out of bounds."
            
        if end_line < start_line:
            return f"Error: end_line cannot be before start_line."
            
        prefix = lines[:start_line - 1]
        suffix = lines[end_line:] if end_line <= len(lines) else []
        
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(prefix)
            if replacement_content:
                f.write(replacement_content)
                if not replacement_content.endswith("\n"):
                    f.write("\n")
            f.writelines(suffix)
            
        return f"Successfully replaced lines {start_line} to {end_line} in {path}."
    except Exception as e:
        return f"Error replacing lines: {str(e)}"

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
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Globally string search project files (like grep).",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "The search term or regex."},
                    "root_dir": {"type": "string", "description": "The root directory to search. Default is '.'"}
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_project_structure",
            "description": "List all files up to 3 folders deep for discovery.",
            "parameters": {
                "type": "object",
                "properties": {
                    "root_dir": {"type": "string", "description": "The root directory to tree map. Default is '.'"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "replace_file_lines",
            "description": "Surgically replace specific lines of code inside a file. Lines are 1-indexed. The start_line is the first line to replace, and end_line is the exact last line to replace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path to the file."},
                    "start_line": {"type": "integer", "description": "1-indexed starting line number of the block to replace."},
                    "end_line": {"type": "integer", "description": "1-indexed ending line number (inclusive) to replace."},
                    "replacement_content": {"type": "string", "description": "The exact string content to insert perfectly over the replacing lines."}
                },
                "required": ["path", "start_line", "end_line", "replacement_content"]
            }
        }
    }
]

# Registry to map tool names from LLM to actual python functions
TOOL_REGISTRY: Dict[str, Callable] = {
    "read_file": read_file,
    "write_to_file": write_to_file,
    "run_bash_command": run_bash_command,
    "search_files": search_files,
    "list_project_structure": list_project_structure,
    "replace_file_lines": replace_file_lines,
}

def execute_tool(tool_name: str, arguments: Dict[str, Any]) -> str:
    if tool_name not in TOOL_REGISTRY:
        return f"Error: Tool '{tool_name}' not found."
    
    try:
        func = TOOL_REGISTRY[tool_name]
        return func(**arguments)
    except Exception as e:
        return f"Error executing internal tool: {str(e)}"
