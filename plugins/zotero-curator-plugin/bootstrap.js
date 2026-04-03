"use strict";

var chromeHandle;

const WINDOW_URL = "chrome://zotero/content/zoteroPane.xhtml";
const DIALOG_URL = "chrome://zotero-curator/content/dialog.xhtml";
const MENU_ID = "zotero-curator-menuitem";
const PREF_BRANCH = "extensions.zotero-curator.";

function getPref(name, fallback = "") {
  try {
    return Services.prefs.getStringPref(PREF_BRANCH + name, fallback);
  }
  catch (e) {
    return fallback;
  }
}

function setPref(name, value) {
  Services.prefs.setStringPref(PREF_BRANCH + name, value || "");
}

function getCollectionPath(win) {
  try {
    const pane = win.ZoteroPane;
    const collection = pane && pane.getSelectedCollection && pane.getSelectedCollection();
    if (!collection) {
      return "";
    }
    let current = collection;
    const parts = [];
    while (current) {
      parts.unshift(current.name);
      const parentID = current.parentID || current.parentCollectionID;
      current = parentID ? win.Zotero.Collections.get(parentID) : null;
    }
    return parts.join("/");
  }
  catch (e) {
    return "";
  }
}

function ensureMenuItem(win) {
  if (!win || win.location.href !== WINDOW_URL) {
    return;
  }
  if (win.document.getElementById(MENU_ID)) {
    return;
  }
  const popup = win.document.getElementById("menu_ToolsPopup");
  if (!popup) {
    return;
  }
  const item = win.document.createXULElement("menuitem");
  item.id = MENU_ID;
  item.setAttribute("label", "Zotero Curator Import...");
  item.addEventListener("command", () => {
    win.openDialog(
      DIALOG_URL,
      "zotero-curator-dialog",
      "chrome,centerscreen,resizable,width=900,height=760",
      {
        initialCollectionPath: getCollectionPath(win),
        pluginAPI: ZoteroCuratorPlugin
      }
    );
  });
  popup.appendChild(item);
}

function removeMenuItem(win) {
  if (!win) {
    return;
  }
  win.document.getElementById(MENU_ID)?.remove();
}

var ZoteroCuratorPlugin = {
  getConfig() {
    return {
      pythonPath: getPref("pythonPath", ""),
      repoRoot: getPref("repoRoot", ""),
      clientKey: getPref("clientKey", ""),
      clientSecret: getPref("clientSecret", ""),
      targetCollection: getPref("targetCollection", "")
    };
  },

  saveConfig(config) {
    setPref("pythonPath", config.pythonPath || "");
    setPref("repoRoot", config.repoRoot || "");
    setPref("clientKey", config.clientKey || "");
    setPref("clientSecret", config.clientSecret || "");
    setPref("targetCollection", config.targetCollection || "");
  },

  getSelectedCollectionPath() {
    const win = Zotero.getMainWindow();
    return win ? getCollectionPath(win) : "";
  },

  async writeTextFile(path, text) {
    await Zotero.File.putContentsAsync(path, text);
  },

  async readTextFile(path) {
    return Zotero.File.getContentsAsync(path);
  },

  getTempSessionDir() {
    const tmp = Services.dirsvc.get("TmpD", Ci.nsIFile);
    const dir = tmp.clone();
    dir.append("zotero-curator-plugin");
    if (!dir.exists()) {
      dir.create(Ci.nsIFile.DIRECTORY_TYPE, 0o755);
    }
    dir.append("session-" + Date.now());
    dir.create(Ci.nsIFile.DIRECTORY_TYPE, 0o755);
    return dir.path;
  },

  launchProcess(executablePath, args) {
    const file = Cc["@mozilla.org/file/local;1"].createInstance(Ci.nsIFile);
    file.initWithPath(executablePath);
    const process = Cc["@mozilla.org/process/util;1"].createInstance(Ci.nsIProcess);
    process.init(file);

    return new Promise((resolve, reject) => {
      const observer = {
        observe(subject, topic) {
          if (topic === "process-finished") {
            resolve(process.exitValue);
          }
          else if (topic === "process-failed") {
            reject(new Error("Local curator process failed to start"));
          }
        }
      };
      try {
        process.runwAsync(args, args.length, observer, false);
      }
      catch (e) {
        reject(e);
      }
    });
  }
};

function install() {}

async function startup({ rootURI }) {
  var aomStartup = Cc["@mozilla.org/addons/addon-manager-startup;1"].getService(Ci.amIAddonManagerStartup);
  var manifestURI = Services.io.newURI(rootURI + "manifest.json");
  chromeHandle = aomStartup.registerChrome(manifestURI, [
    ["content", "zotero-curator", rootURI + "content/"]
  ]);
}

async function onMainWindowLoad({ window }) {
  ensureMenuItem(window);
}

async function onMainWindowUnload({ window }) {
  removeMenuItem(window);
}

async function shutdown() {
  if (chromeHandle) {
    chromeHandle.destruct();
    chromeHandle = null;
  }
  const win = Zotero.getMainWindow();
  if (win) {
    removeMenuItem(win);
  }
}

function uninstall() {}
