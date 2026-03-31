#!/usr/bin/env node
/**
 * Harness Evolver installer.
 * Copies plugin to Claude Code plugin cache and registers it.
 *
 * Usage: npx harness-evolver@latest
 */

const fs = require("fs");
const path = require("path");
const readline = require("readline");
const { execSync } = require("child_process");

const VERSION = require("../package.json").version;
const PLUGIN_ROOT = path.resolve(__dirname, "..");
const HOME = process.env.HOME || process.env.USERPROFILE;

const MAGENTA = "\x1b[35m";
const BRIGHT_MAGENTA = "\x1b[95m";
const GREEN = "\x1b[32m";
const YELLOW = "\x1b[33m";
const RED = "\x1b[31m";
const DIM = "\x1b[2m";
const BOLD = "\x1b[1m";
const RESET = "\x1b[0m";

const LOGO = `
${BRIGHT_MAGENTA}  ██╗  ██╗ █████╗ ██████╗ ███╗   ██╗███████╗███████╗███████╗
  ██║  ██║██╔══██╗██╔══██╗████╗  ██║██╔════╝██╔════╝██╔════╝
  ███████║███████║██████╔╝██╔██╗ ██║█████╗  ███████╗███████╗
  ██╔══██║██╔══██║██╔══██╗██║╚██╗██║██╔══╝  ╚════██║╚════██║
  ██║  ██║██║  ██║██║  ██║██║ ╚████║███████╗███████║███████║
  ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝╚══════╝╚══════╝╚══════╝
  ${MAGENTA}${BOLD}███████╗██╗   ██╗ ██████╗ ██╗    ██╗   ██╗███████╗██████╗
  ██╔════╝██║   ██║██╔═══██╗██║    ██║   ██║██╔════╝██╔══██╗
  █████╗  ██║   ██║██║   ██║██║    ██║   ██║█████╗  ██████╔╝
  ██╔══╝  ╚██╗ ██╔╝██║   ██║██║    ╚██╗ ██╔╝██╔══╝  ██╔══██╗
  ███████╗ ╚████╔╝ ╚██████╔╝███████╗╚████╔╝ ███████╗██║  ██║
  ╚══════╝  ╚═══╝   ╚═════╝ ╚══════╝ ╚═══╝  ╚══════╝╚═╝  ╚═╝${RESET}
`;

function ask(rl, question) {
  return new Promise((resolve) => rl.question(question, resolve));
}

