'use strict';

const fs = require('fs/promises');
const path = require('path');
const { useMultiFileAuthState } = require('@whiskeysockets/baileys');
const { assertValidInstanceId } = require('../errors');

/**
 * Session persistence abstraction (MVP: local filesystem).
 *
 * The rest of the codebase only depends on this interface:
 *   - load(instanceId)   -> { state, saveCreds }
 *   - clear(instanceId)  -> void
 *   - listIds()          -> string[]
 *
 * To move to PostgreSQL/Redis later, reimplement these three methods
 * using Baileys' auth-state keys (see useMultiFileAuthState source as
 * the reference implementation). No other file needs to change.
 *
 * Small per-instance JSON sidecars (e.g. webhook.json) go through
 * writeMeta/readMeta, so all filesystem knowledge stays here.
 */
class SessionStore {
  constructor(baseDir) {
    this.baseDir = baseDir;
  }

  dirFor(instanceId) {
    assertValidInstanceId(instanceId);
    return path.join(this.baseDir, instanceId);
  }

  async load(instanceId) {
    return useMultiFileAuthState(this.dirFor(instanceId));
  }

  async clear(instanceId) {
    await fs.rm(this.dirFor(instanceId), { recursive: true, force: true });
  }

  async exists(instanceId) {
    try {
      const stat = await fs.stat(this.dirFor(instanceId));
      return stat.isDirectory();
    } catch {
      return false;
    }
  }

  /** Instance ids that have persisted auth state on disk. */
  async listIds() {
    try {
      const entries = await fs.readdir(this.baseDir, { withFileTypes: true });
      return entries.filter((e) => e.isDirectory()).map((e) => e.name);
    } catch {
      return [];
    }
  }

  /** Write a small JSON sidecar (e.g. webhook.json) for an instance. */
  async writeMeta(instanceId, name, obj) {
    const dir = this.dirFor(instanceId);
    await fs.mkdir(dir, { recursive: true });
    await fs.writeFile(path.join(dir, name), JSON.stringify(obj), 'utf8');
  }

  /** Read a JSON sidecar; returns null when absent or invalid. */
  async readMeta(instanceId, name) {
    try {
      const raw = await fs.readFile(path.join(this.dirFor(instanceId), name), 'utf8');
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }
}

module.exports = { SessionStore };
