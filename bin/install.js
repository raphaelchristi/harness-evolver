#!/usr/bin/env node
/**
 * Harness Evolver installer.
 * Interactive setup with runtime selection, global/local choice.
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

// ANSI colors
const CYAN = "\x1b[36m";
const GREEN = "\x1b[32m";
const YELLOW = "\x1b[33m";
const RED = "\x1b[31m";
const DIM = "\x1b[2m";
const BOLD = "\x1b[1m";
const RESET = "\x1b[0m";

const LOGO = `
${CYAN}  ██╗  ██╗ █████╗ ██████╗ ███╗   ██╗███████╗███████╗███████╗
  ██║  ██║██╔══██╗██╔══██╗████╗  ██║██╔════╝██╔════╝██╔════╝
  ███████║███████║██████╔╝██╔██╗ ██║█████╗  ███████╗███████╗
  ██╔══██║██╔══██║██╔══██╗██║╚██╗██║██╔══╝  ╚════██║╚════██║
  ██║  ██║██║  ██║██║  ██║██║ ╚████║███████╗███████║███████║
  ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝╚══════╝╚══════╝╚══════╝
  ${BOLD}███████╗██╗   ██╗ ██████╗ ██╗    ██╗   ██╗███████╗██████╗
  ██╔════╝██║   ██║██╔═══██╗██║    ██║   ██║██╔════╝██╔══██╗
  █████╗  ██║   ██║██║   ██║██║    ██║   ██║█████╗  ██████╔╝
  ██╔══╝  ╚██╗ ██╔╝██║   ██║██║    ╚██╗ ██╔╝██╔══╝  ██╔══██╗
  ███████╗ ╚████╔╝ ╚██████╔╝███████╗╚████╔╝ ███████╗██║  ██║
  ╚══════╝  ╚═══╝   ╚═════╝ ╚══════╝ ╚═══╝  ╚══════╝╚═╝  ╚═╝${RESET}
`;

const RUNTIMES = [
  { name: "Claude Code", dir: ".claude", detected: () => fs.existsSync(path.join(HOME, ".claude")) },
  { name: "Cursor", dir: ".cursor", detected: () => fs.existsSync(path.join(HOME, ".cursor")) },
  { name: "Codex", dir: ".codex", detected: () => fs.existsSync(path.join(HOME, ".codex")) },
  { name: "Windsurf", dir: ".windsurf", detected: () => fs.existsSync(path.join(HOME, ".windsurf")) },
];

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

  // Skills
  const skillsSource = path.join(PLUGIN_ROOT, "skills");
  if (fs.existsSync(skillsSource)) {
    for (const skill of fs.readdirSync(skillsSource, { withFileTypes: true })) {
      if (skill.isDirectory()) {
        copyDir(path.join(skillsSource, skill.name), path.join(commandsDir, skill.name));
        console.log(`  ${GREEN}✓${RESET} Installed skill: ${skill.name}`);
      }
    }
  }

  // Agents
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
        console.log(`  ${GREEN}✓${RESET} Installed tool: ${tool}`);
      }
    }
  }
}

function installExamples() {
  const examplesDir = path.join(HOME, ".harness-evolver", "examples");
  const examplesSource = path.join(PLUGIN_ROOT, "examples");
  if (fs.existsSync(examplesSource)) {
    copyDir(examplesSource, examplesDir);
    console.log(`  ${GREEN}✓${RESET} Installed examples: classifier`);
  }
}

async function main() {
  console.log(LOGO);
  console.log(`  ${DIM}Harness Evolver v${VERSION}${RESET}`);
  console.log(`  ${DIM}Meta-Harness-style autonomous harness optimization${RESET}`);
  console.log();

  // Check python
  if (!checkPython()) {
    console.error(`  ${RED}ERROR:${RESET} python3 not found in PATH. Install Python 3.8+ first.`);
    process.exit(1);
  }
  console.log(`  ${GREEN}✓${RESET} python3 found`);

  // Detect runtimes
  const available = RUNTIMES.filter((r) => r.detected());
  if (available.length === 0) {
    console.error(`\n  ${RED}ERROR:${RESET} No supported runtime detected.`);
    console.error(`  Install Claude Code, Cursor, Codex, or Windsurf first.`);
    process.exit(1);
  }

  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });

  // Runtime selection
  console.log(`\n  ${YELLOW}Which runtime(s) would you like to install for?${RESET}\n`);
  available.forEach((r, i) => {
    console.log(`  ${i + 1}) ${r.name.padEnd(14)} (~/${r.dir})`);
  });
  if (available.length > 1) {
    console.log(`  ${available.length + 1}) All`);
    console.log(`\n  ${DIM}Select multiple: 1,2 or 1 2${RESET}`);
  }

  const defaultChoice = "1";
  const runtimeAnswer = await ask(rl, `\n  ${YELLOW}Choice [${defaultChoice}]:${RESET} `);
  const runtimeInput = (runtimeAnswer.trim() || defaultChoice);

  let selectedRuntimes;
  if (runtimeInput === String(available.length + 1)) {
    selectedRuntimes = available;
  } else {
    const indices = runtimeInput.split(/[,\s]+/).map((s) => parseInt(s, 10) - 1);
    selectedRuntimes = indices
      .filter((i) => i >= 0 && i < available.length)
      .map((i) => available[i]);
  }

  if (selectedRuntimes.length === 0) {
    selectedRuntimes = [available[0]];
  }

  // Scope selection
  console.log(`\n  ${YELLOW}Where would you like to install?${RESET}\n`);
  console.log(`  1) Global  (~/${selectedRuntimes[0].dir}) - available in all projects`);
  console.log(`  2) Local   (./${selectedRuntimes[0].dir}) - this project only`);

  const scopeAnswer = await ask(rl, `\n  ${YELLOW}Choice [1]:${RESET} `);
  const scope = (scopeAnswer.trim() === "2") ? "local" : "global";

  console.log();

  // Install for each selected runtime
  for (const runtime of selectedRuntimes) {
    const target = scope === "local" ? `./${runtime.dir}` : `~/${runtime.dir}`;
    console.log(`  Installing for ${CYAN}${runtime.name}${RESET} to ${target}`);
    console.log();
    installForRuntime(runtime.dir, scope);
  }

  // Tools and examples are always global
  installTools();
  installExamples();

  // Write version file
  const versionPath = path.join(HOME, ".harness-evolver", "VERSION");
  fs.mkdirSync(path.dirname(versionPath), { recursive: true });
  fs.writeFileSync(versionPath, VERSION);
  console.log(`  ${GREEN}✓${RESET} Wrote VERSION (${VERSION})`);

  console.log(`\n  ${GREEN}Done!${RESET} Open a project in Claude Code and run ${CYAN}/harness-evolver:init${RESET}`);
  console.log(`\n  ${DIM}Quick start with example:${RESET}`);
  console.log(`    cp -r ~/.harness-evolver/examples/classifier ./my-project`);
  console.log(`    cd my-project && claude`);
  console.log(`    /harness-evolver:init`);
  console.log(`    /harness-evolver:evolve`);

  console.log(`\n  ${DIM}GitHub: https://github.com/raphaelchristi/harness-evolver${RESET}`);
  console.log();

  rl.close();
}

main().catch((err) => {
  console.error(`  ${RED}ERROR:${RESET} ${err.message}`);
  process.exit(1);
});
