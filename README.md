# Term Chat Minimal

A minimal terminal-based chat application.

## Prerequisites

- Windows (for `winget`) or macOS/Linux (for `brew`)
- Internet connection

## Installation

### 1. Install Python

**Windows:**
```bash
winget install Python.Python.3

**# Mac OS/ Lunix**

# Python is usually pre-installed. If not:
# macOS
brew install python

# Ubuntu/Debian
sudo apt update && sudo apt install python3 python3-pip

**2. Install Cloudflared**
brew install cloudflared

Note: On Windows, download Cloudflared from the official GitHub releases or install via winget if available.

**3. Install Python Dependencies**

python.exe -m pip install aiohttp prompt_toolkit


4. Run the Application

python.exe .\term_chat_minimal.py


**Quick Start (All Commands)**

# Install Python (Windows)
winget install Python.Python.3

# Install cloudflared
brew install cloudflared

# Install dependencies
python.exe -m pip install aiohttp prompt_toolkit

# Run
python.exe .\chat-terminal.py

**Requirements**
Python 3.x
aiohttp
prompt_toolkit
cloudflared
