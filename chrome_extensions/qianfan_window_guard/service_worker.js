const STORAGE_KEY = "ownedWindows";
const DEFAULT_DELAY_MS = 60000;
const ALARM_PREFIX = "close-owned-window:";

function normalizeTaskId(value) {
  const taskId = String(value || "").trim();
  return taskId || "";
}

async function loadOwnedWindows() {
  const payload = await chrome.storage.local.get(STORAGE_KEY);
  const items = Array.isArray(payload[STORAGE_KEY]) ? payload[STORAGE_KEY] : [];
  return items.filter((item) => item && Number.isInteger(item.windowId));
}

async function saveOwnedWindows(items) {
  await chrome.storage.local.set({ [STORAGE_KEY]: items });
}

async function pruneOwnedWindows() {
  const items = await loadOwnedWindows();
  const kept = [];
  for (const item of items) {
    try {
      const currentWindow = await chrome.windows.get(item.windowId, { populate: true });
      const activeTab = Array.isArray(currentWindow.tabs)
        ? currentWindow.tabs.find((tab) => tab.active) || currentWindow.tabs[0] || null
        : null;
      kept.push({
        ...item,
        activeTabId: activeTab?.id || item.activeTabId || null,
        url: activeTab?.url || item.url || "",
        title: activeTab?.title || item.title || ""
      });
    } catch (_error) {
      // Window no longer exists; drop it.
    }
  }
  await saveOwnedWindows(kept);
  return kept;
}

async function registerOwnedWindow(windowInfo, metadata = {}) {
  const items = await pruneOwnedWindows();
  const next = items.filter((item) => item.windowId !== windowInfo.id);
  const activeTab = Array.isArray(windowInfo.tabs)
    ? windowInfo.tabs.find((tab) => tab.active) || windowInfo.tabs[0] || null
    : null;
  next.push({
    windowId: windowInfo.id,
    activeTabId: activeTab?.id || null,
    url: activeTab?.url || "",
    title: activeTab?.title || "",
    createdAt: new Date().toISOString(),
    ...metadata
  });
  await saveOwnedWindows(next);
  return next;
}

async function forgetOwnedWindow(windowId) {
  const items = await loadOwnedWindows();
  const next = items.filter((item) => item.windowId !== windowId);
  await saveOwnedWindows(next);
  return next;
}

async function closeOwnedWindow(windowId) {
  await chrome.windows.remove(windowId);
  await forgetOwnedWindow(windowId);
}

async function closeOwnedWindowIfTracked(windowId) {
  const items = await loadOwnedWindows();
  if (!items.some((item) => item.windowId === windowId)) {
    return { closed: false, reason: "window_not_tracked" };
  }
  await closeOwnedWindow(windowId);
  return { closed: true, reason: "closed" };
}

async function closeExpiredOwnedWindows(now = Date.now()) {
  const items = await pruneOwnedWindows();
  const dueItems = items.filter((item) => Number.isFinite(item.closeAt) && item.closeAt <= now);
  const results = [];
  for (const item of dueItems) {
    try {
      await closeOwnedWindow(item.windowId);
      results.push({ windowId: item.windowId, closed: true });
    } catch (_error) {
      results.push({ windowId: item.windowId, closed: false });
    }
  }
  return results;
}

async function listTaskOwnedWindows(taskId) {
  const normalizedTaskId = normalizeTaskId(taskId);
  if (!normalizedTaskId) {
    return [];
  }
  const items = await pruneOwnedWindows();
  return items.filter((item) => normalizeTaskId(item.taskId) === normalizedTaskId);
}

async function closeTaskOwnedWindows(taskId) {
  const matched = await listTaskOwnedWindows(taskId);
  const closed = [];
  const remaining = [];
  for (const item of matched) {
    try {
      await closeOwnedWindow(item.windowId);
      closed.push(item);
    } catch (_error) {
      remaining.push(item);
    }
  }
  return {
    taskId: normalizeTaskId(taskId),
    matched,
    closed,
    remaining
  };
}

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (!alarm.name.startsWith(ALARM_PREFIX)) {
    return;
  }
  const rawWindowId = alarm.name.slice(ALARM_PREFIX.length);
  const windowId = Number.parseInt(rawWindowId, 10);
  if (!Number.isInteger(windowId) || windowId <= 0) {
    return;
  }
  try {
    await closeOwnedWindowIfTracked(windowId);
  } catch (_error) {
    await pruneOwnedWindows();
  }
});

chrome.windows.onRemoved.addListener(async (windowId) => {
  const items = await loadOwnedWindows();
  if (!items.some((item) => item.windowId === windowId)) {
    return;
  }
  await forgetOwnedWindow(windowId);
});

chrome.runtime.onInstalled.addListener(async () => {
  await chrome.runtime.openOptionsPage();
});

