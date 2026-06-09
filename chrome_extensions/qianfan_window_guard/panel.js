const urlInput = document.getElementById("url");
const delayInput = document.getElementById("delay");
const statusEl = document.getElementById("status");
const DEFAULT_DELAY_MS = 60000;
const LONG_TASK_DELAY_MS = 600000;
const panelParams = new URLSearchParams(window.location.search);

function setStatus(title, payload) {
  const body = typeof payload === "string" ? payload : JSON.stringify(payload, null, 2);
  statusEl.textContent = `${title}\n${body}`;
}

function setDelayPreset(delayMs, label) {
  delayInput.value = String(delayMs);
  setStatus("已切换自动关闭时长", {
    mode: label,
    autoCloseMs: delayMs
  });
}

async function guard(message) {
  const response = await chrome.runtime.sendMessage(message);
  if (!response || !response.ok) {
    throw new Error(response?.error || "Unknown extension error");
  }
  return response;
}

async function refreshList() {
  const response = await guard({ type: "guard:list" });
  setStatus("当前自建窗口列表", response.items);
}

function schedulePanelFallbackClose(windowId, autoCloseMs) {
  const delay = Math.max(0, Number(autoCloseMs || 0));
  window.setTimeout(async () => {
    try {
      await guard({
        type: "guard:close-window-by-id",
        windowId
      });
    } catch (_error) {
      // Ignore: the background alarm may have already closed it.
    } finally {
      try {
        await refreshList();
      } catch (_refreshError) {
        // Ignore refresh errors in fallback timer.
      }
    }
  }, delay + 500);
}

function readPositiveInt(value, fallbackValue) {
  const parsed = Number.parseInt(String(value || ""), 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return fallbackValue;
  }
  return parsed;
}

function shouldCloseSelf() {
  return panelParams.get("closeSelf") === "1";
}

function scheduleSelfClose() {
  window.setTimeout(() => {
    window.close();
  }, 120);
}

async function runAutoActionFromQuery() {
  const action = String(panelParams.get("action") || "").trim();
  if (!action) {
    return false;
  }
  const taskId = String(panelParams.get("taskId") || "").trim();
  const targetUrl = String(panelParams.get("targetUrl") || "").trim();
  const autoCloseMs = readPositiveInt(panelParams.get("autoCloseMs"), DEFAULT_DELAY_MS);
  const closeSelfWindow = shouldCloseSelf();

  if (targetUrl) {
    urlInput.value = targetUrl;
  }
  delayInput.value = String(autoCloseMs);

  if (action === "open_auto_close") {
    const response = await guard({
      type: "guard:open-window-and-auto-close",
      url: targetUrl || urlInput.value,
      autoCloseMs,
      taskId,
      closeSelfWindow
    });
    setStatus("桥接页已托管打开任务窗口", response);
    if (closeSelfWindow) {
      scheduleSelfClose();
    }
    return true;
  }

  if (action === "close_task") {
    const response = await guard({
      type: "guard:close-task-windows",
      taskId,
      closeSelfWindow
    });
    setStatus("桥接页已托管关闭任务窗口", response);
    if (closeSelfWindow) {
      scheduleSelfClose();
    }
    return true;
  }

  throw new Error(`Unsupported auto action: ${action}`);
}

document.getElementById("open-auto-close").addEventListener("click", async () => {
  try {
    const response = await guard({
      type: "guard:open-window-and-auto-close",
      url: urlInput.value,
      autoCloseMs: Number(delayInput.value || DEFAULT_DELAY_MS)
    });
    setStatus("已打开并计划自动关闭", response);
    if (response?.opened?.windowId) {
      schedulePanelFallbackClose(response.opened.windowId, Number(delayInput.value || DEFAULT_DELAY_MS));
    }
    window.setTimeout(refreshList, Number(delayInput.value || DEFAULT_DELAY_MS) + 1200);
  } catch (error) {
    setStatus("打开失败", error.message);
  }
});

document.getElementById("open-only").addEventListener("click", async () => {
  try {
    const response = await guard({
      type: "guard:open-window",
      url: urlInput.value
    });
    setStatus("已打开", response);
    await refreshList();
  } catch (error) {
    setStatus("打开失败", error.message);
  }
});

document.getElementById("close-latest").addEventListener("click", async () => {
  try {
    const response = await guard({ type: "guard:close-latest-window" });
    setStatus("关闭结果", response);
    await refreshList();
  } catch (error) {
    setStatus("关闭失败", error.message);
  }
});

document.getElementById("refresh").addEventListener("click", async () => {
  try {
    await refreshList();
  } catch (error) {
    setStatus("刷新失败", error.message);
  }
});

document.getElementById("preset-short").addEventListener("click", () => {
  setDelayPreset(DEFAULT_DELAY_MS, "short_task_60s");
});

document.getElementById("preset-long").addEventListener("click", () => {
  setDelayPreset(LONG_TASK_DELAY_MS, "long_task_10m");
});

(async () => {
  try {
    const autoRan = await runAutoActionFromQuery();
    if (!autoRan) {
      await refreshList();
    }
  } catch (error) {
    setStatus("初始化失败", error.message);
  }
})();
