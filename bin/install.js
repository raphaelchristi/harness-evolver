#!/usr/bin/env node
/**
 * Harness Evolver installer.
 * Detects Claude Code, copies skills/agents/tools to the right locations.
 *
 * Usage: npx harness-evolver@latest
 */

const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

const PLUGIN_ROOT = path.resolve(__dirname, "..");
const HOME = process.env.HOME || process.env.USERPROFILE;

const CLAUDE_DIR = path.join(HOME, ".claude");
const COMMANDS_DIR = path.join(CLAUDE_DIR, "commands", "harness-evolver");
const AGENTS_DIR = path.join(CLAUDE_DIR, "agents");
const TOOLS_DIR = path.join(HOME, ".harness-evolver", "tools");
const EXAMPLES_DIR = path.join(HOME, ".harness-evolver", "examples");

function log(msg) {
  console.log(`  ${msg}`);
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

function main() {
  console.log("\n  Harness Evolver v0.1.0\n");

  if (!checkPython()) {
    console.error("  ERROR: python3 not found in PATH. Install Python 3.8+ first.");
    process.exit(1);
  }
  log("\u2713 python3 found");

  if (!fs.existsSync(CLAUDE_DIR)) {
    console.error(`  ERROR: Claude Code directory not found at ${CLAUDE_DIR}`);
    console.error("  Install Claude Code first: https://claude.ai/code");
    process.exit(1);
  }
  log("\u2713 Claude Code detected");

  // Copy skills
  const skillsSource = path.join(PLUGIN_ROOT, "skills");
  if (fs.existsSync(skillsSource)) {
    for (const skill of fs.readdirSync(skillsSource, { withFileTypes: true })) {
      if (skill.isDirectory()) {
        const src = path.join(skillsSource, skill.name);
        const dest = path.join(COMMANDS_DIR, skill.name);
        copyDir(src, dest);
        log(`  skill: ${skill.name}`);
      }
    }
  }

  // Copy agents
  const agentsSource = path.join(PLUGIN_ROOT, "agents");
  if (fs.existsSync(agentsSource)) {
    fs.mkdirSync(AGENTS_DIR, { recursive: true });
    for (const agent of fs.readdirSync(agentsSource)) {
      copyFile(
        path.join(agentsSource, agent),
        path.join(AGENTS_DIR, agent)
      );
      log(`  agent: ${agent}`);
    }
  }

  // Copy tools
  const toolsSource = path.join(PLUGIN_ROOT, "tools");
  if (fs.existsSync(toolsSource)) {
    fs.mkdirSync(TOOLS_DIR, { recursive: true });
    for (const tool of fs.readdirSync(toolsSource)) {
      if (tool.endsWith(".py")) {
        copyFile(
          path.join(toolsSource, tool),
          path.join(TOOLS_DIR, tool)
        );
        log(`  tool: ${tool}`);
      }
    }
  }

  // Copy examples
  const examplesSource = path.join(PLUGIN_ROOT, "examples");
  if (fs.existsSync(examplesSource)) {
    copyDir(examplesSource, EXAMPLES_DIR);
    log("  examples: classifier");
  }

  console.log("\n  \u2713 Installed successfully!\n");
  console.log("  Next steps:");
  console.log("    1. Copy an example:  cp -r ~/.harness-evolver/examples/classifier ./my-project");
  console.log("    2. cd my-project");
  console.log("    3. /harness-evolve-init --harness harness.py --eval eval.py --tasks tasks/");
  console.log("    4. /harness-evolve --iterations 5\n");
}

main();
