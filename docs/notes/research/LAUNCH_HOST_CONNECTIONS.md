# Launch host connections

Research date: September 28, 2026.

## Launch decision

Use the existing Codex queue connection for Codex. Use cooperative Model Context Protocol (MCP) tools for Hermes and OpenClaw.
The current host agent receives voice input as a tool result. It sends speech through a reply tool.
This design does not require another model session.

The selected new module is `talktome.call_tools`. Its tools are `talktome_call`, `talktome_listen`, `talktome_reply`, and `talktome_end`.
These names describe the implementation contract for this change. They do not describe an upstream host feature.
The existing `talktome.mcp_server` remains a separate interface for older clients.

The reported Hermes failure occurred after skill loading, during terminal command discovery.
Direct MCP tools remove that terminal step. They still require a working MCP process and a reachable TalkToMe app.
This is a design conclusion. No live call established its reliability during this research.

| Method | Existing session | Speech source | Main limit |
| --- | --- | --- | --- |
| Cooperative shell commands | Current agent runs `listen` and `reply` | Explicit reply text | Depends on the terminal executor |
| Cooperative MCP tools | Current agent calls the tools | Explicit reply text | Agent must continue the listen loop |
| Native host plugin tools | Current agent calls registered tools | Explicit reply text | Separate plugin code and installation |
| Session event connection | Host processes input in a selected session | Host output events | Depends on ownership, permissions, and event support |

The current cooperative commands and external adapters appear in [agent support](../../AGENT_SUPPORT.md).
The [external adapter source](../../../src/talktome/external_adapters.py) defines the current Hermes and OpenClaw protocol requirements.

## Shared MCP contract

Use an absolute Python executable that contains the installed TalkToMe package.
The examples use `/ABS/PYTHON` as a placeholder. They do not depend on the shell search path or working directory.
The package requires Python 3.11 through 3.13 and already declares `mcp>=1.12,<2`.
See [package settings](../../../pyproject.toml).

