"""
CHAT TERMINAL v1.0 - minimalist live 1-to-1 terminal chat over a Cloudflare tunnel
--------------------------------------------------------------------------
Setup:
    pip install aiohttp prompt_toolkit

Host:    python term_chat_minimal.py      -> [1] Initiate chat
Join:    python term_chat_minimal.py      -> [2] Connect chat (enter code or link)

Options:
    --name Alex        skip the name screen
    --no-tunnel        host on localhost only (join with http://localhost:8080)
"""
import argparse
import asyncio
import html
import json
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

from aiohttp import ClientSession, WSMsgType, web
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style
from prompt_toolkit import print_formatted_text

PORT = int(os.getenv("PORT", "8080"))
if getattr(sys, "frozen", False):
    HERE = os.path.dirname(sys.executable)
else:
    HERE = os.path.dirname(os.path.abspath(__file__))
CF_LOCAL = os.path.join(HERE, "cloudflared.exe")
CF_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"

TITLE = "CHAT TERMINAL v1.0"
RULE = "─" * 38

PEERS = []  # connected websockets (max 2)

STYLE = Style.from_dict({
    "bottom-toolbar": "noreverse #888888",
    "bottom-toolbar.text": "noreverse #888888",
    "dim": "#888888",
})


# ------------------------------------------------------------------ ui helpers
def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def header(clear=True):
    if clear:
        clear_screen()
    print(TITLE)
    print(RULE)


def say(markup):
    print_formatted_text(HTML(markup), style=STYLE)


def note(text):
    say(f"<dim>{html.escape(text)}</dim>")


# ------------------------------------------------------------------ server
async def ws_handler(request):
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    if len(PEERS) >= 2:
        await ws.send_json({"t": "full"})
        await ws.close()
        return ws
    PEERS.append(ws)
    await ws.send_json({"t": "joined", "count": len(PEERS)})
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                for p in list(PEERS):
                    if p is not ws and not p.closed:
                        await p.send_str(msg.data)  # plain relay
    finally:
        if ws in PEERS:
            PEERS.remove(ws)
        for p in PEERS:
            if not p.closed:
                await p.send_json({"t": "left"})
    return ws


async def home(request):
    return web.Response(text="Chat Terminal server is running. Join from a terminal.")


