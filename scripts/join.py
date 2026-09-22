#!/usr/bin/env python3
"""
join-call: Join video meetings with voice and screenshare.

This is a thin wrapper around AgentCall's bridge.py that provides
sensible defaults for the join-call skill.

Usage:
    python scripts/join.py "https://meet.google.com/abc" --name "Agent"
    python scripts/join.py "https://zoom.us/j/123" --mode webpage-av-screenshare
    python scripts/join.py "https://teams.microsoft.com/..." --output events.jsonl

Requirements:
    pip install aiohttp websockets

AgentCall API key must be configured at ~/.agentcall/config.json or
via AGENTCALL_API_KEY environment variable.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

try:
    import aiohttp
    import websockets
except ImportError:
    print("Error: Missing dependencies. Run: pip install aiohttp websockets", file=sys.stderr)
    sys.exit(1)


API_URL = os.environ.get("AGENTCALL_API_URL", "https://api.agentcall.dev")
CONFIG_PATH = Path.home() / ".agentcall" / "config.json"


def get_api_key() -> str:
    """Get API key from environment or config file."""
    if key := os.environ.get("AGENTCALL_API_KEY"):
        return key
    
    if CONFIG_PATH.exists():
        try:
            config = json.loads(CONFIG_PATH.read_text())
            if key := config.get("api_key"):
                return key
        except (json.JSONDecodeError, OSError):
            pass
    
    print("Error: No AgentCall API key found.", file=sys.stderr)
    print(f"Set AGENTCALL_API_KEY or save key to {CONFIG_PATH}", file=sys.stderr)
    print("Get a free key at https://agentcall.dev", file=sys.stderr)
    sys.exit(1)


def get_config() -> dict:
    """Load user config with defaults."""
    defaults = {
        "default_mode": "audio",
        "default_voice": "af_heart",
        "default_bot_name": "Agent",
    }
    
    if CONFIG_PATH.exists():
        try:
            config = json.loads(CONFIG_PATH.read_text())
            defaults.update({k: v for k, v in config.items() if k != "api_key"})
        except (json.JSONDecodeError, OSError):
            pass
    
    return defaults


class MeetingBridge:
    """Bridge between the agent and AgentCall meeting infrastructure."""
    
    def __init__(self, meeting_url: str, args: argparse.Namespace):
        self.meeting_url = meeting_url
        self.args = args
        self.api_key = get_api_key()
        self.config = get_config()
        self.call_id = None
        self.ws = None
        self.output_file = None
        self.vad_buffer = []
        self.vad_timeout = args.vad_timeout
        self.last_speaker = None
        
    async def create_call(self) -> dict:
        """Create a new call via AgentCall API."""
        mode = self.args.mode or self.config.get("default_mode", "audio")
        bot_name = self.args.name or self.config.get("default_bot_name", "Agent")
        
        payload = {
            "meeting_url": self.meeting_url,
            "bot_name": bot_name,
            "mode": mode,
            "transcription": True,
        }
        
        if mode.startswith("webpage"):
            payload["voice_strategy"] = "direct"
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{API_URL}/v1/calls",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"}
            ) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    raise RuntimeError(f"Failed to create call: {resp.status} {error}")
                return await resp.json()
    
    async def connect_websocket(self, ws_url: str):
        """Connect to the call's WebSocket."""
        self.ws = await websockets.connect(ws_url)
    
    def emit_event(self, event: dict):
        """Emit an event to stdout and optionally to file."""
        line = json.dumps(event)
        print(line, flush=True)
        
        if self.output_file:
            self.output_file.write(line + "\n")
            self.output_file.flush()
    
    async def process_transcript(self, event: dict):
        """Coalesce transcript events with VAD buffering."""
        text = event.get("text", "")
        speaker = event.get("speaker", {})
        speaker_name = speaker.get("name", "Unknown")
        
        self.vad_buffer.append(text)
        self.last_speaker = speaker_name
    
    async def flush_vad_buffer(self):
        """Flush buffered transcript as user.message."""
        if self.vad_buffer:
            full_text = " ".join(self.vad_buffer).strip()
            if full_text:
                self.emit_event({
                    "event": "user.message",
                    "speaker": self.last_speaker,
                    "text": full_text
                })
            self.vad_buffer = []
    
    async def handle_event(self, raw_event: dict):
        """Process a raw event from AgentCall."""
        event_type = raw_event.get("event") or raw_event.get("type")
        
        if event_type == "transcript.final":
            await self.process_transcript(raw_event)
            return
        
        if event_type == "call.bot_ready":
            self.emit_event({"event": "call.bot_ready", "call_id": self.call_id})
            return
        
        if event_type == "call.ended":
            reason = raw_event.get("reason", "unknown")
            self.emit_event({"event": "call.ended", "reason": reason})
            return
        
        if event_type == "participant.joined":
            participant = raw_event.get("participant", {})
            name = participant.get("name", "Unknown")
            self.emit_event({"event": "participant.joined", "name": name})
            
            if not hasattr(self, "_greeted"):
                self._greeted = True
                self.emit_event({
                    "event": "greeting.prompt",
                    "participant": name,
                    "hint": f"{name} joined. Introduce yourself and greet them via tts.speak."
                })
            return
        
        if event_type == "participant.left":
            participant = raw_event.get("participant", {})
            name = participant.get("name", "Unknown")
            self.emit_event({"event": "participant.left", "name": name})
            return
        
        if event_type == "chat.message":
            self.emit_event({
                "event": "chat.received",
                "sender": raw_event.get("sender", "Unknown"),
                "message": raw_event.get("message", "")
            })
            return
        
        if event_type in ("tts.done", "tts.started"):
            self.emit_event({"event": event_type})
            return
        
        if event_type == "tts.error":
            self.emit_event({"event": "tts.error", "reason": raw_event.get("reason", "unknown")})
            return
        
        if event_type == "tts.interrupted":
            self.emit_event({
                "event": "tts.interrupted",
                "played": raw_event.get("played", []),
                "not_played": raw_event.get("not_played", [])
            })
            return
        
        if event_type == "screenshot.result":
            self.emit_event({
                "event": "screenshot.result",
                "data": raw_event.get("data"),
                "width": raw_event.get("width"),
                "height": raw_event.get("height"),
                "request_id": raw_event.get("request_id", "screenshot")
            })
            return
        
        if event_type in ("screenshare.started", "screenshare.stopped", "screenshare.error"):
            self.emit_event(raw_event)
            return
    
    async def send_command(self, command: dict):
        """Send a command to AgentCall via WebSocket."""
        if self.ws:
            cmd = command.get("command") or command.get("type")
            
            ws_command = {"type": cmd}
            for key in ("text", "voice", "speed", "message", "action", 
                        "url", "port", "request_id", "state"):
                if key in command:
                    ws_command[key] = command[key]
            
            if cmd == "tts.speak":
                ws_command["type"] = "tts.speak"
                ws_command.setdefault("voice", self.args.voice or self.config.get("default_voice", "af_heart"))
            
            if cmd == "send_chat":
                ws_command["type"] = "meeting.send_chat"
            
            if cmd == "leave":
                ws_command["type"] = "meeting.leave"
            
            if cmd == "screenshot":
                ws_command["type"] = "screenshot.take"
                ws_command.setdefault("request_id", "screenshot")
            
            await self.ws.send(json.dumps(ws_command))
    
    async def read_stdin(self):
        """Read commands from stdin."""
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        
        while True:
            try:
                line = await reader.readline()
                if not line:
                    break
                
                command = json.loads(line.decode().strip())
                await self.send_command(command)
            except json.JSONDecodeError:
                continue
            except Exception:
                break
    
    async def read_websocket(self):
        """Read events from WebSocket."""
        vad_task = None
        
        async def vad_timer():
            await asyncio.sleep(self.vad_timeout)
            await self.flush_vad_buffer()
        
        while True:
            try:
                msg = await self.ws.recv()
                event = json.loads(msg)
                
                if vad_task:
                    vad_task.cancel()
                    try:
                        await vad_task
                    except asyncio.CancelledError:
                        pass
                
                await self.handle_event(event)
                
                event_type = event.get("event") or event.get("type")
                if event_type == "transcript.final":
                    vad_task = asyncio.create_task(vad_timer())
                
                if event_type == "call.ended":
                    break
                    
            except websockets.ConnectionClosed:
                self.emit_event({"event": "call.ended", "reason": "connection_closed"})
                break
            except Exception as e:
                self.emit_event({"event": "error", "message": str(e)})
                break
    
    async def run(self):
        """Main run loop."""
        if self.args.output:
            self.output_file = open(self.args.output, "a")
        
        try:
            call_data = await self.create_call()
            self.call_id = call_data["call_id"]
            ws_url = call_data["ws_url"]
            
            self.emit_event({
                "event": "call.created",
                "call_id": self.call_id,
                "status": call_data.get("status", "bot_joining")
            })
            
            await self.connect_websocket(ws_url)
            
            stdin_task = asyncio.create_task(self.read_stdin())
            ws_task = asyncio.create_task(self.read_websocket())
            
            done, pending = await asyncio.wait(
                [stdin_task, ws_task],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                    
        except Exception as e:
            self.emit_event({"event": "error", "message": str(e)})
            sys.exit(1)
        finally:
            if self.output_file:
                self.output_file.close()
            if self.ws:
                await self.ws.close()


def main():
    parser = argparse.ArgumentParser(
        description="Join a video meeting with voice and screenshare",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/join.py "https://meet.google.com/abc-def-ghi"
    python scripts/join.py "https://zoom.us/j/123" --name "Claude"
    python scripts/join.py "https://teams.microsoft.com/..." --mode webpage-av-screenshare
    
Get a free AgentCall API key at https://agentcall.dev
        """
    )
    
    parser.add_argument("meeting_url", help="Meeting URL (Google Meet, Zoom, or Teams)")
    parser.add_argument("--name", help="Bot name in participant list")
    parser.add_argument("--mode", choices=["audio", "webpage-av", "webpage-av-screenshare"],
                        help="Call mode (default: audio)")
    parser.add_argument("--voice", help="TTS voice (default: af_heart)")
    parser.add_argument("--output", "-o", help="Write events to file (in addition to stdout)")
    parser.add_argument("--vad-timeout", type=float, default=1.25,
                        help="VAD coalescing timeout in seconds (default: 1.25)")
    
    args = parser.parse_args()
    
    bridge = MeetingBridge(args.meeting_url, args)
    asyncio.run(bridge.run())


if __name__ == "__main__":
    main()
