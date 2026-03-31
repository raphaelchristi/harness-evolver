#!/usr/bin/env node
/**
 * Harness Evolver installer.
 * Copies skills/agents/tools directly to runtime directories (GSD pattern).
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
      copyDir(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

function copyFile(src, dest) {
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.copyFileSync(src, dest);
}

function checkPython() {
  try {
    execSync("python3 --version", { stdio: "pipe" });
    return true;
  } catch {
    return false;
  }
}

function installForRuntime(runtimeDir, scope) {
  const baseDir = scope === "local"
    ? path.join(process.cwd(), runtimeDir)
    : path.join(HOME, runtimeDir);

  const commandsDir = path.join(baseDir, "commands", "harness-evolver");
  const agentsDir = path.join(baseDir, "agents");

  // Skills → commands/harness-evolver/ as flat .md files
  // Claude Code expects commands/name.md, not commands/name/SKILL.md
  const skillsSource = path.join(PLUGIN_ROOT, "skills");
  if (fs.existsSync(skillsSource)) {
    fs.mkdirSync(commandsDir, { recursive: true });
    for (const skill of fs.readdirSync(skillsSource, { withFileTypes: true })) {
      if (skill.isDirectory()) {
        const skillMd = path.join(skillsSource, skill.name, "SKILL.md");
        if (fs.existsSync(skillMd)) {
          fs.copyFileSync(skillMd, path.join(commandsDir, skill.name + ".md"));
          console.log(`  ${GREEN}✓${RESET} Installed command: harness-evolver:${skill.name}`);
        }
      }
    }
  }

  // Agents → agents/
  const agentsSource = path.join(PLUGIN_ROOT, "agents");
  if (fs.existsSync(agentsSource)) {
    fs.mkdirSync(agentsDir, { recursive: true });
    for (const agent of fs.readdirSync(agentsSource)) {
      copyFile(path.join(agentsSource, agent), path.join(agentsDir, agent));
      console.log(`  ${GREEN}✓${RESET} Installed agent: ${agent}`);
    }
  }
}

function installTools() {
  const toolsDir = path.join(HOME, ".harness-evolver", "tools");
  const toolsSource = path.join(PLUGIN_ROOT, "tools");
  if (fs.existsSync(toolsSource)) {
    fs.mkdirSync(toolsDir, { recursive: true });
    for (const tool of fs.readdirSync(toolsSource)) {
      if (tool.endsWith(".py")) {
        copyFile(path.join(toolsSource, tool), path.join(toolsDir, tool));
      }
    }
    console.log(`  ${GREEN}✓${RESET} Installed tools to ~/.harness-evolver/tools/`);
  }
}

function installExamples() {
  const examplesDir = path.join(HOME, ".harness-evolver", "examples");
  const examplesSource = path.join(PLUGIN_ROOT, "examples");
  if (fs.existsSync(examplesSource)) {
    copyDir(examplesSource, examplesDir);
    console.log(`  ${GREEN}✓${RESET} Installed examples to ~/.harness-evolver/examples/`);
  }
}

function cleanupBrokenPluginEntry(runtimeDir) {
  // Remove the harness-evolver@local entry that doesn't work
  const installedPath = path.join(HOME, runtimeDir, "plugins", "installed_plugins.json");
  try {
    const data = JSON.parse(fs.readFileSync(installedPath, "utf8"));
    if (data.plugins && data.plugins["harness-evolver@local"]) {
      delete data.plugins["harness-evolver@local"];
      fs.writeFileSync(installedPath, JSON.stringify(data, null, 2) + "\n");
    }
  } catch {}

  const settingsPath = path.join(HOME, runtimeDir, "settings.json");
  try {
    const data = JSON.parse(fs.readFileSync(settingsPath, "utf8"));
    if (data.enabledPlugins && data.enabledPlugins["harness-evolver@local"] !== undefined) {
      delete data.enabledPlugins["harness-evolver@local"];
      fs.writeFileSync(settingsPath, JSON.stringify(data, null, 2) + "\n");
    }
  } catch {}
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

  console.log(`\n  ${YELLOW}Where would you like to install?${RESET}\n`);
  console.log(`  1) Global  (~/${selected[0].dir}) - available in all projects`);
  console.log(`  2) Local   (./${selected[0].dir}) - this project only`);

  const scopeAnswer = await ask(rl, `\n  ${YELLOW}Choice [1]:${RESET} `);
  const scope = (scopeAnswer.trim() === "2") ? "local" : "global";

  console.log();

  for (const runtime of selected) {
    console.log(`  Installing for ${BRIGHT_MAGENTA}${runtime.name}${RESET}\n`);
    cleanupBrokenPluginEntry(runtime.dir);
    installForRuntime(runtime.dir, scope);
    console.log();
  }

  installTools();
  installExamples();

  const versionPath = path.join(HOME, ".harness-evolver", "VERSION");
  fs.mkdirSync(path.dirname(versionPath), { recursive: true });
  fs.writeFileSync(versionPath, VERSION);
  console.log(`  ${GREEN}✓${RESET} VERSION ${VERSION}`);

  console.log(`\n  ${GREEN}Done!${RESET} Run ${BRIGHT_MAGENTA}/reload-plugins${RESET} in Claude Code, then ${BRIGHT_MAGENTA}/harness-evolver:init${RESET}`);
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