async def start_server():
    app = web.Application()
    app.router.add_get("/", home)
    app.router.add_get("/ws", ws_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", PORT).start()
    return runner


# ------------------------------------------------------------------ tunnel
def find_cloudflared():
    for c in (shutil.which("cloudflared"), CF_LOCAL,
              r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
              r"C:\Program Files\cloudflared\cloudflared.exe"):
        if c and os.path.exists(c):
            return c
    return None


def start_tunnel():
    """Blocking: launches cloudflared, returns (process, public_url) or (None, None)."""
    exe = find_cloudflared()
    if not exe:
        if os.name != "nt":
            print("cloudflared not found. Install: github.com/cloudflare/cloudflared/releases")
            return None, None
        print("Downloading cloudflared (one time, ~20 MB)...")
        try:
            urllib.request.urlretrieve(CF_URL, CF_LOCAL)
            exe = CF_LOCAL
        except Exception as e:
            print("Download failed:", e)
            return None, None
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.Popen([exe, "tunnel", "--url", f"http://localhost:{PORT}"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, creationflags=flags)
    url = None
    for line in proc.stdout:
        m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
        if m:
            url = m.group(0)
            break
    # keep draining output so cloudflared never blocks
    threading.Thread(target=lambda: [None for _ in proc.stdout], daemon=True).start()
    return proc, url


# ------------------------------------------------------------------ client
def to_ws_url(link):
    link = link.strip().rstrip("/")
    if not re.match(r"^[a-z]+://", link):
        link = "https://" + link
    link = re.sub(r"^https://", "wss://", link)
    link = re.sub(r"^http://", "ws://", link)
    return link if link.endswith("/ws") else link + "/ws"


async def chat(ws_url, name):
    session = PromptSession(style=STYLE)
    st = {"peer": None, "typing_until": 0.0, "sent_typing": 0.0, "was_typing": False}

    def toolbar():
        peer = html.escape(st["peer"] or "Other person")
        if time.time() < st["typing_until"]:
            dots = "." * (int(time.time() * 2.5) % 3 + 1)
            return HTML(f" {peer} is typing{dots}")
        if st["peer"]:
            return HTML(f" {peer} connected")
        return HTML(" waiting for the other person...")

    async with ClientSession() as http:
        try:
            ws = await http.ws_connect(ws_url, heartbeat=20)
        except Exception as e:
            print("Could not connect:", e)
            return False

        def send(o):
            if not ws.closed:
                asyncio.ensure_future(ws.send_json(o))

        def on_change(buf):
            now = time.time()
            has_text = bool(buf.text.strip()) and not buf.text.startswith("/")
            if has_text and now - st["sent_typing"] > 1.5:
                st["sent_typing"] = now
                st["was_typing"] = True
                send({"t": "typing", "on": True})
            elif not has_text and st["was_typing"]:
                st["was_typing"] = False
                send({"t": "typing", "on": False})

        session.default_buffer.on_text_changed += on_change

        async def receiver():
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                m = json.loads(msg.data)
                t = m.get("t")
                if t == "joined":
                    send({"t": "hello", "name": name, "reply": False})
                    if m.get("count", 1) == 1:
                        note("Connected. Waiting for the other person...")
                elif t == "full":
                    note("Chat already has 2 people.")
                elif t == "hello":
                    st["peer"] = str(m.get("name", "Friend"))[:30]
                    note(f"-- {st['peer']} joined --")
                    if not m.get("reply"):
                        send({"t": "hello", "name": name, "reply": True})
                elif t == "typing":
                    st["typing_until"] = time.time() + 3 if m.get("on") else 0
                elif t == "msg":
                    st["typing_until"] = 0
                    who = html.escape(st["peer"] or "Them")
                    text = html.escape(str(m.get("text", ""))[:2000])
                    say(f"<b>{who}</b>: {text}")
                elif t == "left":
                    note(f"-- {st['peer'] or 'The other person'} left --")
                    st["peer"] = None
                    st["typing_until"] = 0
            # connection closed
            note("Disconnected.")
            if session.app.is_running:
                session.app.exit(exception=EOFError)

        rx = asyncio.ensure_future(receiver())
        note("Type a message and press Enter. /quit to leave.")
        print()
        try:
            with patch_stdout():
                while not ws.closed:
                    try:
                        text = await session.prompt_async(
                            "> ",
                            bottom_toolbar=toolbar,
                            refresh_interval=0.3,
                        )
                    except (EOFError, KeyboardInterrupt):
                        break
                    text = text.strip()
                    if not text:
                        continue
                    if text == "/quit":
                        break
                    st["was_typing"] = False
                    send({"t": "typing", "on": False})
                    send({"t": "msg", "text": text})
        finally:
            rx.cancel()
            await ws.close()
    return True


def local_ip():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packet is actually sent
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def set_title():
    title = f"Chat Terminal ({local_ip()})"
    if os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW(title)
    else:
        sys.stdout.write(f"\033]0;{title}\007")
        sys.stdout.flush()


SUBSCRIBE_URL = "https://www.youtube.com/channel/UCjklPOypi7jzKsKBUsNLKyA?sub_confirmation=1"


def ensure_numlock():
    """Windows: turn Num Lock on if it is off, so number keys work for the menu."""
    if os.name != "nt":
        return
    try:
        import ctypes
        VK_NUMLOCK = 0x90
        if not (ctypes.windll.user32.GetKeyState(VK_NUMLOCK) & 1):
            ctypes.windll.user32.keybd_event(VK_NUMLOCK, 0x45, 0x1, 0)  # key down
            ctypes.windll.user32.keybd_event(VK_NUMLOCK, 0x45, 0x3, 0)  # key up
    except Exception:
        pass


def show_about():
    header()
    print()
    print("A Cloudflare Tunnel based live terminal chat.")
    print("Developed by Prakash Bera (MH4K YouTube) Team")
    print("using vibe coding.")
    print()
    print("Opening the MH4K YouTube channel - click Subscribe in the popup.")
    try:
        webbrowser.open(SUBSCRIBE_URL)
    except Exception:
        pass
    print(f"If it did not open: {SUBSCRIBE_URL}")
    print()
    print(RULE)


# ------------------------------------------------------------------ chat codes
# A random number is mapped to the tunnel link through a tiny public relay
# (ntfy.sh): the host posts "open <link>" under the code, the joiner reads it.
NTFY = "https://ntfy.sh"
TOPIC_PREFIX = "mh4k-termchat-"
CODE_LEN = 5


def new_code():
    rng = random.SystemRandom()
    return "".join(rng.choice("0123456789") for _ in range(CODE_LEN))


def _ntfy_post(code, text):
    req = urllib.request.Request(f"{NTFY}/{TOPIC_PREFIX}{code}", data=text.encode(),
                                 method="POST", headers={"User-Agent": "term-chat"})
    urllib.request.urlopen(req, timeout=10).read()


def publish_code(code, url):
    _ntfy_post(code, "open " + url)


def close_code(code):
    try:
        _ntfy_post(code, "closed")
    except Exception:
        pass


def lookup_code(code):
    """Blocking: returns the tunnel link for a code, or None."""
    req = urllib.request.Request(f"{NTFY}/{TOPIC_PREFIX}{code}/json?poll=1&since=all",
                                 headers={"User-Agent": "term-chat"})
    with urllib.request.urlopen(req, timeout=10) as r:
        lines = r.read().decode("utf-8", "replace").splitlines()
    last = None
    for ln in lines:
        try:
            ev = json.loads(ln)
        except ValueError:
            continue
        if ev.get("event") == "message":
            last = ev.get("message", "")
    if last and last.startswith("open "):
        return last[5:].strip()
    return None


async def resolve_target(text):
    """Accepts a chat code (digits) or a full link. Returns (ws_url, error)."""
    text = text.strip()
    if text.isdigit():
        loop = asyncio.get_running_loop()
        try:
            url = await loop.run_in_executor(None, lookup_code, text)
        except Exception as e:
            return None, f"Could not reach the code service: {e}"
        if not url:
            return None, "Code not found, or that chat has already closed."
        return to_ws_url(url), None
    return to_ws_url(text), None


async def host_session(name, no_tunnel):
    """Returns a notice string to show on the menu afterwards (or None)."""
    runner = await start_server()
    proc = None
    code = None
    loop = asyncio.get_running_loop()
    header()
    print()
    try:
        ws_url = f"ws://127.0.0.1:{PORT}/ws"
        if no_tunnel:
            print(f"Hosting locally. Join with: http://localhost:{PORT}")
        else:
            print("Starting tunnel...")
            proc, url = await loop.run_in_executor(None, start_tunnel)
            if not url:
                return "Tunnel failed to start."
            code = new_code()
            try:
                await loop.run_in_executor(None, publish_code, code, url)
            except Exception as e:
                code = None
                print(f"(Could not register a chat code: {e})")
            print()
            if code:
                print(f"Chat code: {code}")
                print("Your friend chooses [2] Connect chat and enters it.")
            else:
                print("Send the link below to your friend ([2] Connect chat).")
            print(f"Direct link: {url}")
        print()
        print(RULE)
        print()
        await chat(ws_url, name)
    finally:
        if code:
            await loop.run_in_executor(None, close_code, code)
        if proc:
            proc.terminate()
        await runner.cleanup()
    return None


def ask_name():
    header()
    print()
    print("Enter your name to continue:")
    return (input("> ").strip() or "Anon")[:30]


def show_menu(name, notice):
    header()
    print(f"Logged in as: {name}")
    if notice:
        print(f"\n{notice}")
    print()
    print("[1]  Initiate chat")
    print("[2]  Connect chat")
    print("[3]  About")
    print("[4]  Exit")
    print()
    print(RULE)
    return input("Select [1-4]: ").strip()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("link", nargs="?", help="optional: chat code or link to join directly")
    ap.add_argument("--name")
    ap.add_argument("--no-tunnel", action="store_true")
    args = ap.parse_args()
    set_title()
    ensure_numlock()

    name = args.name[:30] if args.name else ask_name()

    if args.link:
        ws_url, err = await resolve_target(args.link)
        if err:
            print(err)
            return
        await chat(ws_url, name)
        return

    notice = ""
    while True:
        choice = show_menu(name, notice)
        notice = ""
        if choice == "1":
            notice = await host_session(name, args.no_tunnel) or ""
        elif choice == "2":
            header()
            print()
            print("Enter chat code (or paste link):")
            code = input("> ").strip()
            if code:
                ws_url, err = await resolve_target(code)
                if err:
                    notice = err
                else:
                    print()
                    print(RULE)
                    print()
                    if not await chat(ws_url, name):
                        notice = "Could not connect. The host may have closed the chat."
        elif choice == "3":
            show_about()
            input("Press Enter to return...")
        elif choice == "4":
            clear_screen()
            return
        else:
            notice = "Please enter 1, 2, 3 or 4."


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
