import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { explain } from "./link";
import { inspect, LOCAL, sshHosts } from "./servers";

test("named ssh hosts, without patterns", () => {
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "ssh-")), "config");
  fs.writeFileSync(file, "Host home-server\n  HostName 10.0.0.2\nHost *.internal !bad\nhost build box\nMatch all\n");
  assert.deepEqual(sshHosts(file), ["box", "build", "home-server"]);
  assert.deepEqual(sshHosts(file + ".missing"), []);
});

test("ssh failures in words the user can act on", () => {
  assert.match(explain("user@h: Permission denied (publickey,password).", 255), /SSH keys only/);
  assert.match(explain("Host key verification failed.", 255), /accept its key/);
  assert.match(explain("ssh: Could not resolve hostname nope: nodename nor servname provided", 255), /could not find/);
  assert.match(explain("sh: 1: exec: /home/u/.local/bin/talktome-server: not found", 127), /not installed/);
});

test("inspect this computer", async () => {
  const found = await inspect(LOCAL);
  assert.equal(found.reachable, true);
  assert.equal(found.error, "");
});
