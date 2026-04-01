#!/usr/bin/env node
/**
 * Harness Evolver v3 installer.
 * Copies skills/agents/tools to runtime directories (GSD pattern).
 * Installs Python dependencies (langsmith + openevals).
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

  // Cleanup old v2 commands/ directory
  const oldCommandsDir = path.join(baseDir, "commands", "harness-evolver");
  if (fs.existsSync(oldCommandsDir)) {
    fs.rmSync(oldCommandsDir, { recursive: true, force: true });
    console.log(`  ${DIM}Cleaned up old commands/ directory${RESET}`);
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
  // v3: tools go to ~/.evolver/tools/
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

  // Also maintain legacy path for v2 backward compat
  const legacyDir = path.join(HOME, ".harness-evolver", "tools");
  if (fs.existsSync(legacyDir)) {
    // Update tools in legacy dir too
    for (const tool of fs.readdirSync(toolsSource)) {
      if (tool.endsWith(".py")) {
        copyFile(path.join(toolsSource, tool), path.join(legacyDir, tool));
      }
    }
    console.log(`  ${DIM}Also updated legacy ~/.harness-evolver/tools/${RESET}`);
  }
}

function installPythonDeps() {
  console.log(`\n  ${YELLOW}Installing Python dependencies...${RESET}`);

  // Try multiple pip variants
  const commands = [
    "pip install langsmith openevals",
    "uv pip install langsmith openevals",
    "pip3 install langsmith openevals",
    "python3 -m pip install langsmith openevals",
  ];

  for (const cmd of commands) {
    try {
      execSync(cmd, { stdio: "pipe", timeout: 120000 });
      console.log(`  ${GREEN}✓${RESET} langsmith + openevals installed`);
      return true;
    } catch {
      continue;
    }
  }

  console.log(`  ${YELLOW}!${RESET} Could not auto-install Python packages.`);
  console.log(`    Run manually: ${BOLD}pip install langsmith openevals${RESET}`);
  return false;
}

async function configureLangSmith(rl) {
  console.log(`\n  ${YELLOW}LangSmith Configuration${RESET} ${DIM}(required for v3)${RESET}\n`);

  // Check if already configured
  const langsmithCredsDir = process.platform === "darwin"
    ? path.join(HOME, "Library", "Application Support", "langsmith-cli")
    : path.join(HOME, ".config", "langsmith-cli");
  const langsmithCredsFile = path.join(langsmithCredsDir, "credentials");

  // Check env var
  if (process.env.LANGSMITH_API_KEY) {
    console.log(`  ${GREEN}✓${RESET} LANGSMITH_API_KEY found in environment`);
    return;
  }

  // Check credentials file
  if (fs.existsSync(langsmithCredsFile)) {
    console.log(`  ${GREEN}✓${RESET} LangSmith credentials found at ${DIM}${langsmithCredsFile}${RESET}`);
    return;
  }

  // Ask for API key
  console.log(`  ${BOLD}LangSmith API Key${RESET} — get yours at ${DIM}https://smith.langchain.com/settings${RESET}`);
  console.log(`  ${DIM}LangSmith is required for v3 (datasets, experiments, evaluators).${RESET}\n`);
  const apiKey = await ask(rl, `  ${YELLOW}Paste your LangSmith API key:${RESET} `);
  const key = apiKey.trim();

  if (key && key.startsWith("lsv2_")) {
    try {
      fs.mkdirSync(langsmithCredsDir, { recursive: true });
      fs.writeFileSync(langsmithCredsFile, `LANGSMITH_API_KEY=${key}\n`);
      console.log(`  ${GREEN}✓${RESET} API key saved to ${DIM}${langsmithCredsFile}${RESET}`);
    } catch {
      console.log(`  ${RED}Failed to save.${RESET} Add to your shell: export LANGSMITH_API_KEY=${key}`);
    }
  } else if (key) {
    console.log(`  ${YELLOW}Doesn't look like a LangSmith key (should start with lsv2_).${RESET}`);
    console.log(`  Add to your shell: ${BOLD}export LANGSMITH_API_KEY=your_key${RESET}`);
  } else {
    console.log(`  ${YELLOW}Skipped.${RESET} You must set LANGSMITH_API_KEY before using /evolver:setup`);
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

  // Install skills + agents
  console.log(`\n  ${BOLD}Installing skills & agents${RESET}\n`);
  for (const runtime of selected) {
    console.log(`  ${GREEN}${runtime.name}${RESET}:`);
    installSkillsAndAgents(runtime.dir, scope);
    console.log();
  }

  // Install tools
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
