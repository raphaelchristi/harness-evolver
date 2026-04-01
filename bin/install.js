#!/usr/bin/env node
/**
 * Harness Evolver installer.
 * Copies skills/agents/tools to runtime directories.
 * Installs Python dependencies (langsmith) and langsmith-cli.
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

// ─── Colors (zero dependencies, inline ANSI) ───────────────────────────────

const isColorSupported =
  process.env.FORCE_COLOR !== "0" &&
  !process.env.NO_COLOR &&
  (process.env.FORCE_COLOR !== undefined || process.stdout.isTTY);

function ansi(code) {
  return isColorSupported ? `\x1b[${code}m` : "";
}

const reset = ansi("0");
const bold = ansi("1");
const dim = ansi("2");
const red = ansi("31");
const green = ansi("32");
const yellow = ansi("33");
const cyan = ansi("36");
const gray = ansi("90");
const bgCyan = ansi("46");
const black = ansi("30");

const c = {
  bold: (s) => `${bold}${s}${reset}`,
  dim: (s) => `${dim}${s}${reset}`,
  red: (s) => `${red}${s}${reset}`,
  green: (s) => `${green}${s}${reset}`,
  yellow: (s) => `${yellow}${s}${reset}`,
  cyan: (s) => `${cyan}${s}${reset}`,
  gray: (s) => `${gray}${s}${reset}`,
  bgCyan: (s) => `${bgCyan}${black}${s}${reset}`,
};

// ─── Symbols ────────────────────────────────────────────────────────────────

const S = {
  bar: "\u2502",       // │
  barEnd: "\u2514",    // └
  barStart: "\u250C",  // ┌
  step: "\u25C7",      // ◇
  stepActive: "\u25C6",// ◆
  stepDone: "\u25CF",  // ●
  stepError: "\u25A0", // ■
};

// ─── UI helpers (clack-style) ───────────────────────────────────────────────

function barLine(content = "") {
  console.log(`${c.gray(S.bar)}  ${content}`);
}

function barEmpty() {
  console.log(`${c.gray(S.bar)}`);
}

function header(label) {
  console.log();
  console.log(`${c.gray(S.barStart)}  ${c.bgCyan(` ${label} `)}`);
}

function footer(message) {
  if (message) {
    console.log(`${c.gray(S.barEnd)}  ${message}`);
  } else {
    console.log(`${c.gray(S.barEnd)}`);
  }
}

function step(content) {
  console.log(`${c.gray(S.step)}  ${content}`);
}

function stepDone(content) {
  console.log(`${c.green(S.stepDone)}  ${content}`);
}

function stepError(content) {
  console.log(`${c.red(S.stepError)}  ${content}`);
}

function stepPrompt(content) {
  console.log(`${c.cyan(S.stepActive)}  ${content}`);
}

// ─── Banner (gradient dark → light) ─────────────────────────────────────────

const BANNER_LINES = [
  "\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2557   \u2588\u2588\u2557 \u2588\u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2557     \u2588\u2588\u2557   \u2588\u2588\u2557\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2588\u2588\u2588\u2588\u2557 ",
  "\u2588\u2588\u2554\u2550\u2550\u2550\u2550\u255D\u2588\u2588\u2551   \u2588\u2588\u2551\u2588\u2588\u2554\u2550\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2551     \u2588\u2588\u2551   \u2588\u2588\u2551\u2588\u2588\u2554\u2550\u2550\u2550\u2550\u255D\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557",
  "\u2588\u2588\u2588\u2588\u2588\u2557  \u255A\u2588\u2588\u2557 \u2588\u2588\u2554\u255D\u2588\u2588\u2551   \u2588\u2588\u2551\u2588\u2588\u2551     \u255A\u2588\u2588\u2557 \u2588\u2588\u2554\u255D\u2588\u2588\u2588\u2588\u2588\u2557  \u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255D",
  "\u2588\u2588\u2554\u2550\u2550\u255D   \u255A\u2588\u2588\u2588\u2588\u2554\u255D \u2588\u2588\u2551   \u2588\u2588\u2551\u2588\u2588\u2551      \u255A\u2588\u2588\u2588\u2588\u2554\u255D \u2588\u2588\u2554\u2550\u2550\u255D  \u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557",
  "\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557  \u255A\u2588\u2588\u2554\u255D  \u255A\u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255D\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557  \u255A\u2588\u2588\u2554\u255D  \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2551  \u2588\u2588\u2551",
  "\u255A\u2550\u2550\u2550\u2550\u2550\u2550\u255D   \u255A\u2550\u255D    \u255A\u2550\u2550\u2550\u2550\u2550\u255D \u255A\u2550\u2550\u2550\u2550\u2550\u2550\u255D   \u255A\u2550\u255D   \u255A\u2550\u2550\u2550\u2550\u2550\u2550\u255D\u255A\u2550\u255D  \u255A\u2550\u255D",
];

const GRADIENT = [
  [60, 60, 60],
  [90, 90, 90],
  [125, 125, 125],
  [160, 160, 160],
  [200, 200, 200],
  [240, 240, 240],
];

function rgb(r, g, b) {
  return isColorSupported ? `\x1b[38;2;${r};${g};${b}m` : "";
}

function banner() {
  console.log();
  for (let i = 0; i < BANNER_LINES.length; i++) {
    const [r, g, b] = GRADIENT[i];
    console.log(`${rgb(r, g, b)}${BANNER_LINES[i]}${reset}`);
  }
}

// ─── Utilities ──────────────────────────────────────────────────────────────

function ask(rl, question) {
  return new Promise((resolve) => rl.question(question, resolve));
}

function copyDir(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.name === "__pycache__") continue;
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

function checkCommand(cmd) {
  try {
    execSync(cmd, { stdio: "pipe" });
    return true;
  } catch {
    return false;
  }
}

// ─── Install logic ──────────────────────────────────────────────────────────

function cleanPreviousInstall(runtimeDir, scope) {
  const baseDir = scope === "local"
    ? path.join(process.cwd(), runtimeDir)
    : path.join(HOME, runtimeDir);

  const skillsDir = path.join(baseDir, "skills");
  const agentsDir = path.join(baseDir, "agents");
  let cleaned = 0;

  if (fs.existsSync(skillsDir)) {
    const ours = ["setup", "evolve", "deploy", "status",
      "init", "architect", "compare", "critic", "diagnose",
      "import-traces", "evolve-v3", "deploy-v3", "status-v3",
      "harness-evolver:init", "harness-evolver:evolve",
      "harness-evolver:status", "harness-evolver:deploy",
      "harness-evolver:compare", "harness-evolver:diagnose",
      "harness-evolver:architect", "harness-evolver:critic",
      "harness-evolver:import-traces"];
    for (const name of ours) {
      const p = path.join(skillsDir, name);
      if (fs.existsSync(p)) {
        fs.rmSync(p, { recursive: true, force: true });
        cleaned++;
      }
    }
  }

  if (fs.existsSync(agentsDir)) {
    for (const f of fs.readdirSync(agentsDir)) {
      if (f.startsWith("evolver-") || f.startsWith("harness-evolver-")) {
        fs.rmSync(path.join(agentsDir, f), { force: true });
        cleaned++;
      }
    }
  }

  const oldCommandsDir = path.join(baseDir, "commands", "harness-evolver");
  if (fs.existsSync(oldCommandsDir)) {
    fs.rmSync(oldCommandsDir, { recursive: true, force: true });
    cleaned++;
  }

  for (const toolsPath of [
    path.join(HOME, ".evolver", "tools"),
    path.join(HOME, ".harness-evolver"),
  ]) {
    if (fs.existsSync(toolsPath)) {
      fs.rmSync(toolsPath, { recursive: true, force: true });
      cleaned++;
    }
  }

  if (cleaned > 0) {
    barLine(c.dim(`Cleaned ${cleaned} items from previous install`));
  }
}

function countInstallables() {
  let skills = 0;
  let agents = 0;
  let tools = 0;

  const skillsSource = path.join(PLUGIN_ROOT, "skills");
  if (fs.existsSync(skillsSource)) {
    for (const s of fs.readdirSync(skillsSource, { withFileTypes: true })) {
      if (s.isDirectory() && fs.existsSync(path.join(skillsSource, s.name, "SKILL.md"))) skills++;
    }
  }

  const agentsSource = path.join(PLUGIN_ROOT, "agents");
  if (fs.existsSync(agentsSource)) {
    for (const a of fs.readdirSync(agentsSource)) {
      if (a.endsWith(".md")) agents++;
    }
  }

  const toolsSource = path.join(PLUGIN_ROOT, "tools");
  if (fs.existsSync(toolsSource)) {
    for (const t of fs.readdirSync(toolsSource)) {
      if (t.endsWith(".py")) tools++;
    }
  }

  return { skills, agents, tools };
}

function installSkillsAndAgents(runtimeDir, scope) {
  const baseDir = scope === "local"
    ? path.join(process.cwd(), runtimeDir)
    : path.join(HOME, runtimeDir);

  const skillsDir = path.join(baseDir, "skills");
  const agentsDir = path.join(baseDir, "agents");
  let installed = 0;

  const skillsSource = path.join(PLUGIN_ROOT, "skills");
  if (fs.existsSync(skillsSource)) {
    for (const skill of fs.readdirSync(skillsSource, { withFileTypes: true })) {
      if (!skill.isDirectory()) continue;
      const src = path.join(skillsSource, skill.name);
      const skillMd = path.join(src, "SKILL.md");
      if (!fs.existsSync(skillMd)) continue;

      const content = fs.readFileSync(skillMd, "utf8");
      const nameMatch = content.match(/^name:\s*(.+)$/m);
      const skillName = nameMatch ? nameMatch[1].trim() : skill.name;

      const dest = path.join(skillsDir, skill.name);
      copyDir(src, dest);
      barLine(`${c.green("\u2714")} ${skillName}`);
      installed++;
    }
  }

  const agentsSource = path.join(PLUGIN_ROOT, "agents");
  if (fs.existsSync(agentsSource)) {
    fs.mkdirSync(agentsDir, { recursive: true });
    for (const agent of fs.readdirSync(agentsSource)) {
      if (!agent.endsWith(".md")) continue;
      copyFile(path.join(agentsSource, agent), path.join(agentsDir, agent));
      const agentName = agent.replace(".md", "");
      barLine(`${c.green("\u2714")} agent: ${agentName}`);
      installed++;
    }
  }

  return installed;
}

function installTools() {
  const toolsDir = path.join(HOME, ".evolver", "tools");
  const toolsSource = path.join(PLUGIN_ROOT, "tools");
  if (fs.existsSync(toolsSource)) {
    fs.mkdirSync(toolsDir, { recursive: true });
    let count = 0;
    for (const tool of fs.readdirSync(toolsSource)) {
      if (!tool.endsWith(".py")) continue;
      copyFile(path.join(toolsSource, tool), path.join(toolsDir, tool));
      count++;
    }
    return count;
  }
  return 0;
}

function installPythonDeps() {
  const venvDir = path.join(HOME, ".evolver", "venv");
  const venvPython = path.join(venvDir, "bin", "python");
  const venvPip = path.join(venvDir, "bin", "pip");

  step("Setting up Python environment...");

  if (!fs.existsSync(venvPython)) {
    barLine("Creating isolated venv at ~/.evolver/venv/");
    const venvCommands = [
      `uv venv "${venvDir}"`,
      `python3 -m venv "${venvDir}"`,
    ];
    let created = false;
    for (const cmd of venvCommands) {
      try {
        execSync(cmd, { stdio: "pipe", timeout: 30000 });
        created = true;
        break;
      } catch {
        continue;
      }
    }
    if (!created) {
      stepError("Failed to create venv");
      barLine(c.dim(`Run manually: python3 -m venv ~/.evolver/venv`));
      return false;
    }
    stepDone("venv created");
  } else {
    stepDone("venv exists at ~/.evolver/venv/");
  }

  barEmpty();

  const installCommands = [
    `uv pip install --python "${venvPython}" langsmith`,
    `"${venvPip}" install --upgrade langsmith`,
    `"${venvPython}" -m pip install --upgrade langsmith`,
  ];

  step("Installing langsmith...");
  for (const cmd of installCommands) {
    try {
      execSync(cmd, { stdio: "pipe", timeout: 120000 });
      stepDone("langsmith installed in venv");
      return true;
    } catch {
      continue;
    }
  }

  stepError("Could not install langsmith");
  barLine(c.dim("Run manually: ~/.evolver/venv/bin/pip install langsmith"));
  return false;
}

async function configureLangSmith(rl) {
  const langsmithCredsDir = process.platform === "darwin"
    ? path.join(HOME, "Library", "Application Support", "langsmith-cli")
    : path.join(HOME, ".config", "langsmith-cli");
  const langsmithCredsFile = path.join(langsmithCredsDir, "credentials");
  const hasLangsmithCli = checkCommand("langsmith-cli --version");

  let hasKey = false;

  barEmpty();
  step(c.bold("LangSmith API Key") + " " + c.dim("(required)"));

  if (process.env.LANGSMITH_API_KEY) {
    stepDone("LANGSMITH_API_KEY found in environment");
    hasKey = true;
  } else if (fs.existsSync(langsmithCredsFile)) {
    try {
      const content = fs.readFileSync(langsmithCredsFile, "utf8");
      if (content.includes("LANGSMITH_API_KEY=lsv2_")) {
        stepDone("API key found in credentials file");
        hasKey = true;
      }
    } catch {}
  }

  if (!hasKey) {
    barLine(c.dim("Get yours at https://smith.langchain.com/settings"));
    barLine(c.dim("LangSmith is required. The evolver won't work without it."));
    barEmpty();

    let attempts = 0;
    while (!hasKey && attempts < 3) {
      const apiKey = await ask(rl, `${c.cyan(S.stepActive)}  Paste your LangSmith API key (lsv2_pt_...): `);
      const key = apiKey.trim();

      if (key && key.startsWith("lsv2_")) {
        try {
          fs.mkdirSync(langsmithCredsDir, { recursive: true });
          fs.writeFileSync(langsmithCredsFile, `LANGSMITH_API_KEY=${key}\n`);
          stepDone("API key saved");
          hasKey = true;
        } catch {
          stepError("Failed to save");
          barLine(c.dim(`Add to your shell: export LANGSMITH_API_KEY=${key}`));
          hasKey = true;
        }
      } else if (key) {
        barLine(c.yellow("Invalid \u2014 LangSmith keys start with lsv2_"));
        attempts++;
      } else {
        stepError("No API key configured");
        barLine(c.dim("/evolver:setup will not work until you set LANGSMITH_API_KEY"));
        barLine(c.dim("Run: export LANGSMITH_API_KEY=lsv2_pt_your_key"));
        break;
      }
    }
  }

  barEmpty();
  step(c.bold("langsmith-cli") + " " + c.dim("(required for LLM-as-judge)"));

  if (hasLangsmithCli) {
    stepDone("langsmith-cli installed");
  } else {
    barLine(c.dim("The evaluator agent uses it to read experiment outputs and write scores"));
    step("Installing langsmith-cli...");
    try {
      execSync("uv tool install langsmith-cli 2>/dev/null || pip install langsmith-cli 2>/dev/null || pip3 install langsmith-cli", { stdio: "pipe", timeout: 60000 });
      stepDone("langsmith-cli installed");

      if (hasKey && fs.existsSync(langsmithCredsFile)) {
        stepDone("langsmith-cli auto-authenticated");
      }
    } catch {
      stepError("Could not install langsmith-cli");
      barLine(c.dim("Install manually: uv tool install langsmith-cli"));
    }
  }
}

async function configureOptionalIntegrations(rl) {
  barEmpty();
  step(c.bold("Optional Integrations"));
  barEmpty();

  // Context7 MCP
  const hasContext7 = (() => {
    try {
      for (const p of [path.join(HOME, ".claude", "settings.json"), path.join(HOME, ".claude.json")]) {
        if (fs.existsSync(p)) {
          const s = JSON.parse(fs.readFileSync(p, "utf8"));
          if (s.mcpServers && (s.mcpServers.context7 || s.mcpServers.Context7)) return true;
        }
      }
    } catch {}
    return false;
  })();

  if (hasContext7) {
    stepDone("Context7 MCP already configured");
  } else {
    barLine(c.bold("Context7 MCP") + " \u2014 " + c.dim("up-to-date library documentation"));
    const c7Answer = await ask(rl, `${c.cyan(S.stepActive)}  Install Context7 MCP? [y/N]: `);
    if (c7Answer.trim().toLowerCase() === "y") {
      step("Installing Context7 MCP...");
      try {
        execSync("claude mcp add context7 -- npx -y @upstash/context7-mcp@latest", { stdio: "inherit" });
        stepDone("Context7 MCP configured");
      } catch {
        stepError("Failed to install Context7 MCP");
        barLine(c.dim("Run manually: claude mcp add context7 -- npx -y @upstash/context7-mcp@latest"));
      }
    }
  }

  barEmpty();

  // LangChain Docs MCP
  const hasLcDocs = (() => {
    try {
      for (const p of [path.join(HOME, ".claude", "settings.json"), path.join(HOME, ".claude.json")]) {
        if (fs.existsSync(p)) {
          const s = JSON.parse(fs.readFileSync(p, "utf8"));
          if (s.mcpServers && (s.mcpServers["docs-langchain"] || s.mcpServers["LangChain Docs"])) return true;
        }
      }
    } catch {}
    return false;
  })();

  if (hasLcDocs) {
    stepDone("LangChain Docs MCP already configured");
  } else {
    barLine(c.bold("LangChain Docs MCP") + " \u2014 " + c.dim("LangChain/LangGraph/LangSmith docs"));
    const lcAnswer = await ask(rl, `${c.cyan(S.stepActive)}  Install LangChain Docs MCP? [y/N]: `);
    if (lcAnswer.trim().toLowerCase() === "y") {
      step("Installing LangChain Docs MCP...");
      try {
        execSync("claude mcp add docs-langchain --transport http https://docs.langchain.com/mcp", { stdio: "inherit" });
        stepDone("LangChain Docs MCP configured");
      } catch {
        stepError("Failed to install LangChain Docs MCP");
        barLine(c.dim("Run manually: claude mcp add docs-langchain --transport http https://docs.langchain.com/mcp"));
      }
    }
  }
}

// ─── Main ───────────────────────────────────────────────────────────────────

async function main() {
  banner();

  header("harness-evolver");
  step(`Source: ${c.dim(`v${VERSION} \u2014 LangSmith-native agent optimization`)}`);

  // Version check
  try {
    const latest = execSync("npm view harness-evolver version", { stdio: "pipe", timeout: 5000 }).toString().trim();
    if (latest && latest !== VERSION) {
      barEmpty();
      stepError(`You're running v${VERSION} but v${c.cyan(latest)} is available`);
      barLine(c.dim(`Run: npx harness-evolver@${latest}`));
    }
  } catch {}

  barEmpty();

  // Python check
  if (!checkPython()) {
    stepError("python3 not found. Install Python 3.10+ first.");
    footer();
    process.exit(1);
  }
  stepDone("python3 found");

  // Detect runtimes
  const RUNTIMES = [
    { name: "Claude Code", dir: ".claude" },
    { name: "Cursor", dir: ".cursor" },
    { name: "Codex", dir: ".codex" },
    { name: "Windsurf", dir: ".windsurf" },
  ].filter(r => fs.existsSync(path.join(HOME, r.dir)));

  if (RUNTIMES.length === 0) {
    stepError("No supported runtime detected");
    barLine(c.dim("Install Claude Code, Cursor, Codex, or Windsurf first"));
    footer();
    process.exit(1);
  }

  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });

  // Runtime selection
  barEmpty();
  stepPrompt("Which runtime(s) to install for?");
  barEmpty();
  RUNTIMES.forEach((r, i) => barLine(`  ${c.bold(String(i + 1))}  ${r.name.padEnd(14)} ${c.dim(`~/${r.dir}`)}`));
  if (RUNTIMES.length > 1) {
    barLine(`  ${c.bold(String(RUNTIMES.length + 1))}  All`);
    barLine(c.dim("Select multiple: 1,2 or 1 2"));
  }

  const runtimeAnswer = await ask(rl, `${c.cyan(S.stepActive)}  Choice [1]: `);
  const runtimeInput = (runtimeAnswer.trim() || "1");

  let selected;
  if (runtimeInput === String(RUNTIMES.length + 1)) {
    selected = RUNTIMES;
  } else {
    const indices = runtimeInput.split(/[,\s]+/).map(s => parseInt(s, 10) - 1);
    selected = indices.filter(i => i >= 0 && i < RUNTIMES.length).map(i => RUNTIMES[i]);
  }
  if (selected.length === 0) selected = [RUNTIMES[0]];

  stepDone(`Target: ${c.cyan(selected.map(r => r.name).join(", "))}`);

  // Scope selection
  barEmpty();
  stepPrompt("Where to install?");
  barEmpty();
  barLine(`  ${c.bold("1")}  Global ${c.dim(`(~/${selected[0].dir})`)}`);
  barLine(`  ${c.bold("2")}  Local  ${c.dim(`(./${selected[0].dir})`)}`);

  const scopeAnswer = await ask(rl, `${c.cyan(S.stepActive)}  Choice [1]: `);
  const scope = (scopeAnswer.trim() === "2") ? "local" : "global";

  stepDone(`Scope: ${c.cyan(scope)}`);

  // Discover what we're installing
  const counts = countInstallables();
  barEmpty();
  step(`Found ${c.bold(`${counts.skills} skills, ${counts.agents} agents, ${counts.tools} tools`)}`);

  // Clean previous install
  barEmpty();
  step("Cleaning previous install...");
  for (const runtime of selected) {
    cleanPreviousInstall(runtime.dir, scope);
  }
  stepDone("Clean");

  // Install skills + agents
  barEmpty();
  for (const runtime of selected) {
    step(`Installing to ${c.bold(runtime.name)}...`);
    barEmpty();
    installSkillsAndAgents(runtime.dir, scope);
    barEmpty();
    stepDone(`${c.cyan(runtime.name)} ready`);
  }

  // Install tools
  barEmpty();
  step("Installing tools...");
  const toolCount = installTools();
  stepDone(`${toolCount} tools installed to ~/.evolver/tools/`);

  // Version marker
  const versionPath = path.join(HOME, ".evolver", "VERSION");
  fs.mkdirSync(path.dirname(versionPath), { recursive: true });
  fs.writeFileSync(versionPath, VERSION);

  // Install Python deps
  barEmpty();
  installPythonDeps();

  // Configure LangSmith
  await configureLangSmith(rl);

  // Optional integrations
  await configureOptionalIntegrations(rl);

  // Done
  barEmpty();
  stepDone(c.green("Done.") + "  Restart your agent tools to load the plugin.");
  barEmpty();
  barLine(c.dim("Commands:"));
  barLine(`  ${c.cyan("/evolver:setup")}   \u2014 configure LangSmith for your project`);
  barLine(`  ${c.cyan("/evolver:evolve")}  \u2014 run the optimization loop`);
  barLine(`  ${c.cyan("/evolver:status")} \u2014 check progress`);
  barLine(`  ${c.cyan("/evolver:deploy")}  \u2014 finalize and push`);
  barEmpty();
  barLine(c.dim("GitHub: https://github.com/raphaelchristi/harness-evolver"));
  footer();

  rl.close();
}

main().catch(err => {
  stepError(err.message);
  footer();
  process.exit(1);
});