Keep the host session identifier for the full call. Keep the call, turn, item, and event identifiers returned by TalkToMe.
The listen result supplies pending voice input. A progress reply keeps the turn open for further replies.
The adapter rejects old call and turn identifiers. An exact item retry does not repeat speech.
See [cooperative commands](../../AGENT_SUPPORT.md#use-cooperative-commands).

The MCP server must call the same cooperative controller as the command interface.
It must not launch `hermes chat`, another Codex process for inference, or another OpenClaw agent session.
It must not use MCP sampling to request another model response.
Normal host commentary requires an explicit reply call before TalkToMe can speak it.

Use a 60-second tool timeout with a 25-second listen timeout.
These are proposed launch settings, not measured performance limits.
Keep call operations sequential so a reply cannot precede its listen result.

For a local call, the MCP process and TalkToMe app must run on the same Mac.
The host shell must run on the Mac that runs TalkToMe.

## Hermes configuration

Hermes includes MCP support in its standard installation. It discovers configured tools and adds them to its normal tool registry.
The `/reload-mcp` command refreshes the available tools in an existing session.
See [Hermes MCP](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp).

The active file is `$HERMES_HOME/config.yaml`. The default is `~/.hermes/config.yaml`.
Named profiles normally use `~/.hermes/profiles/NAME/config.yaml`.
The `--profile` option and `HERMES_HOME` affect profile selection.
The installer must select the profile that owns the current chat.
See [configuration source](https://github.com/NousResearch/hermes-agent/blob/614b9b3f3c1ea8e24e6c7370bd85f9639f779bf0/hermes_cli/config.py#L436) and [profile source](https://github.com/NousResearch/hermes-agent/blob/614b9b3f3c1ea8e24e6c7370bd85f9639f779bf0/hermes_cli/profiles.py#L2438).

The required YAML fragment is:

```yaml
mcp_servers:
  talktome:
    command: /ABS/PYTHON
    args: ["-m", "talktome.call_tools"]
    enabled: true
    connect_timeout: 10
    timeout: 60
    supports_parallel_tool_calls: false
    sampling:
      enabled: false
    tools:
      include:
        - talktome_call
        - talktome_listen
        - talktome_reply
        - talktome_end
      resources: false
      prompts: false
```

Hermes uses seconds for both timeouts. Tool filters use the original MCP names.
The model sees names such as `mcp__talktome__talktome_call`.
The runtime toolset is `mcp-talktome`.
See [MCP configuration](https://hermes-agent.nousresearch.com/docs/reference/mcp-config-reference) and [tool registration](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp#how-hermes-registers-mcp-tools).

MCP sampling is enabled by default in current Hermes. The fragment disables it for this server.
See [sampling configuration](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp#mcp-sampling-support).

### Scoped command operations

Read only the TalkToMe entry:

```sh
hermes config get mcp_servers.talktome --json
```

Save only the TalkToMe entry:

```sh
hermes config set mcp_servers.talktome '{"command":"/ABS/PYTHON","args":["-m","talktome.call_tools"],"enabled":true,"connect_timeout":10,"timeout":60,"supports_parallel_tool_calls":false,"sampling":{"enabled":false},"tools":{"include":["talktome_call","talktome_listen","talktome_reply","talktome_end"],"resources":false,"prompts":false}}'
```

Remove only the TalkToMe entry:

```sh
hermes config unset mcp_servers.talktome
```

The getter supports `--json` and masks credentials by default. Do not add `--raw`.
The setter parses a JSON object into a mapping. It reads the raw configuration before it changes the selected key.
The unset command removes the selected key. These operations do not require MCP discovery.
See [command parser](https://github.com/NousResearch/hermes-agent/blob/614b9b3f3c1ea8e24e6c7370bd85f9639f779bf0/hermes_cli/subcommands/config.py), [value parser](https://github.com/NousResearch/hermes-agent/blob/614b9b3f3c1ea8e24e6c7370bd85f9639f779bf0/hermes_cli/config.py#L3315), and [configuration writer](https://github.com/NousResearch/hermes-agent/blob/614b9b3f3c1ea8e24e6c7370bd85f9639f779bf0/hermes_cli/config.py#L3546).

The interactive alternative is:

```sh
hermes mcp add talktome --command /ABS/PYTHON --connect-timeout 10 --args -m talktome.call_tools
hermes mcp remove talktome
```

The `--args` option must come last. The add command connects to the server and opens tool selection.
It asks before it replaces an existing server name. The remove command also asks for confirmation.
Thus these commands suit manual installation better than unattended Settings actions.
See [MCP command parser](https://github.com/NousResearch/hermes-agent/blob/614b9b3f3c1ea8e24e6c7370bd85f9639f779bf0/hermes_cli/subcommands/mcp.py#L27) and [MCP installer](https://github.com/NousResearch/hermes-agent/blob/614b9b3f3c1ea8e24e6c7370bd85f9639f779bf0/hermes_cli/mcp_config.py#L644).

## OpenClaw configuration

Current OpenClaw supports direct MCP clients. A TalkToMe plugin is not required for this path.
It supports stdio, Server-Sent Events (SSE), and Streamable HTTP transports.
See [OpenClaw MCP connections](https://docs.openclaw.ai/tools/mcp).

OpenClaw reads JSON5 from `~/.openclaw/openclaw.json` by default.
`OPENCLAW_CONFIG_PATH` selects a different file. Otherwise, `OPENCLAW_STATE_DIR` changes the directory that contains `openclaw.json`.
See [configuration format](https://docs.openclaw.ai/gateway/configuration) and [path source](https://github.com/openclaw/openclaw/blob/dd3fb2bd9cf2aedf1a86eebc388e4f3386b35b98/src/config/paths.ts#L219).

The required JSON5 fragment is:

```json5
{
  mcp: {
    servers: {
      talktome: {
        command: "/ABS/PYTHON",
        args: ["-m", "talktome.call_tools"],
        transport: "stdio",
        enabled: true,
        connectionTimeoutMs: 10000,
        requestTimeoutMs: 60000,
        supportsParallelToolCalls: false,
        toolFilter: {
          include: [
            "talktome_call",
            "talktome_listen",
            "talktome_reply",
            "talktome_end",
          ],
        },
      },
    },
  },
}
```

OpenClaw uses milliseconds in the saved timeout fields. Its command options use seconds.
The normal `coding` and `messaging` profiles expose MCP tools. The `minimal` profile hides them.
A denial for `bundle-mcp` disables MCP tools. Session policy and individual tool denials also apply.
See [MCP registry](https://docs.openclaw.ai/cli/mcp/registry) and [transports](https://docs.openclaw.ai/cli/mcp/transports).

### Scoped command operations

Read only the TalkToMe entry:

```sh
openclaw config get mcp.servers.talktome --json
```

The command returns the selected value with secrets masked.
An absent path returns exit status 1. With `--json`, the error can appear as a JSON object on standard output.
The installer must require exit status 0 before it reads a server object.
See [config getter](https://docs.openclaw.ai/cli/config#config-get).

Save only the TalkToMe entry:

```sh
openclaw mcp set talktome '{"command":"/ABS/PYTHON","args":["-m","talktome.call_tools"],"transport":"stdio","enabled":true,"connectionTimeoutMs":10000,"requestTimeoutMs":60000,"supportsParallelToolCalls":false,"toolFilter":{"include":["talktome_call","talktome_listen","talktome_reply","talktome_end"]}}'
```

Remove only the TalkToMe entry:

```sh
openclaw mcp unset talktome
```

The `set` command accepts one JSON object. It changes one server entry without a connection probe.
The `unset` command removes one server entry.
The `add` command probes by default, but accepts `--no-probe`.
See [MCP registry commands](https://docs.openclaw.ai/cli/mcp/registry) and [command source](https://github.com/openclaw/openclaw/blob/dd3fb2bd9cf2aedf1a86eebc388e4f3386b35b98/src/cli/mcp-cli.ts#L1122).

With Gateway hot reload enabled, the next turn discovers changed server definitions.
`openclaw mcp reload` affects its own process. It does not reload a separate Gateway process.
See [connection reload behavior](https://docs.openclaw.ai/tools/mcp#changes-do-not-reach-an-active-agent).

## Installer limits

Read the selected server entry before a write. Compare its executable and module with the expected TalkToMe values.
If another installation owns that entry, retain it until the user selects a replacement.
An uninstall operation must remove only the entry that this installer owns.
Use the host command interfaces to preserve unrelated settings and secret references.
Do not parse OpenClaw JSON5 with a strict JSON parser and rewrite the whole file.

These are installer requirements from this research. They do not imply that configuration proves a working call.
The host can read a skill while its terminal tool remains unavailable.
Likewise, a saved MCP entry does not prove tool discovery or connection to TalkToMe.

## Native plugin alternatives

Hermes supports Python plugins with `plugin.yaml` and `register(ctx)`.
A plugin can call `ctx.register_tool(name=..., toolset=..., schema=..., handler=...)`.
The model reads the description from `schema["description"]`.
User plugins reside under `$HERMES_HOME/plugins/`. Project plugins require separate enablement.
This path could call the cooperative controller, but adds a Hermes-specific package.
See [Hermes plugins](https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins).

OpenClaw supplies `defineToolPlugin` from `openclaw/plugin-sdk/tool-plugin`.
Its declarative tool handler uses `execute(params, config, context)`.
A factory tool registered with `api.registerTool` uses `execute(toolCallId, params, signal?, onUpdate?)` instead.
See [tool plugin entry](https://docs.openclaw.ai/plugins/sdk-entrypoints/define-tool-plugin) and [plugin tools](https://docs.openclaw.ai/plugins/tool-plugins).

The current example depends on `typebox:^1.1.38` and declares peer dependency `openclaw:>=2026.5.17`.
It ships built JavaScript through `openclaw.extensions` and declares tool names in `openclaw.plugin.json` under `contracts.tools`.
These are the current example requirements, not a minimum version claim for all MCP features.
See [plugin package metadata](https://docs.openclaw.ai/plugins/tool-plugins#package-metadata).

## Session event alternatives

### Codex

TalkToMe already sends `thread/queue/add` through a persistent proxy and reads the existing thread rollout.
This path retains the terminal owner. Speech interruption does not stop terminal work.
See [queue transport](../../../src/talktome/codex_queue.py) and [attachment source](../../../src/talktome/attach.py).

Codex App Server supports thread resume, turn start, turn steering, interruption, and output events.
Those methods support clients that own the host connection.
Resuming stored history alone does not establish attachment to the current desktop owner.
See [official Codex App Server documentation](https://developers.openai.com/codex/app-server/).

### Hermes

The current adapter requires `/v1/capabilities`, `run_submission`, and `run_events_sse`.
It reads `/api/sessions/{id}`, submits `/v1/runs`, then reads `/v1/runs/{run_id}/events`.
It requests stop only when Hermes advertises `run_stop`.
See [TalkToMe adapter](../../../src/talktome/external_adapters.py).

The standard server setup uses `API_SERVER_ENABLED=true`, an `API_SERVER_KEY`, and `hermes gateway`.
The default address is `http://127.0.0.1:8642`.
Current Runs requests can load an existing session transcript. Session leases serialize writers.
See [Hermes API server](https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server).

Current source adds a narrow exception for a canonical Bot Chat with a live Desktop owner.
It sends the input to that owner's mailbox. Other runs create an agent through `_create_agent`.
The mailbox path returns the final receipt output. It does not stream the owner's text or tool events through that function.
Its stop operation cannot stop a turn that the owner already claimed.
See [run admission](https://github.com/NousResearch/hermes-agent/blob/614b9b3f3c1ea8e24e6c7370bd85f9639f779bf0/gateway/platforms/api_server_runs.py#L743) and [owner receipt path](https://github.com/NousResearch/hermes-agent/blob/614b9b3f3c1ea8e24e6c7370bd85f9639f779bf0/gateway/platforms/api_server_runs.py#L864).

Thus the existing Runs adapter cannot promise attachment to every live Hermes desktop or terminal session.
It also cannot infer per-session streaming and stop support from global feature flags.
The older statement that every API session is separate from every terminal session is now too broad.
The mailbox exception needs a separate compatibility check before launch support.

### OpenClaw

The current adapter requires protocol version 4, a session key, a token, and a local `openclaw` executable.
It requests `operator.read` and `operator.write`.
It requires `chat.history`, `chat.send`, `sessions.abort`, and `sessions.messages.subscribe`.
It sends input with `queueMode:"followup"` and reads `agent` events for the returned run identifier.
See [TalkToMe adapter](../../../src/talktome/external_adapters.py).

OpenClaw permits a direct loopback backend client to omit device identity when it uses a shared Gateway token or password.
The exception requires `client.id:"gateway-client"` and `client.mode:"backend"`.
See [Gateway handshake](https://docs.openclaw.ai/gateway/protocol/handshake).

`chat.send` targets the selected session and supports explicit queue modes.
Its acknowledgment separates admission from transcript persistence.
Current assistant events can contain replacements and item boundaries as well as appended text.
TalkToMe currently accumulates appended text in one item. It needs further work before it can promise complete event behavior.
See [session control](https://docs.openclaw.ai/gateway/protocol/rpc-session-control) and [event contract](https://docs.openclaw.ai/gateway/protocol/rpc-bootstrap-and-events).

## Evidence limits

This research examined official documentation and source. It did not install software or change host configuration.
It did not run applications, calls, tests, or builds.
OpenClaw was not installed in the reported launch environment.
The MCP configuration remains subject to the installed host version and its tool policy.

The source references use Hermes commit `614b9b3f3c1ea8e24e6c7370bd85f9639f779bf0` and OpenClaw commit `dd3fb2bd9cf2aedf1a86eebc388e4f3386b35b98`.
These commits identify the examined upstream state. They do not identify a tested release or the installed Hermes desktop build.
