def run(name: str):
    return f"Hello, {name}! This is a local Apsara tool plugin."

METADATA = {
    "description": "A simple test tool to verify local plugin loading.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "The name to greet."}
        },
        "required": ["name"]
    }
}
