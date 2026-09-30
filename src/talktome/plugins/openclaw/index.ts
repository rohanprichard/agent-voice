// TalkToMe voice calls for OpenClaw.
//
// The agent rings the user with the talktome_call tool. After the user answers,
// each spoken turn runs through OpenClaw's embedded agent in the session that
// placed the call, so the call continues that conversation. Replies are spoken
// on the Mac. The model never runs the listen and reply loop itself.

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { TalkToMeClient, TalkToMeError, VoiceCall } from "./talktome.mjs";

const DEFAULT_GREETING = "Hey, what would you like to talk about?";

const VOICE_PROMPT =
  "You are in a live TalkToMe voice call. The user hears each reply as speech, and you " +
  "hear the user as text. Answer in one or two short spoken sentences unless the user " +
  "asks for detail. Do not use markdown, lists, code, file paths, or URLs. Before long " +
  "work, say in a few words what you will do.";

let live: VoiceCall | null = null;
let core: Promise<any> | null = null;

function findPackageRoot(start: string): string | null {
  for (let dir = start; ; dir = path.dirname(dir)) {
    try {
      const pkg = JSON.parse(fs.readFileSync(path.join(dir, "package.json"), "utf8"));
      if (pkg.name === "openclaw") return dir;
    } catch {
      // Keep walking up.
    }
    if (path.dirname(dir) === dir) return null;
  }
}

// extensionAPI.js is the entry point OpenClaw ships for extensions that run the
// embedded agent. The bundled voice-call plugin loads it the same way.
function loadCore(): Promise<any> {
  core ??= (async () => {
    const starts = [process.argv[1] && path.dirname(fs.realpathSync(process.argv[1]))];
    try {
      starts.push(path.dirname(fileURLToPath(import.meta.url)));
    } catch {
      // A loader without file URLs.
    }
    const roots = [process.env.OPENCLAW_ROOT, ...starts.map((start) => start && findPackageRoot(start))];
    for (const root of roots) {
      const api = root && path.join(root, "dist", "extensionAPI.js");
      if (api && fs.existsSync(api)) return import(pathToFileURL(api).href);
    }
    throw new Error("Could not find OpenClaw's extension API. Set OPENCLAW_ROOT.");
  })();
  return core;
}

function modelFor(config: any, agentId: string, deps: any) {
  const agent = (config.agents?.list ?? []).find((entry: any) => entry.id === agentId);
  const pick = (model: any) => (typeof model === "string" ? model : model?.primary);
  const ref =
    pick(agent?.model) ||
    pick(config.agents?.defaults?.model) ||
    `${deps.DEFAULT_PROVIDER}/${deps.DEFAULT_MODEL}`;
  const slash = ref.indexOf("/");
  return slash < 0
    ? { provider: deps.DEFAULT_PROVIDER, model: ref }
    : { provider: ref.slice(0, slash), model: ref.slice(slash + 1) };
}

function agentRunner(api: any, ctx: any) {
  return async (prompt: string, options: any) => {
    const deps = await loadCore();
    const config = ctx.config ?? api.config;
    const agentId = ctx.agentId || "main";
    const storePath = deps.resolveStorePath(config.session?.store, { agentId });
    const entry = deps.loadSessionStore(storePath)[ctx.sessionKey];
    if (!entry?.sessionId) throw new Error(`The calling session ${ctx.sessionKey} was not found.`);
    const { provider, model } = modelFor(config, agentId, deps);
    const result = await deps.runEmbeddedPiAgent({
      sessionId: entry.sessionId,
      sessionKey: ctx.sessionKey,
      messageProvider: "talktome",
      sessionFile: deps.resolveSessionFilePath(entry.sessionId, entry, { agentId }),
      workspaceDir: ctx.workspaceDir ?? deps.resolveAgentWorkspaceDir(config, agentId),
      agentDir: ctx.agentDir ?? deps.resolveAgentDir(config, agentId),
      config,
      prompt,
      provider,
      model,
      thinkLevel: deps.resolveThinkingDefault({ cfg: config, provider, model }),
      verboseLevel: "off",
      timeoutMs: deps.resolveAgentTimeoutMs({ cfg: config }),
      runId: `talktome:${options.turnId}:${crypto.randomUUID().slice(0, 8)}`,
      extraSystemPrompt: VOICE_PROMPT,
      abortSignal: options.abortSignal,
      onBlockReply: options.onBlockReply,
    });
    const payloads = result?.payloads ?? [];
    return {
      texts: payloads.map((payload: any) => payload?.text).filter(Boolean),
      failed: payloads.some((payload: any) => payload?.isError),
    };
  };
}

const result = (details: unknown) => ({
  content: [{ type: "text" as const, text: JSON.stringify(details) }],
  details,
});

export default {
  id: "talktome",
  name: "TalkToMe",
  description: "Voice calls with OpenClaw through the TalkToMe desktop app.",
  register(api: any) {
    const settings = api.pluginConfig ?? {};
    const log = (message: string) => api.logger.info(`[talktome] ${message}`);

    api.registerTool(
      (ctx: any) => [
        {
          name: "talktome_call",
          label: "TalkToMe call",
          description:
            "Ring the user for a live TalkToMe voice call on their Mac. Use it when the user " +
            "says call me, ring me, or talk to me. This is a desktop voice call, not a phone " +
            "call, so do not use a phone or telephony tool. After the user answers, the call " +
            "continues this conversation by voice. Returns whether they answered.",
          parameters: {
            type: "object",
            properties: {
              greeting: {
                type: "string",
                description: "The first sentence the user hears. Write it as speech.",
              },
              name: {
                type: "string",
                description: "A short title that shows while the call rings.",
              },
            },
            additionalProperties: false,
          },
          async execute(_toolCallId: string, params: any) {
            if (live && !live.closed) {
              return result({ answered: false, error: "A TalkToMe call is already live." });
            }
            if (!ctx.sessionKey) {
              return result({ answered: false, error: "This run has no session to continue." });
            }
            try {
              const client = await TalkToMeClient.discover(settings);
              const thread = `openclaw-${crypto.randomUUID().replaceAll("-", "").slice(0, 16)}`;
              const greeting = String(params?.greeting || "").trim() || DEFAULT_GREETING;
              const name = String(params?.name || "").trim() || null;
              const answer = await client.call(thread, greeting, name);
              if (!answer.answered) {
                return result({ answered: false, status: answer.status || "not answered" });
              }
              const call = new VoiceCall({ thread, client, runAgent: agentRunner(api, ctx), log });
              live = call.start();
              call.listening.finally(() => {
                log(`Call ${thread} ended.`);
                if (live === call) live = null;
              });
              return result({ answered: true, call: thread, remote: client.remote });
            } catch (error) {
              const message = error instanceof TalkToMeError ? error.message : String(error);
              return result({ answered: false, error: message });
            }
          },
        },
        {
          name: "talktome_end",
          label: "End TalkToMe call",
          description: "End the live TalkToMe voice call, or stop a ring.",
          parameters: { type: "object", properties: {}, additionalProperties: false },
          async execute() {
            try {
              const call = live;
              live = null;
              const ended = call ? await call.end() : await (await TalkToMeClient.discover(settings)).end();
              return result(ended);
            } catch (error) {
              return result({ ended: false, error: String((error as Error)?.message ?? error) });
            }
          },
        },
      ],
      { names: ["talktome_call", "talktome_end"] },
    );

    api.registerService({
      id: "talktome",
      start() {},
      stop() {
        live?.close();
        live = null;
      },
    });
  },
};