function copyDir(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "node_modules" || entry.name === ".git" || entry.name === "__pycache__" || entry.name === "tests" || entry.name === "docs") continue;
      copyDir(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

function checkPython() {
  try {
    execSync("python3 --version", { stdio: "pipe" });
    return true;
  } catch {
    return false;
  }
}

function readJSON(filepath) {
  try {
    return JSON.parse(fs.readFileSync(filepath, "utf8"));
  } catch {
    return null;
  }
}

function writeJSON(filepath, data) {
  fs.mkdirSync(path.dirname(filepath), { recursive: true });
  fs.writeFileSync(filepath, JSON.stringify(data, null, 2) + "\n");
}

function installPlugin(runtimeDir, scope) {
  const baseDir = scope === "local"
    ? path.join(process.cwd(), runtimeDir)
    : path.join(HOME, runtimeDir);

  // 1. Copy plugin to cache
  const cacheDir = path.join(baseDir, "plugins", "cache", "local", "harness-evolver", VERSION);
  console.log(`  Copying plugin to ${scope === "local" ? "." : "~"}/${runtimeDir}/plugins/cache/...`);
  copyDir(PLUGIN_ROOT, cacheDir);
  console.log(`  ${GREEN}✓${RESET} Plugin files copied`);

  // 2. Register in installed_plugins.json
  const installedPath = path.join(baseDir, "plugins", "installed_plugins.json");
  let installed = readJSON(installedPath) || { version: 2, plugins: {} };
  if (!installed.plugins) installed.plugins = {};

  installed.plugins["harness-evolver@local"] = [{
    scope: "user",
    installPath: cacheDir,
    version: VERSION,
    installedAt: new Date().toISOString(),
    lastUpdated: new Date().toISOString(),
  }];
  writeJSON(installedPath, installed);
  console.log(`  ${GREEN}✓${RESET} Registered in installed_plugins.json`);

  // 3. Enable in settings.json
  const settingsPath = path.join(baseDir, "settings.json");
  let settings = readJSON(settingsPath) || {};
  if (!settings.enabledPlugins) settings.enabledPlugins = {};
  settings.enabledPlugins["harness-evolver@local"] = true;
  writeJSON(settingsPath, settings);
  console.log(`  ${GREEN}✓${RESET} Enabled in settings.json`);

  // Count installed items
  const skillCount = fs.existsSync(path.join(cacheDir, "skills"))
    ? fs.readdirSync(path.join(cacheDir, "skills")).filter(f =>
        fs.statSync(path.join(cacheDir, "skills", f)).isDirectory()
      ).length
    : 0;
  const agentCount = fs.existsSync(path.join(cacheDir, "agents"))
    ? fs.readdirSync(path.join(cacheDir, "agents")).length
    : 0;
  const toolCount = fs.existsSync(path.join(cacheDir, "tools"))
    ? fs.readdirSync(path.join(cacheDir, "tools")).filter(f => f.endsWith(".py")).length
    : 0;

  console.log(`  ${GREEN}✓${RESET} ${skillCount} skills, ${agentCount} agent, ${toolCount} tools`);
}

function installToolsGlobal() {
  const toolsDir = path.join(HOME, ".harness-evolver", "tools");
  const toolsSource = path.join(PLUGIN_ROOT, "tools");
  if (fs.existsSync(toolsSource)) {
    fs.mkdirSync(toolsDir, { recursive: true });
    for (const tool of fs.readdirSync(toolsSource)) {
      if (tool.endsWith(".py")) {
        fs.copyFileSync(path.join(toolsSource, tool), path.join(toolsDir, tool));
      }
    }
    console.log(`  ${GREEN}✓${RESET} Tools copied to ~/.harness-evolver/tools/`);
  }
}

function installExamples() {
  const examplesDir = path.join(HOME, ".harness-evolver", "examples");
  const examplesSource = path.join(PLUGIN_ROOT, "examples");
  if (fs.existsSync(examplesSource)) {
    copyDir(examplesSource, examplesDir);
    console.log(`  ${GREEN}✓${RESET} Examples copied to ~/.harness-evolver/examples/`);
  }
}

async function main() {
  console.log(LOGO);
  console.log(`  ${DIM}Harness Evolver v${VERSION}${RESET}`);
  console.log(`  ${DIM}Meta-Harness-style autonomous harness optimization${RESET}`);
  console.log();

  if (!checkPython()) {
    console.error(`  ${RED}ERROR:${RESET} python3 not found in PATH. Install Python 3.8+ first.`);
    process.exit(1);
  }
  console.log(`  ${GREEN}✓${RESET} python3 found`);

  // Detect runtimes
  const RUNTIMES = [
    { name: "Claude Code", dir: ".claude" },
    { name: "Cursor", dir: ".cursor" },
    { name: "Codex", dir: ".codex" },
    { name: "Windsurf", dir: ".windsurf" },
  ].filter(r => fs.existsSync(path.join(HOME, r.dir)));

  if (RUNTIMES.length === 0) {
    console.error(`\n  ${RED}ERROR:${RESET} No supported runtime detected.`);
    console.error(`  Install Claude Code, Cursor, Codex, or Windsurf first.`);
    process.exit(1);
  }

  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });

  // Runtime selection
  console.log(`\n  ${YELLOW}Which runtime(s) would you like to install for?${RESET}\n`);
  RUNTIMES.forEach((r, i) => console.log(`  ${i + 1}) ${r.name.padEnd(14)} (~/${r.dir})`));
  if (RUNTIMES.length > 1) {
    console.log(`  ${RUNTIMES.length + 1}) All`);
    console.log(`\n  ${DIM}Select multiple: 1,2 or 1 2${RESET}`);
  }

  const runtimeAnswer = await ask(rl, `\n  ${YELLOW}Choice [1]:${RESET} `);
  const runtimeInput = (runtimeAnswer.trim() || "1");

  let selected;
  if (runtimeInput === String(RUNTIMES.length + 1)) {
    selected = RUNTIMES;
  } else {
    const indices = runtimeInput.split(/[,\s]+/).map(s => parseInt(s, 10) - 1);
    selected = indices.filter(i => i >= 0 && i < RUNTIMES.length).map(i => RUNTIMES[i]);
  }
  if (selected.length === 0) selected = [RUNTIMES[0]];

  // Scope selection
  console.log(`\n  ${YELLOW}Where would you like to install?${RESET}\n`);
  console.log(`  1) Global  (~/${selected[0].dir}) - available in all projects`);
  console.log(`  2) Local   (./${selected[0].dir}) - this project only`);

  const scopeAnswer = await ask(rl, `\n  ${YELLOW}Choice [1]:${RESET} `);
  const scope = (scopeAnswer.trim() === "2") ? "local" : "global";

  console.log();

  // Install
  for (const runtime of selected) {
    console.log(`  Installing for ${BRIGHT_MAGENTA}${runtime.name}${RESET}\n`);
    installPlugin(runtime.dir, scope);
    console.log();
  }

  installToolsGlobal();
  installExamples();

  // Version marker
  const versionPath = path.join(HOME, ".harness-evolver", "VERSION");
  fs.mkdirSync(path.dirname(versionPath), { recursive: true });
  fs.writeFileSync(versionPath, VERSION);
  console.log(`  ${GREEN}✓${RESET} VERSION ${VERSION}`);

  console.log(`\n  ${GREEN}Done!${RESET} Open a project in Claude Code and run ${BRIGHT_MAGENTA}/harness-evolver:init${RESET}`);
  console.log(`\n  ${DIM}Quick start with example:${RESET}`);
  console.log(`    cp -r ~/.harness-evolver/examples/classifier ./my-project`);
  console.log(`    cd my-project && claude`);
  console.log(`    /harness-evolver:init`);
  console.log(`    /harness-evolver:evolve`);
  console.log(`\n  ${DIM}GitHub: https://github.com/raphaelchristi/harness-evolver${RESET}\n`);

  rl.close();
}

main().catch(err => {
  console.error(`  ${RED}ERROR:${RESET} ${err.message}`);
  process.exit(1);
});
