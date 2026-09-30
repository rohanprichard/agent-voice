// The places where agents run, and how to set them up: this computer, and
// servers the user reaches over SSH. Each check and install is one shell
// script, run locally or through one ssh command.

import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { REMOTE_SERVER, ServerLink, explain, sshArgs } from "./link";

export const LOCAL = "local";

// Where `uv tool install` and other installers put commands. An app started
// from the Finder, or a shell over SSH, often has none of them on PATH.
const binDirs = ["~/.local/bin", "/opt/homebrew/bin", "/usr/local/bin"];
const pathPrefix = 'PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"; ';

export type HostPlugin = { host: string; installed: boolean; current: boolean; hooks_trusted?: boolean };

export type Inspection = {
  place: string;
  reachable: boolean;
  error: string;
  uv: string; // the uv path, or ""
  server: string; // the talktome-server version, or ""
  hosts: HostPlugin[];
};

export function localServerBin(): string | null {
  if (process.env.TALKTOME_SERVER_BIN) return process.env.TALKTOME_SERVER_BIN;
  for (const dir of binDirs) {
    const bin = path.join(dir.replace("~", os.homedir()), "talktome-server");
    if (fs.existsSync(bin)) return bin;
  }
  return null;
}

export function linkFor(place: string): ServerLink {
  if (place === LOCAL) {
    return new ServerLink({ id: LOCAL, command: localServerBin() ?? "talktome-server", args: [] });
  }
  return new ServerLink({ id: `ssh:${place}`, command: "ssh", args: sshArgs(place, REMOTE_SERVER) });
}

export function placeOf(linkId: string): string {
  return linkId === LOCAL ? LOCAL : linkId.replace(/^ssh:/, "");
}

type Ran = { code: number | null; out: string; err: string };

function run(command: string, args: string[], timeoutMs: number): Promise<Ran> {
  return new Promise((resolve) => {
    const child = spawn(command, args, { stdio: ["ignore", "pipe", "pipe"] });
    let out = "";
    let err = "";
    child.stdout.on("data", (d) => (out += d));
    child.stderr.on("data", (d) => (err += d));
    const timer = setTimeout(() => child.kill(), timeoutMs);
    child.on("error", (error) => {
      clearTimeout(timer);
      resolve({ code: null, out, err: error.message });
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      resolve({ code, out, err });
    });
  });
}

// sh runs a script in the place: here with /bin/sh, or on the server over ssh.
export function sh(place: string, script: string, timeoutMs = 30_000): Promise<Ran> {
  script = pathPrefix + script;
  if (place === LOCAL) return run("/bin/sh", ["-c", script], timeoutMs);
  return run("ssh", sshArgs(place, script), timeoutMs);
}

export async function inspect(place: string): Promise<Inspection> {
  const result: Inspection = { place, reachable: false, error: "", uv: "", server: "", hosts: [] };
  const ran = await sh(
    place,
    'echo "uv=$(command -v uv)"; echo "server=$(talktome-server version 2>/dev/null)"; echo "hosts=$(talktome-server hosts 2>/dev/null | tr -d \'\\n\')"',
  );
  if (ran.code !== 0) {
    result.error = explain(ran.err.trim(), ran.code);
    return result;
  }
  result.reachable = true;
  for (const line of ran.out.split("\n")) {
    const [key, ...rest] = line.split("=");
    const value = rest.join("=").trim();
    if (key === "uv") result.uv = value;
    if (key === "server") result.server = value;
    if (key === "hosts" && value) {
      try {
        result.hosts = JSON.parse(value);
      } catch {
        result.hosts = [];
      }
    }
  }
  return result;
}

// The official uv installer. The user starts it with a button that shows this command.
export const UV_INSTALL = "curl -LsSf https://astral.sh/uv/install.sh | sh";

export async function installUv(place: string): Promise<string> {
  const ran = await sh(place, UV_INSTALL, 180_000);
  return ran.code === 0 ? "" : explain(ran.err.trim(), ran.code);
}

// serverSource is what uv installs: the package name, a git URL, or a wheel
// file on this computer, which is copied to a server first.
export function serverSource(): string {
  return process.env.TALKTOME_SERVER_SOURCE || "talktome-server";
}

export async function installServer(place: string): Promise<string> {
  let source = serverSource();
  if (fs.existsSync(source) && place !== LOCAL) {
    const remote = `/tmp/${path.basename(source)}`;
    const copied = await run("scp", ["-q", "-o", "BatchMode=yes", source, `${place}:${remote}`], 120_000);
    if (copied.code !== 0) return explain(copied.err.trim(), copied.code);
    source = remote;
  }
  const ran = await sh(place, `uv tool install --force --quiet ${quote(source)}`, 300_000);
  return ran.code === 0 ? "" : ran.err.trim().split("\n").at(-1) || `The install failed (exit ${ran.code}).`;
}

export async function installPlugin(place: string, host: string): Promise<string> {
  const ran = await sh(place, `talktome-server plugin install --host ${quote(host)}`, 120_000);
  if (ran.code === 0) return "";
  return ran.err.trim().replace(/^talktome-server: /, "") || `The install failed (exit ${ran.code}).`;
}

function quote(text: string): string {
  return `'${text.replace(/'/g, "'\\''")}'`;
}

// sshHosts lists the named hosts in ~/.ssh/config, for the "Add a server" field.
export function sshHosts(file = path.join(os.homedir(), ".ssh", "config")): string[] {
  let text = "";
  try {
    text = fs.readFileSync(file, "utf8");
  } catch {
    return [];
  }
  const hosts = new Set<string>();
  for (const line of text.split("\n")) {
    const match = /^\s*Host\s+(.+)$/i.exec(line);
    if (!match) continue;
    for (const name of match[1].split(/\s+/)) {
      if (name && !/[*?!]/.test(name)) hosts.add(name);
    }
  }
  return [...hosts].sort();
}

export type Settings = { servers: string[]; elevenlabs?: string; sealed?: boolean };

export function loadSettings(file: string): Settings {
  try {
    const saved = JSON.parse(fs.readFileSync(file, "utf8")) as Settings;
    return { servers: saved.servers ?? [], elevenlabs: saved.elevenlabs, sealed: saved.sealed };
  } catch {
    return { servers: [] };
  }
}

export function saveSettings(file: string, settings: Settings): void {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(settings, null, 2), { mode: 0o600 });
}

// elevenLabsToken makes a single-use token with the user's own key, the way
// the relay does with its key.
export async function elevenLabsToken(apiKey: string, kind: "realtime_scribe" | "tts_websocket"): Promise<string> {
  const response = await fetch(`https://api.elevenlabs.io/v1/single-use-token/${kind}`, {
    method: "POST",
    headers: { "xi-api-key": apiKey },
  });
  const data = (await response.json().catch(() => ({}))) as { token?: string; detail?: { message?: string } | string };
  if (!response.ok || !data.token) {
    const detail = typeof data.detail === "string" ? data.detail : data.detail?.message;
    throw new Error(response.status === 401 ? "ElevenLabs refused the key. Check it in talktome." : detail || `ElevenLabs failed (${response.status}).`);
  }
  return data.token;
}