chrome.runtime.onStartup.addListener(async () => {
  await closeExpiredOwnedWindows();
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  (async () => {
    if (!message || typeof message !== "object") {
      throw new Error("Invalid message payload");
    }
    if (message.type === "guard:list") {
      await closeExpiredOwnedWindows();
      const items = await pruneOwnedWindows();
      sendResponse({ ok: true, items });
      return;
    }
    if (message.type === "guard:open-window") {
      const url = String(message.url || "").trim();
      if (!url) {
        throw new Error("URL is required");
      }
      const createdWindow = await chrome.windows.create({
        url,
        focused: true,
        type: "normal"
      });
      const taskId = normalizeTaskId(message.taskId);
      await registerOwnedWindow(createdWindow, {
        source: "guard_open_window",
        ...(taskId ? { taskId } : {})
      });
      const activeTab = Array.isArray(createdWindow.tabs)
        ? createdWindow.tabs.find((tab) => tab.active) || createdWindow.tabs[0] || null
        : null;
      sendResponse({
        ok: true,
        opened: {
          windowId: createdWindow.id,
          tabId: activeTab?.id || null,
          url: activeTab?.url || url,
          title: activeTab?.title || ""
        }
      });
      return;
    }
    if (message.type === "guard:open-window-and-auto-close") {
      const url = String(message.url || "").trim();
      if (!url) {
        throw new Error("URL is required");
      }
      const autoCloseMs = Number.isFinite(message.autoCloseMs)
        ? Number(message.autoCloseMs)
        : DEFAULT_DELAY_MS;
      const closeAt = Date.now() + Math.max(0, autoCloseMs);
      const createdWindow = await chrome.windows.create({
        url,
        focused: true,
        type: "normal"
      });
      const taskId = normalizeTaskId(message.taskId);
      await registerOwnedWindow(createdWindow, {
        source: "guard_open_window_and_auto_close",
        closeAt,
        ...(taskId ? { taskId } : {})
      });
      chrome.alarms.create(`${ALARM_PREFIX}${createdWindow.id}`, {
        when: closeAt
      });
      const activeTab = Array.isArray(createdWindow.tabs)
        ? createdWindow.tabs.find((tab) => tab.active) || createdWindow.tabs[0] || null
        : null;
      sendResponse({
        ok: true,
        opened: {
          windowId: createdWindow.id,
          tabId: activeTab?.id || null,
          url: activeTab?.url || url,
          title: activeTab?.title || ""
        },
        autoCloseMs,
        closeAt
      });
      return;
    }
    if (message.type === "guard:list-task-windows") {
      const taskId = normalizeTaskId(message.taskId);
      if (!taskId) {
        throw new Error("taskId is required");
      }
      const items = await listTaskOwnedWindows(taskId);
      sendResponse({ ok: true, taskId, items });
      return;
    }
    if (message.type === "guard:close-task-windows") {
      const taskId = normalizeTaskId(message.taskId);
      if (!taskId) {
        throw new Error("taskId is required");
      }
      const result = await closeTaskOwnedWindows(taskId);
      sendResponse({
        ok: true,
        taskId,
        matchedCount: result.matched.length,
        closed: result.closed,
        remaining: result.remaining,
        cleanupStatus: result.remaining.length ? "warning" : "closed"
      });
      return;
    }
    if (message.type === "guard:close-window-by-id") {
      const windowId = Number(message.windowId);
      if (!Number.isInteger(windowId) || windowId <= 0) {
        throw new Error("windowId is required");
      }
      const result = await closeOwnedWindowIfTracked(windowId);
      sendResponse({ ok: true, ...result, windowId });
      return;
    }
    if (message.type === "guard:close-latest-window") {
      await closeExpiredOwnedWindows();
      const items = await pruneOwnedWindows();
      const latest = items.at(-1);
      if (!latest) {
        sendResponse({ ok: true, closed: null, reason: "no_owned_windows" });
        return;
      }
      await closeOwnedWindow(latest.windowId);
      sendResponse({ ok: true, closed: latest });
      return;
    }
    throw new Error(`Unsupported message type: ${String(message.type || "")}`);
  })().catch((error) => {
    sendResponse({
      ok: false,
      error: error instanceof Error ? error.message : String(error)
    });
  }).finally(() => {
    const senderWindowId = Number(_sender?.tab?.windowId || 0);
    const shouldCloseSelfWindow = Boolean(message?.closeSelfWindow) && Number.isInteger(senderWindowId) && senderWindowId > 0;
    if (!shouldCloseSelfWindow) {
      return;
    }
    globalThis.setTimeout(() => {
      chrome.windows.remove(senderWindowId).catch(() => {
        // Ignore self-close failures for bridge windows.
      });
    }, 80);
  });
  return true;
});
