"""Print all Claude models available via the Anthropic API."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv

from agent_foundry.primitives import list_claude_models

load_dotenv()


for model in list_claude_models():
    print(model)
