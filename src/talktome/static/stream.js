// The live state from /v1/stream. The server sends one snapshot, then small
// events. A reply delta carries only its new text, so this file keeps the
// transcript the same way the room does.

// The room keeps this many messages.
const MAX_MESSAGES = 200;

function findMessage(messages, itemId) {
  for (let index = messages.length - 1; index >= 0; index--) {
    if (messages[index].item_id === itemId) return messages[index];
  }
  return null;
}

function agentMessage(messages, event) {
  let message = findMessage(messages, event.item_id);
  if (!message) {
    message = {
      role: "agent",
      name: event.name || "Agent",
      text: "",
      item_id: event.item_id,
      turn_id: event.turn_id,
      call_id: event.call_id,
      kind: event.kind || "message",
    };
    messages.push(message);
  }
  return message;
}

/** Apply one room event to a copy of the room. Returns true if the messages changed. */
export function applyEvent(room, event) {
  const messages = (room.messages ||= []);
  if (event.type === "call.started") {
    messages.length = 0;
    return true;
  }
  if (event.type === "user.utterance") {
    messages.push({
      role: "user",
      text: event.text,
      turn_id: event.turn_id,
      call_id: event.call_id,
    });
  } else if (event.type === "agent.greeting" && event.item_id) {
    agentMessage(messages, event).text = event.text;
  } else if (event.type === "message.delta") {
    const message = agentMessage(messages, event);
    message.text += event.text || "";
    message.kind = event.kind || message.kind;
  } else if (event.type === "message.done") {
    const message = agentMessage(messages, event);
    if (typeof event.text === "string") message.text = event.text;
    message.kind = event.kind || message.kind;
  } else {
    return false;
  }
  if (messages.length > MAX_MESSAGES) messages.splice(0, messages.length - MAX_MESSAGES);
  return true;
}

/**
 * Follow /v1/stream. The browser opens the stream again after it ends, and
 * sends the last event id, so a short gap costs nothing. A stream the browser
 * gave up on, for example after a 401, is opened again after a pause.
 */
export function followStream({ onSnapshot, onEvent, onSpeech, onLost, onOpen }) {
  let source = null;
  let timer = null;
  let stopped = false;

  function open() {
    if (stopped) return;
    source = new EventSource("/v1/stream");
    source.addEventListener("open", () => onOpen?.());
    source.addEventListener("snapshot", (message) => onSnapshot(JSON.parse(message.data)));
    source.addEventListener("event", (message) => onEvent(JSON.parse(message.data)));
    source.addEventListener("speech", (message) => onSpeech?.(JSON.parse(message.data)));
    source.addEventListener("error", () => {
      if (source.readyState !== EventSource.CLOSED) return;
      onLost?.();
      clearTimeout(timer);
      timer = setTimeout(open, 2000);
    });
  }

  open();
  return () => {
    stopped = true;
    clearTimeout(timer);
    source?.close();
  };
}
