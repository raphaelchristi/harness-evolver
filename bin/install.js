#!/usr/bin/env node
/**
 * Harness Evolver v3 installer.
 * Copies skills/agents/tools to runtime directories (GSD pattern).
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

const GREEN = "\x1b[38;2;0;255;136m";
const YELLOW = "\x1b[33m";
const RED = "\x1b[31m";
const DIM = "\x1b[2m";
const BOLD = "\x1b[1m";
const RESET = "\x1b[0m";

const LOGO = `${BOLD}${GREEN}
  ╦ ╦╔═╗╦═╗╔╗╔╔═╗╔═╗╔═╗  ╔═╗╦  ╦╔═╗╦  ╦  ╦╔═╗╦═╗
  ╠═╣╠═╣╠╦╝║║║║╣ ╚═╗╚═╗  ║╣ ╚╗╔╝║ ║║  ╚╗╔╝║╣ ╠╦╝
  ╩ ╩╩ ╩╩╚═╝╚╝╚═╝╚═╝╚═╝  ╚═╝ ╚╝ ╚═╝╩═╝ ╚╝ ╚═╝╩╚═
${RESET}
${DIM}${GREEN}  LangSmith-native agent optimization  v${VERSION}${RESET}
`;

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

function cleanPreviousInstall(runtimeDir, scope) {
  const baseDir = scope === "local"
    ? path.join(process.cwd(), runtimeDir)
    : path.join(HOME, runtimeDir);

  const skillsDir = path.join(baseDir, "skills");
  const agentsDir = path.join(baseDir, "agents");
  let cleaned = 0;

  // Remove ALL evolver/harness-evolver skills (any version)
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

  // Remove ALL evolver/harness-evolver agents
  if (fs.existsSync(agentsDir)) {
    for (const f of fs.readdirSync(agentsDir)) {
      if (f.startsWith("evolver-") || f.startsWith("harness-evolver-")) {
        fs.rmSync(path.join(agentsDir, f), { force: true });
        cleaned++;
      }
    }
  }

  // Remove old commands/ directory (v1)
  const oldCommandsDir = path.join(baseDir, "commands", "harness-evolver");
  if (fs.existsSync(oldCommandsDir)) {
    fs.rmSync(oldCommandsDir, { recursive: true, force: true });
    cleaned++;
  }

  // Remove old tools directories
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
    console.log(`  ${DIM}Cleaned ${cleaned} items from previous install${RESET}`);
  }
}

function installSkillsAndAgents(runtimeDir, scope) {
  const baseDir = scope === "local"
    ? path.join(process.cwd(), runtimeDir)
    : path.join(HOME, runtimeDir);

  const skillsDir = path.join(baseDir, "skills");
  const agentsDir = path.join(baseDir, "agents");

  // Skills — read SKILL.md name field, use directory name for filesystem
  const skillsSource = path.join(PLUGIN_ROOT, "skills");
  if (fs.existsSync(skillsSource)) {
    for (const skill of fs.readdirSync(skillsSource, { withFileTypes: true })) {
      if (!skill.isDirectory()) continue;
      const src = path.join(skillsSource, skill.name);
      const skillMd = path.join(src, "SKILL.md");
      if (!fs.existsSync(skillMd)) continue;

      // Read the skill name from frontmatter
      const content = fs.readFileSync(skillMd, "utf8");
      const nameMatch = content.match(/^name:\s*(.+)$/m);
      const skillName = nameMatch ? nameMatch[1].trim() : skill.name;

      const dest = path.join(skillsDir, skill.name);
      copyDir(src, dest);
      console.log(`  ${GREEN}✓${RESET} ${skillName}`);
    }
  }

  // Agents
  const agentsSource = path.join(PLUGIN_ROOT, "agents");
  if (fs.existsSync(agentsSource)) {
    fs.mkdirSync(agentsDir, { recursive: true });
    for (const agent of fs.readdirSync(agentsSource)) {
      if (!agent.endsWith(".md")) continue;
      copyFile(path.join(agentsSource, agent), path.join(agentsDir, agent));
      const agentName = agent.replace(".md", "");
      console.log(`  ${GREEN}✓${RESET} agent: ${agentName}`);
    }
  }
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
    console.log(`  ${GREEN}✓${RESET} ${count} tools installed to ~/.evolver/tools/`);
  }
}

function installPythonDeps() {
  const venvDir = path.join(HOME, ".evolver", "venv");
  const venvPython = path.join(venvDir, "bin", "python");
  const venvPip = path.join(venvDir, "bin", "pip");

  console.log(`\n  ${YELLOW}Setting up Python environment...${RESET}`);

  // Create venv if it doesn't exist
  if (!fs.existsSync(venvPython)) {
    console.log(`  Creating isolated venv at ~/.evolver/venv/`);
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
      console.log(`  ${RED}Failed to create venv.${RESET}`);
      console.log(`    Run manually: ${BOLD}python3 -m venv ~/.evolver/venv${RESET}`);
      return false;
    }
    console.log(`  ${GREEN}✓${RESET} venv created`);
  } else {
    console.log(`  ${GREEN}✓${RESET} venv exists at ~/.evolver/venv/`);
  }

  // Install/upgrade deps in the venv
  const installCommands = [
    `uv pip install --python "${venvPython}" langsmith`,
    `"${venvPip}" install --upgrade langsmith`,
    `"${venvPython}" -m pip install --upgrade langsmith`,
  ];

  for (const cmd of installCommands) {
    try {
      execSync(cmd, { stdio: "pipe", timeout: 120000 });
      console.log(`  ${GREEN}✓${RESET} langsmith installed in venv`);
      return true;
    } catch {
      continue;
    }
  }

  console.log(`  ${YELLOW}!${RESET} Could not install packages in venv.`);
  console.log(`    Run manually: ${BOLD}~/.evolver/venv/bin/pip install langsmith${RESET}`);
  return false;
}

async function configureLangSmith(rl) {
  console.log(`\n  ${BOLD}${GREEN}LangSmith Configuration${RESET} ${DIM}(required)${RESET}\n`);

  const langsmithCredsDir = process.platform === "darwin"
    ? path.join(HOME, "Library", "Application Support", "langsmith-cli")
    : path.join(HOME, ".config", "langsmith-cli");
  const langsmithCredsFile = path.join(langsmithCredsDir, "credentials");
  const hasLangsmithCli = checkCommand("langsmith-cli --version");

  // --- Step 1: API Key ---
  let hasKey = false;

  if (process.env.LANGSMITH_API_KEY) {
    console.log(`  ${GREEN}✓${RESET} LANGSMITH_API_KEY found in environment`);
    hasKey = true;
  } else if (fs.existsSync(langsmithCredsFile)) {
    try {
      const content = fs.readFileSync(langsmithCredsFile, "utf8");
      if (content.includes("LANGSMITH_API_KEY=lsv2_")) {
        console.log(`  ${GREEN}✓${RESET} API key found in credentials file`);
        hasKey = true;
      }
    } catch {}
  }

  if (!hasKey) {
    console.log(`  ${BOLD}LangSmith API Key${RESET} — get yours at ${DIM}https://smith.langchain.com/settings${RESET}`);
    console.log(`  ${DIM}LangSmith is required. The evolver won't work without it.${RESET}\n`);

    // Keep asking until they provide a key or explicitly skip
    let attempts = 0;
    while (!hasKey && attempts < 3) {
      const apiKey = await ask(rl, `  ${YELLOW}Paste your LangSmith API key (lsv2_pt_...):${RESET} `);
      const key = apiKey.trim();

      if (key && key.startsWith("lsv2_")) {
        try {
          fs.mkdirSync(langsmithCredsDir, { recursive: true });
          fs.writeFileSync(langsmithCredsFile, `LANGSMITH_API_KEY=${key}\n`);
          console.log(`  ${GREEN}✓${RESET} API key saved`);
          hasKey = true;
        } catch {
          console.log(`  ${RED}Failed to save.${RESET} Add to your shell: export LANGSMITH_API_KEY=${key}`);
          hasKey = true; // they have the key, just couldn't save
        }
      } else if (key) {
        console.log(`  ${YELLOW}Invalid — LangSmith keys start with lsv2_${RESET}`);
        attempts++;
      } else {
        // Empty input — skip
        console.log(`\n  ${RED}WARNING:${RESET} No API key configured.`);
        console.log(`  ${BOLD}/evolver:setup will not work${RESET} until you set LANGSMITH_API_KEY.`);
        console.log(`  Run: ${DIM}export LANGSMITH_API_KEY=lsv2_pt_your_key${RESET}\n`);
        break;
      }
    }
  }

  // --- Step 2: langsmith-cli (required for evaluator agent) ---
  if (hasLangsmithCli) {
    console.log(`  ${GREEN}✓${RESET} langsmith-cli installed`);
  } else {
    console.log(`\n  ${BOLD}langsmith-cli${RESET} — ${YELLOW}required${RESET} for LLM-as-judge evaluation`);
    console.log(`  ${DIM}The evaluator agent uses it to read experiment outputs and write scores.${RESET}`);
    console.log(`\n  Installing langsmith-cli...`);
    try {
      execSync("uv tool install langsmith-cli 2>/dev/null || pip install langsmith-cli 2>/dev/null || pip3 install langsmith-cli", { stdio: "pipe", timeout: 60000 });
      console.log(`  ${GREEN}✓${RESET} langsmith-cli installed`);

      // If we have a key, auto-authenticate
      if (hasKey && fs.existsSync(langsmithCredsFile)) {
        console.log(`  ${GREEN}✓${RESET} langsmith-cli auto-authenticated (credentials file exists)`);
      }
    } catch {
      console.log(`  ${RED}!${RESET} Could not install langsmith-cli.`);
      console.log(`    ${BOLD}This is required.${RESET} Install manually: ${DIM}uv tool install langsmith-cli${RESET}`);
    }
  }
}

async function configureOptionalIntegrations(rl) {
  console.log(`\n  ${YELLOW}Optional Integrations${RESET}\n`);

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
    console.log(`  ${GREEN}✓${RESET} Context7 MCP already configured`);
  } else {
    console.log(`  ${BOLD}Context7 MCP${RESET} — up-to-date library documentation (LangChain, OpenAI, etc.)`);
    const c7Answer = await ask(rl, `\n  ${YELLOW}Install Context7 MCP? [y/N]:${RESET} `);
    if (c7Answer.trim().toLowerCase() === "y") {
      try {
        execSync("claude mcp add context7 -- npx -y @upstash/context7-mcp@latest", { stdio: "inherit" });
        console.log(`\n  ${GREEN}✓${RESET} Context7 MCP configured`);
      } catch {
        console.log(`\n  ${RED}Failed.${RESET} Install manually: claude mcp add context7 -- npx -y @upstash/context7-mcp@latest`);
      }
    }
  }

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
    console.log(`  ${GREEN}✓${RESET} LangChain Docs MCP already configured`);
  } else {
    console.log(`\n  ${BOLD}LangChain Docs MCP${RESET} — LangChain/LangGraph/LangSmith documentation`);
    const lcAnswer = await ask(rl, `\n  ${YELLOW}Install LangChain Docs MCP? [y/N]:${RESET} `);
    if (lcAnswer.trim().toLowerCase() === "y") {
      try {
        execSync("claude mcp add docs-langchain --transport http https://docs.langchain.com/mcp", { stdio: "inherit" });
        console.log(`\n  ${GREEN}✓${RESET} LangChain Docs MCP configured`);
      } catch {
        console.log(`\n  ${RED}Failed.${RESET} Install manually: claude mcp add docs-langchain --transport http https://docs.langchain.com/mcp`);
      }
    }
  }
}

async function main() {
  console.log(LOGO);

  // Check if running latest version (npx may cache an old one)
  try {
    const latest = execSync("npm view harness-evolver version", { stdio: "pipe", timeout: 5000 }).toString().trim();
    if (latest && latest !== VERSION) {
      console.log(`  ${YELLOW}!${RESET} You're running v${VERSION} but v${latest} is available.`);
      console.log(`    Run: ${BOLD}npx harness-evolver@${latest}${RESET} or ${BOLD}npx --yes harness-evolver@latest${RESET}\n`);
    }
  } catch {}

  if (!checkPython()) {
    console.error(`  ${RED}ERROR:${RESET} python3 not found. Install Python 3.10+ first.`);
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
  console.log(`\n  ${YELLOW}Which runtime(s) to install for?${RESET}\n`);
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
  console.log(`\n  ${YELLOW}Where to install?${RESET}\n`);
  console.log(`  1) Global  (~/${selected[0].dir}) — available in all projects`);
  console.log(`  2) Local   (./${selected[0].dir}) — this project only`);

  const scopeAnswer = await ask(rl, `\n  ${YELLOW}Choice [1]:${RESET} `);
  const scope = (scopeAnswer.trim() === "2") ? "local" : "global";

  // Clean previous install (remove ALL old files before installing new ones)
  console.log(`\n  ${BOLD}Cleaning previous install${RESET}`);
  for (const runtime of selected) {
    cleanPreviousInstall(runtime.dir, scope);
  }

  // Install skills + agents
  console.log(`\n  ${BOLD}Installing skills & agents${RESET}\n`);
  for (const runtime of selected) {
    console.log(`  ${GREEN}${runtime.name}${RESET}:`);
    installSkillsAndAgents(runtime.dir, scope);
    console.log();
  }

  // Install tools (fresh — old dir was cleaned above)
  console.log(`  ${BOLD}Installing tools${RESET}`);
  installTools();

  // Version marker
  const versionPath = path.join(HOME, ".evolver", "VERSION");
  fs.mkdirSync(path.dirname(versionPath), { recursive: true });
  fs.writeFileSync(versionPath, VERSION);

  // Install Python deps
  installPythonDeps();

  // Configure LangSmith (required)
  await configureLangSmith(rl);

  // Optional integrations
  await configureOptionalIntegrations(rl);

  // Done
  console.log(`\n  ${GREEN}${BOLD}Setup complete!${RESET}\n`);
  console.log(`  ${DIM}Restart Claude Code, then:${RESET}`);
  console.log(`    ${GREEN}/evolver:setup${RESET}     — configure LangSmith for your project`);
  console.log(`    ${GREEN}/evolver:evolve${RESET}    — run the optimization loop`);
  console.log(`    ${GREEN}/evolver:status${RESET}    — check progress`);
  console.log(`    ${GREEN}/evolver:deploy${RESET}    — finalize and push`);
  console.log(`\n  ${DIM}GitHub: https://github.com/raphaelchristi/harness-evolver${RESET}\n`);

  rl.close();
}

main().catch(err => {
  console.error(`  ${RED}ERROR:${RESET} ${err.message}`);
  process.exit(1);
});
