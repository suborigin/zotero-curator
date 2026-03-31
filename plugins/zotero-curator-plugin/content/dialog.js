"use strict";

var { Services } = ChromeUtils.import("resource://gre/modules/Services.jsm");

var ZoteroCuratorDialog = {
  pluginAPI: null,
  generatedPaths: null,

  init() {
    const args = (window.arguments && window.arguments[0]) || {};
    this.pluginAPI = args.pluginAPI;
    const config = this.pluginAPI.getConfig();

    document.getElementById("targetCollection").value =
      args.initialCollectionPath || config.targetCollection || this.pluginAPI.getSelectedCollectionPath() || "";
    document.getElementById("pythonPath").value = config.pythonPath || "";
    document.getElementById("repoRoot").value = config.repoRoot || "";
    document.getElementById("clientKey").value = config.clientKey || "";
    document.getElementById("clientSecret").value = config.clientSecret || "";
    document.getElementById("tags").value = "self-evolving";

    document.getElementById("generatePlanBtn").addEventListener("click", () => this.generatePlan());
    document.getElementById("runImportBtn").addEventListener("click", () => this.runImport());
    document.getElementById("copyCommandBtn").addEventListener("click", () => this.copyCommand());
    document.getElementById("closeBtn").addEventListener("click", () => window.close());
    this.appendStatus("Ready.");
  },

  appendStatus(message) {
    const box = document.getElementById("statusBox");
    const now = new Date().toLocaleTimeString();
    box.value = box.value ? box.value + "\n[" + now + "] " + message : "[" + now + "] " + message;
    box.scrollTop = box.scrollHeight;
  },

  getFormData() {
    return {
      articleText: document.getElementById("articleText").value.trim(),
      targetCollection: document.getElementById("targetCollection").value.trim(),
      pythonPath: document.getElementById("pythonPath").value.trim(),
      repoRoot: document.getElementById("repoRoot").value.trim(),
      clientKey: document.getElementById("clientKey").value.trim(),
      clientSecret: document.getElementById("clientSecret").value.trim(),
      tags: document.getElementById("tags").value
        .split(",")
        .map(tag => tag.trim())
        .filter(Boolean)
    };
  },

  validateBaseConfig(data) {
    if (!data.articleText) {
      throw new Error("Paste the article text first.");
    }
    if (!data.targetCollection) {
      throw new Error("Choose a target collection path.");
    }
    if (!data.pythonPath) {
      throw new Error("Set the Python executable path.");
    }
    if (!data.repoRoot) {
      throw new Error("Set the curator repo root.");
    }
  },

  persistConfig(data) {
    this.pluginAPI.saveConfig({
      pythonPath: data.pythonPath,
      repoRoot: data.repoRoot,
      clientKey: data.clientKey,
      clientSecret: data.clientSecret,
      targetCollection: data.targetCollection
    });
  },

  async ensureSessionFiles(data) {
    const dir = this.pluginAPI.getTempSessionDir();
    const articlePath = dir + "\\article.txt";
    const planPath = dir + "\\plan.yaml";
    const reportPath = dir + "\\report.json";
    await this.pluginAPI.writeTextFile(articlePath, data.articleText);
    this.generatedPaths = { dir, articlePath, planPath, reportPath };
    return this.generatedPaths;
  },

  async generatePlan() {
    try {
      const data = this.getFormData();
      this.validateBaseConfig(data);
      this.persistConfig(data);
      const paths = await this.ensureSessionFiles(data);
      this.appendStatus("Generating plan from article text...");
      const args = [
        "-m",
        "zotero_curator.cli",
        "plan",
        "from-text",
        "--input",
        paths.articlePath,
        "--output",
        paths.planPath,
        "--target-collection",
        data.targetCollection
      ];
      for (const tag of data.tags) {
        args.push("--tag", tag);
      }
      const exitCode = await this.pluginAPI.launchProcess(data.pythonPath, args);
      if (exitCode !== 0) {
        throw new Error("Plan generation exited with code " + exitCode + ".");
      }
      this.appendStatus("Plan generated: " + paths.planPath);
    }
    catch (e) {
      this.appendStatus("Error: " + e.message);
    }
  },

  buildSyncArgs(data, paths) {
    return [
      "-m",
      "zotero_curator.cli",
      "sync",
      "--plan",
      paths.planPath,
      "--report",
      paths.reportPath,
      "--oauth-authorize",
      "--delete-api-key-after",
      "--exclusive-target-collection",
      "--oauth-client-key",
      data.clientKey,
      "--oauth-client-secret",
      data.clientSecret
    ];
  },

  async runImport() {
    try {
      const data = this.getFormData();
      this.validateBaseConfig(data);
      if (!data.clientKey || !data.clientSecret) {
        throw new Error("Fill in the Zotero OAuth client key and client secret.");
      }
      this.persistConfig(data);
      if (!this.generatedPaths) {
        await this.generatePlan();
      }
      if (!this.generatedPaths || !this.generatedPaths.planPath) {
        throw new Error("Plan generation did not finish.");
      }
      this.appendStatus("Launching local curator import. Zotero will open the authorization page if needed.");
      const exitCode = await this.pluginAPI.launchProcess(data.pythonPath, this.buildSyncArgs(data, this.generatedPaths));
      if (exitCode !== 0) {
        throw new Error("Import exited with code " + exitCode + ".");
      }
      let summary = "Import finished.";
      try {
        const reportText = await this.pluginAPI.readTextFile(this.generatedPaths.reportPath);
        const report = JSON.parse(reportText);
        summary =
          "Import finished. Created items: " + (report.items_created || []).length +
          ", updated items: " + (report.items_updated || []).length +
          ", attachments: " + (report.attachments || []).length +
          ", errors: " + (report.errors || []).length + ".";
      }
      catch (e) {}
      this.appendStatus(summary);
      Services.prompt.alert(window, "Zotero Curator", summary);
    }
    catch (e) {
      this.appendStatus("Error: " + e.message);
      Services.prompt.alert(window, "Zotero Curator", e.message);
    }
  },

  async copyCommand() {
    try {
      const data = this.getFormData();
      this.validateBaseConfig(data);
      this.persistConfig(data);
      const paths = this.generatedPaths || await this.ensureSessionFiles(data);
      await this.pluginAPI.writeTextFile(paths.articlePath, data.articleText);
      const cmd = [
        "\"" + data.pythonPath + "\"",
        "-m zotero_curator.cli plan from-text",
        "--input \"" + paths.articlePath + "\"",
        "--output \"" + paths.planPath + "\"",
        "--target-collection \"" + data.targetCollection + "\"",
        ...data.tags.map(tag => "--tag \"" + tag + "\"")
      ].join(" ");
      Cc["@mozilla.org/widget/clipboardhelper;1"].getService(Ci.nsIClipboardHelper).copyString(cmd);
      this.appendStatus("Copied plan-generation command to clipboard.");
    }
    catch (e) {
      this.appendStatus("Error: " + e.message);
    }
  }
};
